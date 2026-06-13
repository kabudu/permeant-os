import socket
import json
import struct
from permeantos.memory_graph import AgentMemoryGraph

def send_frame(sock: socket.socket, msg: dict):
    serialized = json.dumps(msg).encode("utf-8")
    length = len(serialized)
    sock.sendall(struct.pack(">I", length))
    sock.sendall(serialized)

def recv_frame(sock: socket.socket) -> dict:
    len_bytes = sock.recv(4)
    if not len_bytes or len(len_bytes) < 4:
        raise ConnectionError("Socket closed while reading length prefix")
    length = struct.unpack(">I", len_bytes)[0]
    
    data = bytearray()
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet:
            raise ConnectionError("Socket closed while reading content payload")
        data.extend(packet)
        
    return json.loads(data.decode("utf-8"))

class PermeantClient:
    """
    Python client for interacting with PermeantOS Hypervisor daemon instances.
    """
    def __init__(self, host="127.0.0.1", port=9099):
        self.host = host
        self.port = port
        
    def migrate_agent(
        self,
        model_arch: str,
        config_hash: str,
        memory_graph: AgentMemoryGraph,
        quantize=False
    ) -> bool:
        """
        Runs an end-to-end GQA agent state migration to the target daemon.
        """
        print(f"[SDK] Initiating connection to target hypervisor daemon at {self.host}:{self.port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((self.host, self.port))
        except Exception as e:
            print(f"[SDK] Connection failed: {e}")
            return False
            
        try:
            # 1. Capability Exchange
            print("[SDK] Exchanging capabilities...")
            cap_req = {
                "CapabilityRequest": {
                    "model_architecture": model_arch,
                    "attention_type": "gqa",
                    "seq_len": len(memory_graph.token_ids)
                }
            }
            send_frame(sock, cap_req)
            
            cap_resp = recv_frame(sock)
            if "CapabilityResponse" not in cap_resp:
                print(f"[SDK] Protocol error: expected CapabilityResponse, got {cap_resp}")
                return False
                
            resp_info = cap_resp["CapabilityResponse"]
            if not resp_info["accepted"]:
                print(f"[SDK] Migration rejected: {resp_info.get('error_message')}")
                return False
            print(f"[SDK] Connection accepted. Target device: {resp_info['target_device']}")
            
            # 2. Build and Send USXF Header
            print("[SDK] Building USXF v1.1 metadata header...")
            header = memory_graph.serialize_metadata_header(model_arch, config_hash)
            if quantize:
                header["transfer_quantization"] = {
                    "scheme": "fp8",
                    "group_size": None,
                    "scales": None
                }
                
            # Envelope packaging (simulating EncryptedEnvelope)
            envelope = {
                "HeaderEnvelope": {
                    "ciphertext": list(json.dumps(header).encode("utf-8")), # mock encrypted bytes representation
                    "nonce": list(b"\x00" * 12),
                    "signature": list(b"\xff" * 64),
                    "public_key": list(b"\xaa" * 32)
                }
            }
            send_frame(sock, envelope)
            
            header_ack = recv_frame(sock)
            if "HeaderAck" not in header_ack or not header_ack["HeaderAck"]["accepted"]:
                print("[SDK] Target rejected header validation.")
                return False
            print("[SDK] Header successfully registered by target.")
            
            # 3. Stream block-wise mock payloads
            n_layers = header["model_cache_spec"]["n_layers"]
            n_kv_heads = header["model_cache_spec"]["n_kv_heads"]
            head_dim = header["model_cache_spec"]["head_dim"]
            block_size = header["block_size"]
            seq_len = header["seq_len"]
            
            num_blocks = (seq_len + block_size - 1) // block_size
            total_elements = block_size * n_kv_heads * head_dim
            
            # We send dummy floats (all 1.0) for this client-side demo
            floats_data = [1.0] * total_elements
            if quantize:
                # E4M3 FP8 representation of 1.0 (sign=0, exp=7, mant=0 -> 0x38)
                byte_payload = [0x38] * total_elements
            else:
                # Raw f32 big-endian bytes
                byte_payload = []
                for f in floats_data:
                    byte_payload.extend(list(struct.pack(">f", f)))
                    
            print(f"[SDK] Streaming {n_layers} layers with {num_blocks} blocks each...")
            for layer in range(n_layers):
                for block in range(num_blocks):
                    # Key chunk
                    k_chunk = {
                        "PayloadChunk": {
                            "chunk_index": block,
                            "layer_index": layer,
                            "tensor_name": f"layer.{layer}.key",
                            "data": byte_payload,
                            "crc32": 0 # Simple mock crc32
                        }
                    }
                    # Compute CRC32
                    import binascii
                    crc = binascii.crc32(bytes(byte_payload)) & 0xffffffff
                    k_chunk["PayloadChunk"]["crc32"] = crc
                    
                    send_frame(sock, k_chunk)
                    recv_frame(sock) # wait for ChunkAck
                    
                    # Value chunk
                    v_chunk = {
                        "PayloadChunk": {
                            "chunk_index": block,
                            "layer_index": layer,
                            "tensor_name": f"layer.{layer}.value",
                            "data": byte_payload,
                            "crc32": 0
                        }
                    }
                    crc_v = binascii.crc32(bytes(byte_payload)) & 0xffffffff
                    v_chunk["PayloadChunk"]["crc32"] = crc_v
                    
                    send_frame(sock, v_chunk)
                    recv_frame(sock)
                    
            # 4. Commit Migration
            print("[SDK] Sending Commit Request...")
            send_frame(sock, {"CommitRequest": None})
            
            commit_resp = recv_frame(sock)
            if "CommitResponse" not in commit_resp or not commit_resp["CommitResponse"]["success"]:
                print(f"[SDK] Target failed to commit migration: {commit_resp.get('CommitResponse', {}).get('error_message')}")
                return False
                
            print("[SDK] Migration completed successfully!")
            return True
            
        finally:
            sock.close()
            print("[SDK] Connection closed.")

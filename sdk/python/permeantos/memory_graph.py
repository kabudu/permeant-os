import hashlib
import json
import time

USXF_VERSION = "1.1"
AGENT_MEMORY_GRAPH_SCHEMA_ID = "https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json"
AGENT_MEMORY_GRAPH_GRAPH_VERSION = "0.1"


class AgentMemoryGraph:
    """
    Tracks agent convo turn history, token ID lists, role tags, and turn boundaries.
    Generates standard USXF v1.1 chat template state metadata headers.
    """
    def __init__(self, template_name="llama-3.1-instruct"):
        self.template_name = template_name
        self.token_ids = []
        self.turn_boundaries = [0]
        self.roles = []
        
    def attach_agent_memory(self, turn_tokens: list, role: str):
        """
        Appends a new turn of token IDs and associates it with a system/user/assistant role.
        """
        if not isinstance(turn_tokens, list):
            raise TypeError("turn_tokens must be a list of integer token IDs")
        if role not in ["system", "user", "assistant", "tool"]:
            raise ValueError(f"Invalid agent role: {role}")
            
        self.token_ids.extend(turn_tokens)
        self.turn_boundaries.append(len(self.token_ids))
        self.roles.append(role)
        
    def get_template_hash(self) -> str:
        """
        Computes SHA-256 hash of the template configuration.
        """
        hasher = hashlib.sha256()
        hasher.update(self.template_name.encode("utf-8"))
        return f"sha256:{hasher.hexdigest()}"
        
    def to_usxf_chat_state(self) -> dict:
        """
        Generates standard chat_state section for USXF v1.1 metadata.
        """
        return {
            "template_name": self.template_name,
            "template_hash": self.get_template_hash(),
            "turn_boundaries": self.turn_boundaries,
            "roles": self.roles
        }

    def serialize_metadata_header(self, model_arch: str, config_hash: str) -> dict:
        """
        Assembles a full USXF v1.1 metadata dictionary envelope.
        """
        total_tokens = len(self.token_ids)
        block_size = 256
        num_blocks = (total_tokens + block_size - 1) // block_size
        
        # Calculate content-addressable block hashes
        block_hashes = []
        for i in range(num_blocks):
            block_tokens = self.token_ids[i * block_size : (i + 1) * block_size]
            hasher = hashlib.sha256()
            for token in block_tokens:
                hasher.update(int(token).to_bytes(4, byteorder="big"))
            block_hashes.append(f"sha256:{hasher.hexdigest()}")
            
        return {
            "usxf_version": USXF_VERSION,
            "model_architecture": model_arch,
            "model_identity": {
                "config_hash": f"sha256:{config_hash}",
                "weights_revision": f"hf:meta-llama/{model_arch}@main"
            },
            "attention_type": "gqa",
            "model_cache_spec": {
                "n_layers": 32,
                "n_q_heads": 32,
                "n_kv_heads": 8,
                "head_dim": 128,
                "hidden_size": 4096,
                "max_position_embeddings": 131072,
                "rope_theta": 500000.0,
                "sliding_window": None
            },
            "chat_state": self.to_usxf_chat_state(),
            "token_ids": self.token_ids,
            "seq_len": total_tokens,
            "batch_size": 1,
            "dtype": "bfloat16",
            "block_size": block_size,
            "block_hashes": block_hashes,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "extractor_id": "permeant-os-python-sdk-v0.1.0",
            "checksum": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "signature": ""
        }

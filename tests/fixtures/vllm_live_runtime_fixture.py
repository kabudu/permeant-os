class RecordingRuntime:
    def __init__(self):
        self.registered = []

    def register_permeant_block(self, payload, request=None):
        self.registered.append(payload["hash"])
        return {"success": True}

    def verify_permeant_hashes(self, payload, request=None):
        missing = [hash_value for hash_value in payload["block_hashes"] if hash_value not in self.registered]
        if missing:
            return {"success": False, "missing_hashes": missing}
        return {"success": True}

    def export_reverse_runtime_state(self, payload=None, request=None):
        return {
            "success": True,
            "reverse_runtime_state": {
                "schema_version": "permeantos-vllm-reverse-runtime-state-v0",
                "status": "target_runtime_state_exported",
                "generated_token_ids": [101, 102],
                "proof_hash": "sha256:fixture",
            },
        }


class RegisterOnlyRuntime:
    def __init__(self):
        self.registered = []

    def register_permeant_block(self, payload, request=None):
        self.registered.append(payload["hash"])
        return True


def _make_combined_cache(num_blocks, block_size, num_heads, head_dim):
    return [
        [
            [
                [[0.0 for _ in range(head_dim)] for _ in range(num_heads)]
                for _ in range(block_size)
            ]
            for _ in range(2)
        ]
        for _ in range(num_blocks)
    ]


class TensorBackedRuntime:
    def __init__(self):
        self.permeant_layer_map = {0: "model.layers.0"}
        self.kv_caches = {"model.layers.0": _make_combined_cache(1, 4, 2, 3)}
        self.registered_hashes = set()


_RECORDING = RecordingRuntime()
_REGISTER_ONLY = RegisterOnlyRuntime()
_TENSOR_BACKED = TensorBackedRuntime()


def build_tensor_backed_payload(hash_value="sha256:tensor-runtime"):
    block_size = 4
    kv_heads = 2
    head_dim = 3
    key_blocks = [
        [
            [
                [float(100 * head + 10 * dim + token) for token in range(block_size)]
                for dim in range(head_dim)
            ]
            for head in range(kv_heads)
        ]
    ]
    value_blocks = [
        [
            [
                [float(1000 + 100 * head + 10 * token + dim) for dim in range(head_dim)]
                for token in range(block_size)
            ]
            for head in range(kv_heads)
        ]
    ]
    return {
        "hash": hash_value,
        "block_size": block_size,
        "layer_count": 1,
        "layers": [
            {
                "layer_index": 0,
                "seq_len": block_size,
                "kv_heads": kv_heads,
                "head_dim": head_dim,
                "key_blocks": key_blocks,
                "value_blocks": value_blocks,
            }
        ],
    }


def reset_tensor_backed_runtime():
    _TENSOR_BACKED.kv_caches["model.layers.0"] = _make_combined_cache(1, 4, 2, 3)
    _TENSOR_BACKED.registered_hashes = set()


def snapshot_tensor_backed_runtime():
    cache = _TENSOR_BACKED.kv_caches["model.layers.0"]
    return {
        "registered_hashes": sorted(_TENSOR_BACKED.registered_hashes),
        "key_first_token": cache[0][0][0][0][0],
        "key_last_token": cache[0][0][3][1][2],
        "value_first_token": cache[0][1][0][0][0],
        "value_last_token": cache[0][1][3][1][2],
    }


def get_recording_runtime(payload=None, request=None):
    return _RECORDING


def get_register_only_runtime(payload=None, request=None):
    return _REGISTER_ONLY


def get_tensor_backed_runtime(payload=None, request=None):
    return _TENSOR_BACKED

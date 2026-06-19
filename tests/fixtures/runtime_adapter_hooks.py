def extractor_hook(request):
    seq_len = int(request["seq_len"])
    n_layers = int(request["n_layers"])
    n_kv_heads = int(request["n_kv_heads"])
    head_dim = int(request["head_dim"])
    tensors = []
    for layer in range(n_layers):
        for suffix, value in (("key", 0.25), ("value", 0.75)):
            tensors.append(
                {
                    "name": f"layer.{layer}.{suffix}",
                    "shape": [seq_len, n_kv_heads, head_dim],
                    "data": [value] * (n_kv_heads * seq_len * head_dim),
                }
            )
    return {"tensors": tensors}


def graph_span_extractor_hook(request):
    payload = extractor_hook(request)
    payload["agent_graph_span_metadata"] = {
        "version": "0.1",
        "source_runtime": "fixture-mlx",
        "model_id": "fixture-model",
        "prompt": {
            "byte_hash": "sha256:" + "a" * 64,
            "token_hash": "sha256:" + "b" * 64,
            "token_count": int(request["seq_len"]),
            "tokenizer_hash": "sha256:" + "c" * 64,
        },
        "kv_spans": [
            {
                "node_id": "checkpoint:prompt",
                "token_start": 0,
                "token_end": int(request["seq_len"]),
                "cache_ref": "kv:fixture:prefill",
                "tokenizer_hash": "sha256:" + "c" * 64,
                "block_hashes": ["sha256:" + "d" * 64],
            }
        ],
        "binding": {
            "prompt_used_for_prefill": True,
            "same_prompt_required_on_target": True,
        },
    }
    return payload


def injector_hook(request):
    action = request["action"]
    if action == "inject_block":
        return {"success": True}
    if action == "verify_continuation":
        if request.get("expected_hashes"):
            return {"success": True}
        return {"success": False, "error": "expected_hashes was empty"}
    return {"success": False, "error": f"unsupported action: {action}"}

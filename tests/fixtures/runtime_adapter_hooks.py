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


def injector_hook(request):
    action = request["action"]
    if action == "inject_block":
        return {"success": True}
    if action == "verify_continuation":
        if request.get("expected_hashes"):
            return {"success": True}
        return {"success": False, "error": "expected_hashes was empty"}
    return {"success": False, "error": f"unsupported action: {action}"}

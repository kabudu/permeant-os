# Live runtime HTTP bridge

This bridge is the most practical next step before a private in-memory vLLM connector.

It splits the target integration into two stable pieces:
- `adapters/vllm_runtime_bridge.py` prepares canonical PermeantOS tensors as vLLM-style block tensors.
- `adapters/vllm_http_runtime_hook.py` forwards those prepared blocks to a local HTTP sidecar.
- `adapters/vllm_runtime_receiver.py` receives them, persists them by block hash, and can call a local consumer hook.

## Source host

For a live MLX or `mlx_lm` process:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD="python /ABS/PATH/adapters/mlx_extractor.py"
export PERMEANT_EXTRACTOR_HOOK="/ABS/PATH/adapters/mlx_hook_template.py:extractor_hook"
export PERMEANT_MLX_CACHE_PROVIDER="/ABS/PATH/adapters/mlx_lm_runtime_provider.py:get_live_cache"

export PERMEANT_MLX_RUNTIME_MODULE="my_runtime_module"
export PERMEANT_MLX_RUNTIME_OBJECT="runtime_or_session"
export PERMEANT_MLX_RUNTIME_CALL=1
```

If the cache is not on a default path, set:

```bash
export PERMEANT_MLX_RUNTIME_CACHE_PATH="session.cache,kv_cache"
```

## Target host

Start the sidecar:

```bash
python /ABS/PATH/adapters/vllm_runtime_receiver.py \
  --host 127.0.0.1 \
  --port 29100 \
  --state-dir /tmp/permeant-vllm-state
```

Then point the injector hook at the HTTP client:

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD="python /ABS/PATH/adapters/vllm_injector.py"
export PERMEANT_INJECTOR_HOOK="/ABS/PATH/adapters/vllm_hook_template.py:injector_hook"
export PERMEANT_VLLM_RUNTIME_HOOK="/ABS/PATH/adapters/vllm_http_runtime_hook.py:runtime_hook"
export PERMEANT_VLLM_RUNTIME_URL="http://127.0.0.1:29100"
```

Optional auth:

```bash
export PERMEANT_VLLM_RUNTIME_TOKEN="replace-me"
```

Use the same token when starting the sidecar.

## Consumer hook

To connect this to a real vLLM-adjacent process, run the sidecar with:

```bash
export PERMEANT_VLLM_CONSUMER_HOOK="/ABS/PATH/my_consumer.py:consume"
```

Your consumer hook receives the prepared payload:

```python
def consume(payload):
    # payload["layers"][i]["key_blocks"]
    # payload["layers"][i]["value_blocks"]
    return {"success": True}
```

If the consumer returns success, the receiver acknowledges the block hash so continuation checks pass.

## What this proves

This path is strong enough to validate:
- live source-process extraction
- real canonical transfer
- target-side vLLM block shaping
- target-side staging and acknowledgement over a stable IPC boundary

What it does not prove by itself:
- direct registration into vLLM private memory structures
- exact continuation from a fully live target runtime

# Live runtime source HTTP bridge

When the extractor command runs in a separate process, importing a live MLX object directly is not always practical.

This bridge gives the source side a stable IPC path:
- `adapters/mlx_runtime_exporter.py` exposes `/extract` on localhost
- `adapters/mlx_http_cache_provider.py` fetches that payload
- `adapters/mlx_hook_template.py` can use the HTTP provider as `PERMEANT_MLX_CACHE_PROVIDER`

## Source host setup

Start the exporter near the live MLX process:

```bash
export PERMEANT_MLX_EXPORTER_HOOK="/ABS/PATH/my_mlx_provider.py:provider"
export PERMEANT_MLX_RUNTIME_TOKEN="replace-me"

python /ABS/PATH/adapters/mlx_runtime_exporter.py \
  --host 127.0.0.1 \
  --port 29101
```

Then point PermeantOS at the HTTP provider:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD="python /ABS/PATH/adapters/mlx_extractor.py"
export PERMEANT_EXTRACTOR_HOOK="/ABS/PATH/adapters/mlx_hook_template.py:extractor_hook"
export PERMEANT_MLX_CACHE_PROVIDER="/ABS/PATH/adapters/mlx_http_cache_provider.py:get_live_cache"
export PERMEANT_MLX_RUNTIME_URL="http://127.0.0.1:29101"
export PERMEANT_MLX_RUNTIME_TOKEN="replace-me"
```

## Provider contract

Your exporter hook should return the extractor JSON contract directly:

```python
def provider(request):
    return {
        "tensors": [
            {"name": "layer.0.key", "shape": [seq_len, kv_heads, head_dim], "data": [...]},
            {"name": "layer.0.value", "shape": [seq_len, kv_heads, head_dim], "data": [...]},
        ]
    }
```

This is the cleanest path when the live MLX process is not safely importable from the extractor command.

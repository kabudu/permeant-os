# First real cross-host run

This is the shortest path from the current validated bridge code to a real laptop-to-GPU-host experiment.

Assumptions:
- source host is your laptop running an MLX-based runtime
- target host is the disposable Linux GPU box
- PermeantOS transport/orchestrator is already built
- you will fill in two concrete integration files:
  - `adapters/my_mlx_provider.py`
  - `adapters/my_vllm_consumer.py`

## 1. Source host: expose live MLX cache over localhost

Edit:
- `adapters/my_mlx_provider.py`

Implement:
- `get_live_runtime()`
- optionally adjust `extract_cache_object()`

Then start the source exporter:

```bash
export PERMEANT_MLX_EXPORTER_HOOK="/ABS/PATH/adapters/my_mlx_provider.py:provider"
export PERMEANT_MLX_RUNTIME_TOKEN="replace-me"

python /ABS/PATH/adapters/mlx_runtime_exporter.py \
  --host 127.0.0.1 \
  --port 29101
```

Configure the extractor side:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD="python /ABS/PATH/adapters/mlx_extractor.py"
export PERMEANT_EXTRACTOR_HOOK="/ABS/PATH/adapters/mlx_hook_template.py:extractor_hook"
export PERMEANT_MLX_CACHE_PROVIDER="/ABS/PATH/adapters/mlx_http_cache_provider.py:get_live_cache"
export PERMEANT_MLX_RUNTIME_URL="http://127.0.0.1:29101"
export PERMEANT_MLX_RUNTIME_TOKEN="replace-me"
```

## 2. Target host: receive prepared blocks and hand them to the live runtime

Edit:
- `adapters/my_vllm_consumer.py`

Implement:
- `get_target_runtime()`
- `register_prepared_block()`

Optional stable spool fallback:
- if you are not ready for direct runtime registration, use `adapters/vllm_directory_consumer.py` first

Start the target receiver:

```bash
export PERMEANT_VLLM_CONSUMER_HOOK="/ABS/PATH/adapters/my_vllm_consumer.py:consume"
export PERMEANT_VLLM_RUNTIME_TOKEN="replace-me"

python /ABS/PATH/adapters/vllm_runtime_receiver.py \
  --host 127.0.0.1 \
  --port 29100 \
  --state-dir /tmp/permeant-vllm-state
```

Configure the injector side:

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD="python /ABS/PATH/adapters/vllm_injector.py"
export PERMEANT_INJECTOR_HOOK="/ABS/PATH/adapters/vllm_hook_template.py:injector_hook"
export PERMEANT_VLLM_RUNTIME_HOOK="/ABS/PATH/adapters/vllm_http_runtime_hook.py:runtime_hook"
export PERMEANT_VLLM_RUNTIME_URL="http://127.0.0.1:29100"
export PERMEANT_VLLM_RUNTIME_TOKEN="replace-me"
```

## 3. Run the migration

With the source exporter and target receiver both up:

```bash
./target/debug/permeant-cli daemon --addr 0.0.0.0:29099
```

From the source host:

```bash
./target/debug/permeant-cli sim-migrate \
  --target-addr TARGET_HOST:29099 \
  --seq-len 2048 \
  --quant
```

If your real runtime needs a different command path than `sim-migrate`, keep the same environment variables and swap in the real migration entrypoint once available.

## 4. What success looks like

Minimum success:
- source exporter returns live cache tensors
- target receiver persists and acknowledges all block hashes
- PermeantOS writes a committed manifest

Full milestone success:
- target consumer registers the incoming blocks into the live runtime
- target runtime produces a continuation from migrated state
- docs record the benchmark and any divergence observations

## 5. Recommended first fallback

If direct target registration is not ready yet:
- use `adapters/vllm_directory_consumer.py:consume`
- confirm the target receives correct staged payloads
- then replace only the consumer hook with the real runtime registration path

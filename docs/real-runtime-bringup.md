# Real runtime bring-up guide

This is the next milestone after the successful June 14, 2026 simulated cross-host migration.

What we have already proven:
- Laptop-to-cloud orchestration works.
- The transport, manifest capture, and teardown flow work.
- The command-backed adapter seam works.
- The target can receive real canonical tensors and convert them into vLLM block layout.

What is not yet proven end-to-end:
- Extraction from a live MLX runtime on the laptop.
- Injection into a live target runtime memory manager such as vLLM.
- Continuation equivalence from the injected target runtime.

## New bridge components in this repo

Source-side:
- `adapters/mlx_extractor.py`: command entry point used by the Rust extractor crate.
- `adapters/mlx_hook_template.py`: usable live hook that turns a real MLX cache object into extractor JSON.
- `adapters/mlx_runtime_bridge.py`: cache-shape normalization helpers.

Target-side:
- `adapters/vllm_injector.py`: command entry point used by the Rust injector crate.
- `adapters/vllm_hook_template.py`: usable live hook for injection requests.
- `adapters/vllm_runtime_bridge.py`: converts canonical `[seq, kv_heads, head_dim]` tensors into vLLM block layout.

## Source host: MLX laptop wiring

Set the extractor to command mode:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD="python /ABS/PATH/TO/adapters/mlx_extractor.py"
export PERMEANT_EXTRACTOR_HOOK="/ABS/PATH/TO/adapters/mlx_hook_template.py:extractor_hook"
```

Point the hook at a callable in your real MLX runtime process:

```bash
export PERMEANT_MLX_CACHE_PROVIDER="/ABS/PATH/TO/my_mlx_runtime_bridge.py:get_live_cache"
```

Your `get_live_cache` callable may accept either:
- no arguments, or
- the extractor request JSON object

It must return one of these shapes:
- `[(key0, value0), (key1, value1), ...]`
- `[{"key": key0, "value": value0}, {"key": key1, "value": value1}, ...]`
- `{"layers": ...}` or `{"kv_cache": ...}` containing one of the forms above

The bridge normalizes common layouts to canonical PermeantOS tensors named:
- `layer.0.key`
- `layer.0.value`
- `layer.1.key`
- `layer.1.value`
- and so on

Expected normalized tensor shape:
- `[seq_len, kv_heads, head_dim]`

The bridge currently tolerates these common variants:
- `[seq_len, kv_heads, head_dim]`
- `[1, seq_len, kv_heads, head_dim]`
- `[kv_heads, seq_len, head_dim]` when `seq_len` is available in the request

## Target host: vLLM wiring

Set the injector to command mode:

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD="python /ABS/PATH/TO/adapters/vllm_injector.py"
export PERMEANT_INJECTOR_HOOK="/ABS/PATH/TO/adapters/vllm_hook_template.py:injector_hook"
export PERMEANT_VLLM_STATE_DIR="/tmp/permeant-vllm-state"
```

Optional: point the hook at a runtime-specific connector bridge:

```bash
export PERMEANT_VLLM_RUNTIME_HOOK="/ABS/PATH/TO/my_vllm_runtime_bridge.py:runtime_hook"
```

Without `PERMEANT_VLLM_RUNTIME_HOOK`, the target still does useful work:
- converts canonical tensors into vLLM block layout
- persists one JSON state file per transferred block hash
- verifies continuation readiness by checking whether all referenced hashes were staged

That means the next experiment can already prove:
- live MLX extraction
- real canonical transfer
- correct target-side vLLM block shaping

The remaining gap for full continuation is the final runtime-specific memory registration step.

## Runtime hook contract for the vLLM side

The optional runtime hook is called in two modes.

For `inject_block`, it receives the prepared block state:

```python
{
  "hash": "sha256:...",
  "block_size": 256,
  "layer_count": 32,
  "layers": [
    {
      "layer_index": 0,
      "seq_len": 256,
      "kv_heads": 8,
      "head_dim": 128,
      "key_blocks": [[[...]]],
      "value_blocks": [[[...]]]
    }
  ]
}
```

For `verify_continuation`, it receives the raw verification payload:

```python
{
  "block_hashes": ["sha256:...", "sha256:..."]
}
```

It should return one of:

```python
{"success": True}
{"success": False, "missing_hashes": ["sha256:..."]}
{"success": False, "error": "reason"}
```

## Minimal source bridge example

```python
# my_mlx_runtime_bridge.py

def get_live_cache(request):
    runtime = get_my_runtime_singleton()
    return runtime.kv_cache.layers
```

## Minimal target bridge example

```python
# my_vllm_runtime_bridge.py

def runtime_hook(payload, request=None):
    if "layers" in payload:
        register_payload_into_runtime(payload)
        return {"success": True}
    if "block_hashes" in payload:
        return verify_hashes_are_committed(payload["block_hashes"])
    return {"success": False, "error": "unsupported payload"}
```

## Recommended first real-runtime experiment

1. Use the laptop as the MLX source host.
2. Use the disposable Runpod GPU pod as the Linux target host.
3. Keep the current transport and manifest capture flow unchanged.
4. Wire `PERMEANT_MLX_CACHE_PROVIDER` into a real MLX inference process.
5. Start with staged vLLM block files on the target.
6. Add `PERMEANT_VLLM_RUNTIME_HOOK` only after the staged files look correct.
7. Re-run the cross-host migration and compare:
   - manifest timings
   - extracted layer count
   - staged block count
   - continuation success or failure reason

## Exit criteria for the milestone

We should call the next milestone successful when all of these are true:
- MLX cache extraction is live, not fixture-backed.
- Target receives and stages all hashes from a real run.
- Target runtime accepts the staged tensors through a runtime-specific hook or plugin.
- The migrated session produces a continuation from the target runtime.
- Repo docs capture the benchmark, failure modes, and cleanup steps.

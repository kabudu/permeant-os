# Target import worker

The successful June 14, 2026 live-source run proved that PermeantOS can:
- extract from a live MLX source runtime
- transfer cross-host successfully
- stage and acknowledge target-side payloads on a real GPU host

The next practical step is to have a local worker on the target consume those staged payloads and hand them to the real runtime.

This repo now includes:
- `adapters/vllm_directory_consumer.py`
  - writes staged payloads and `.ready.json` descriptors
- `adapters/vllm_import_worker.py`
  - watches the import directory
  - loads each ready descriptor and full payload
  - calls a runtime hook
  - writes a `.processed.json` marker with the result
- `adapters/vllm_real_runtime_consumer.py`
  - calls `adapters/vllm_live_runtime_registry.py:runtime_hook`
  - defaults the runtime state/probe files
  - is the direct path for in-process live target-runtime registration

## Why this matters

This separates the target-side problem into two stable layers:

1. PermeantOS staging:
   - receive block payload
   - acknowledge transfer
   - write a deterministic spool artifact

2. Runtime integration:
   - watch for new staged payloads
   - register them into the target runtime
   - write success/failure markers

That is much easier to debug than trying to mix network receive, daemon orchestration, and private runtime memory mutation in one place.

## Example usage

Start the receiver as before:

```bash
export PERMEANT_VLLM_CONSUMER_HOOK="/ABS/PATH/adapters/vllm_real_runtime_consumer.py:consume"
export PERMEANT_VLLM_RUNTIME_TARGET="/ABS/PATH/adapters/vllm_real_runtime_target.py:get_runtime"
export PERMEANT_VLLM_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
export VLLM_ENABLE_V1_MULTIPROCESSING=0
export PERMEANT_VLLM_CONTINUATION_PROMPT="PermeantOS continuation probe"
python /ABS/PATH/adapters/vllm_runtime_receiver.py \
  --host 127.0.0.1 \
  --port 29100 \
  --state-dir /tmp/permeant-vllm-state
```

With this direct real-runtime path:
- `inject_block` still stages `<hash>.json`
- successful injects still record `acked.json`
- `verify_continuation` now also calls the live runtime hook
- successful verification can emit a continuation probe into `/tmp/permeant-vllm-runtime-probe.json`

Then start the import worker:

```bash
python /ABS/PATH/adapters/vllm_import_worker.py \
  --import-dir /tmp/permeant-vllm-import \
  --hook /ABS/PATH/adapters/my_vllm_consumer.py:consume
```

One-shot processing mode for debugging:

```bash
python /ABS/PATH/adapters/vllm_import_worker.py \
  --import-dir /tmp/permeant-vllm-import \
  --hook /ABS/PATH/adapters/my_vllm_consumer.py:consume \
  --once
```

## Artifacts

For each staged block hash:
- `<hash>.json`: full staged payload
- `<hash>.ready.json`: summary descriptor written by the directory consumer
- `<hash>.ready.processed.json`: worker result marker

## Recommended next milestone

Use `my_vllm_consumer.py` as the hook for the import worker and implement:
- target runtime discovery
- block registration
- continuation verification against the real runtime

For the current in-process live-runtime path, prefer:
- `PERMEANT_VLLM_CONSUMER_HOOK=/ABS/PATH/adapters/vllm_real_runtime_consumer.py:consume`
- `PERMEANT_VLLM_RUNTIME_TARGET=/ABS/PATH/adapters/vllm_real_runtime_target.py:get_runtime`
- `VLLM_ENABLE_V1_MULTIPROCESSING=0`

That removes the extra import-worker loop and gives the receiver a direct route to:
- runtime registration
- runtime-backed verification
- first continuation probe capture

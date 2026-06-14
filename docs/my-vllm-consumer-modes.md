# `my_vllm_consumer.py` modes

`adapters/my_vllm_consumer.py` is no longer just a stub.

It now supports three practical modes:

## 1. `dry_run`

```bash
export PERMEANT_VLLM_CONSUMER_MODE=dry_run
```

Use this to verify the import worker path without needing a live target runtime.

## 2. `http`

```bash
export PERMEANT_VLLM_CONSUMER_MODE=http
export PERMEANT_VLLM_INGEST_URL=http://127.0.0.1:29200/ingest
export PERMEANT_VLLM_INGEST_TOKEN=replace-me
```

This mode forwards the full prepared block payload to a local HTTP endpoint owned by the target runtime process.

Expected response:

```json
{"success": true}
```

## 3. `command`

```bash
export PERMEANT_VLLM_CONSUMER_MODE=command
export PERMEANT_VLLM_INGEST_CMD="python /abs/path/to/runtime_ingest.py"
```

This mode sends the full prepared block payload to a local command on stdin.

Expected stdout response:

```json
{"success": true}
```

## Why these modes matter

They turn the target-side integration problem into one small contract:
- PermeantOS stages and shapes the payload
- the import worker detects it
- `my_vllm_consumer.py` hands it to the live target runtime

That means the only truly runtime-specific code you still need is the target process endpoint or command itself.

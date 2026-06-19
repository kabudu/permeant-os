# Runtime adapter protocol

This document defines the first real runtime integration surface for PermeantOS.

The current CLI and orchestrator stay unchanged. Instead, the extractor and injector crates can now switch from built-in mock behavior to command-backed adapters.

## Goal

Use real source and target runtimes without rewriting the migration CLI each time.

- Source side: implement a command that extracts canonical KV tensors from a live runtime.
- Target side: implement a command that injects migrated blocks into a live runtime and verifies continuation.

## Extractor backend

Enable it with:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD='python3 adapters/mlx_extractor.py'
```

For live runtime wiring without changing the script body, point the script at a hook implementation:

```bash
export PERMEANT_EXTRACTOR_HOOK='/absolute/path/to/mlx_hook.py:extractor_hook'
```

The extractor command receives a JSON request on `stdin`:

```json
{
  "seq_len": 8192,
  "n_layers": 4,
  "n_kv_heads": 2,
  "head_dim": 64
}
```

It also receives matching environment variables:

- `PERMEANT_SEQ_LEN`
- `PERMEANT_N_LAYERS`
- `PERMEANT_N_KV_HEADS`
- `PERMEANT_HEAD_DIM`

The extractor must write JSON to `stdout` in either of these forms:

```json
{
  "tensors": [
    {
      "name": "layer.0.key",
      "shape": [1, 2, 8192, 64],
      "data": [0.0, 0.1, 0.2]
    }
  ]
}
```

or:

```json
[
  {
    "name": "layer.0.key",
    "shape": [1, 2, 8192, 64],
    "data": [0.0, 0.1, 0.2]
  }
]
```

Required tensor names:

- `layer.<n>.key`
- `layer.<n>.value`

Canonical tensor shape expected by the current transpiler:

- `[1, n_kv_heads, seq_len, head_dim]`

Extractor responses may also include prompt-bound Agent Memory Graph span
metadata:

```json
{
  "tensors": [],
  "agent_graph_span_metadata": {
    "version": "0.1",
    "source_runtime": "mlx-live-runtime",
    "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
    "prompt": {
      "byte_hash": "sha256:...",
      "token_hash": "sha256:...",
      "token_count": 2016,
      "tokenizer_hash": "sha256:..."
    },
    "kv_spans": [
      {
        "node_id": "checkpoint:prompt",
        "token_start": 0,
        "token_end": 2016,
        "cache_ref": "kv:mlx-live:prefill",
        "tokenizer_hash": "sha256:...",
        "block_hashes": ["sha256:..."]
      }
    ],
    "binding": {
      "prompt_used_for_prefill": true,
      "same_prompt_required_on_target": true
    }
  }
}
```

The in-tree MLX live runtime attaches this metadata to the same prompt/token IDs
used to prefill the exported KV cache. The vLLM import worker validates the
sidecar before calling the target hook and records the validation result in its
processed marker. This is adapter-side evidence only; the daemon wire protocol
still carries tensor state as before.

When the staged target payload includes a target tokenizer view, the worker also
verifies that view against the graph span metadata before ingest. The accepted
forms are:

```json
{
  "target_prompt": {
    "text": "same prompt text used by the target",
    "token_ids": [1, 2, 3],
    "tokenizer_hash": "sha256:..."
  }
}
```

or the existing target-runtime fields:

```json
{
  "prompt": "same prompt text used by the target",
  "prompt_token_ids": [1, 2, 3],
  "prompt_tokenization": {
    "token_count": 3,
    "tokenizer_hash": "sha256:..."
  }
}
```

If any supplied target prompt hash, token count, token hash, or tokenizer hash
disagrees with `agent_graph_span_metadata`, the worker rejects the staged import
before the target hook runs.

## Injector backend

Enable it with:

```bash
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD='python3 adapters/vllm_injector.py'
```

For live runtime wiring without changing the script body, point the script at a hook implementation:

```bash
export PERMEANT_INJECTOR_HOOK='/absolute/path/to/vllm_hook.py:injector_hook'
```

The injector command receives JSON on `stdin`.

For block injection:

```json
{
  "action": "inject_block",
  "block_size": 256,
  "block_hash": "sha256:...",
  "tensors": [
    {
      "name": "layer.0.key",
      "shape": [1, 2, 64, 256],
      "data": [0.0, 0.1, 0.2]
    }
  ]
}
```

For continuation verification:

```json
{
  "action": "verify_continuation",
  "block_size": 256,
  "expected_hashes": [
    "sha256:..."
  ]
}
```

A successful command may return nothing, or:

```json
{
  "success": true
}
```

A failed command should return:

```json
{
  "success": false,
  "error": "reason"
}
```

If continuation verification fails because blocks are missing, it may return:

```json
{
  "success": false,
  "missing_hashes": ["sha256:..."]
}
```

## Why this matters

This is the first runtime-facing contract that lets us swap in real adapters for:

- `MLX` or another source runtime on the laptop side
- `vLLM`, `SGLang`, or another target runtime on the Linux GPU side

without changing the CLI transport or the migration envelope again.

## Immediate next adapter targets

1. `adapters/mlx_extractor.py`
2. `adapters/vllm_injector.py`
3. A small fixture runner that can feed saved tensors into both commands for repeatable offline debugging

## Included starter scripts

This repo now includes starter adapter entry points:

- `adapters/mlx_extractor.py`
- `adapters/vllm_injector.py`

Both scripts already speak the documented stdin/stdout JSON contract.

They support fixture-backed bring-up immediately:

- `PERMEANT_EXTRACTOR_FIXTURE=/path/to/extractor-response.json`
- `PERMEANT_INJECTOR_FIXTURE_STATE=/path/to/injector-state.json`

That lets us debug the adapter boundary before wiring in live MLX or live target-runtime calls.

## Graph span helper

`adapters/agent_graph_span_metadata.py` provides the shared helper for building
and validating prompt-bound graph span metadata. Source adapters should use
`build_prompt_span_metadata(...)` after prefill. Target-side workers should use
`validate_prompt_span_metadata(...)` with the target tokenizer view before
activating or forwarding migrated state.

## Fixture and hook bring-up

Two bring-up paths are supported immediately:

- Fixture replay for deterministic offline debugging
- Hook-based live integration for MLX or target-runtime specific code living outside the repo

Included offline test coverage lives in `tests/test_runtime_adapters.py`.


## Included harness and templates

The repo now also includes:

- `adapters/generate_mock_extractor_fixture.py`: generates canonical extractor fixtures matching the built-in mock tensor layout
- `adapters/run_fixture_roundtrip.py`: runs a full local migration using command-backed extractor and injector fixtures
- `adapters/mlx_hook_template.py`: starter live extractor hook module
- `adapters/vllm_hook_template.py`: starter live injector hook module

Example fixture-backed roundtrip:

```bash
python3 adapters/run_fixture_roundtrip.py --quant
```

Example live hook wiring:

```bash
export PERMEANT_EXTRACTOR_MODE=json_command
export PERMEANT_EXTRACTOR_CMD='python3 adapters/mlx_extractor.py'
export PERMEANT_EXTRACTOR_HOOK='/absolute/path/to/adapters/mlx_hook_template.py:extractor_hook'

export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD='python3 adapters/vllm_injector.py'
export PERMEANT_INJECTOR_HOOK='/absolute/path/to/adapters/vllm_hook_template.py:injector_hook'
```

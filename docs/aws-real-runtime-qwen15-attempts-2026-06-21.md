# AWS Qwen2.5 1.5B Raw-Transfer Attempts - 2026-06-21

This checkpoint investigated the larger same-family Qwen2.5 profile without
QATQ. The source and transport path were viable, but the AWS vLLM target did
not complete commit on the current `g4dn.xlarge`/T4 profile.

| Field | Value |
| --- | --- |
| Profile | `qwen2.5-1.5b-mlx-vllm` |
| Model | `Qwen/Qwen2.5-1.5B-Instruct` |
| Runtime path | local MLX to AWS vLLM |
| AWS instance | `g4dn.xlarge` |
| Transport | production `wss://`/mTLS |
| Transfer quantization | `none` |
| Migrated prefix | 1984 tokens |
| Target max context | 2048 tokens |
| Run IDs | `20260621-093155`, `20260621-095626` |
| Cleanup | verified at `2026-06-21T09:53:06Z` and `2026-06-21T10:17:38Z` |

## Source Probe

The local MLX source exported a raw Qwen2.5 1.5B cache with 56 tensors:
28 layers, each with key/value tensors shaped `[1984, 2, 128]`. The raw JSON
extractor payload was about 321 MB and the source continuation file recorded
16 generated tokens for the exact `Qwen/Qwen2.5-1.5B-Instruct` model.

The earlier 2016-token source probe exported cache data but produced zero
source continuation tokens, so the profile now uses a 1984-token migrated
prefix for evidence runs.

## AWS Result

Both AWS attempts reached the same target boundary:

- source cache extraction succeeded;
- capability exchange succeeded;
- encrypted USXF header verification succeeded;
- all raw layer/block payloads streamed to the target;
- the Agent Memory Graph package bound to the staged KV transaction;
- commit failed inside the target vLLM runtime before continuation, reverse
  export, target activity, or return-home proof could run.

The target daemon reported:

```text
Injector command failed: vllm_injector: runtime hook HTTP 500:
{"success": false, "error": "Check failed: (status == cudaSuccess) is false:
BatchPrefillWithPagedKVCache failed with error invalid argument"}
```

The second run attempted to force `VLLM_ATTENTION_BACKEND=TRITON_ATTN`, but
vLLM `0.23.0` logged it as an unknown environment variable and still selected
the FlashInfer attention backend on the Tesla T4 target.

## Conclusion

This is not a QATQ failure; QATQ was disabled for both runs. It is also not a
source extraction, production transport, or graph-binding failure. The current
evidence points at a target-runtime compatibility issue for Qwen2.5 1.5B's
head-dim-128 shape on the current vLLM `0.23.0`/T4 backend path.

PermeantOS should keep `qwen2.5-1.5b-mlx-vllm` marked as investigated but not
validated until the harness uses a supported vLLM backend control, a different
target runtime, or a GPU/backend combination that accepts this shape.

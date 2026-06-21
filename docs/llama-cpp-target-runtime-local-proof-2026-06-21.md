# llama.cpp Target Runtime Local Accepted-State Proof - 2026-06-21

This checkpoint records the first local llama.cpp adapter proof. It validates
the practical open-source runtime boundary at the accepted-state level, not at
the generated-token decode-fidelity level.

Update: `docs/llama-cpp-live-state-binding-proof-2026-06-21.md` now records the
first live llama.cpp state-file binding proof with exact continuation evidence.
This document remains the accepted-state baseline.

## Summary

| Field | Value |
| --- | --- |
| Adapter | `adapters/llamacpp_injector.py` |
| Target runtime | llama.cpp |
| Tooling found | `/opt/homebrew/bin/llama-cli`, `/opt/homebrew/bin/llama-server` |
| llama.cpp version | `8640 (7992aa7c8)` |
| Build | `AppleClang 17.0.0.17000604 for Darwin arm64` |
| Backend libraries reported | BLAS, Metal, Apple M4 CPU |
| Migrated state | one synthetic canonical layer key/value pair |
| Hash verification | passed for `sha256:local-llamacpp-proof` |
| Reverse export | passed |
| Reverse export proof hash | `sha256:9dba9b18cc3d1af4f253cc2599de0ff96d240b6ce857a32c29086a59d55eda43` |
| Decode claim | none |

## What Passed

- The adapter accepted canonical PermeantOS tensors named `layer.0.key` and
  `layer.0.value`.
- The adapter validated canonical `[seq, kv_heads, head_dim]` shape.
- The adapter recorded stable little-endian f32 SHA-256 fingerprints:
  - key: `sha256:7bbef1f0dc452643905807fa8e8940cf2f94cf95f32e839b4fbd7163927331ac`
  - value: `sha256:2e3d0ae3c30354784f52455e7dcb6f0ed769b3af43180c8e8bf16e79f5846d99`
- `verify_continuation` verified the migrated hash.
- `export_reverse_runtime_state` emitted target-runtime state with a proof hash.

## What Did Not Pass Yet

Generated-token continuation was not attempted. The installed llama.cpp
CLI/server expose useful runtime and KV cache controls, but they do not expose a
command-line API for importing externally migrated KV state into a live context.

The adapter therefore reports:

```text
decode_claim=none-without-live-kv-import-hook
```

To turn this into decode-continuation evidence, PermeantOS needs an out-of-tree
`PERMEANT_LLAMA_CPP_RUNTIME_HOOK` implementation that binds migrated KV state
into a live llama.cpp context and returns generated token evidence from that
bound context. The hook contract is now explicit:

- `bind_kv_state` must return `runtime_state_bound=true` plus a
  `binding_proof` containing `bound_hashes`, `context_id`, `kv_token_count`,
  and `proof_hash`;
- `verify_bound_continuation` must return generated `token_ids`,
  `used_migrated_kv=true`, and a binding proof that covers the expected block
  hash.

This should be built as a binding hook first, not an upstream patch. Upstreaming
can wait until the out-of-tree hook proves the API shape and PermeantOS has a
stronger public adoption case.

## Commands

```bash
export PERMEANT_LLAMA_CPP_RUNTIME_STATE_FILE=/tmp/permeant-llamacpp-proof/state.json
export PERMEANT_LLAMA_CPP_RUNTIME_PROBE_FILE=/tmp/permeant-llamacpp-proof/probe.json

python3 adapters/llamacpp_injector.py <<'JSON'
{"action":"inject_block","block_hash":"sha256:local-llamacpp-proof","tensors":[{"name":"layer.0.key","shape":[2,1,2],"data":[0.0,1.0,10.0,11.0]},{"name":"layer.0.value","shape":[2,1,2],"data":[100.0,101.0,110.0,111.0]}]}
JSON

python3 adapters/llamacpp_injector.py <<'JSON'
{"action":"verify_continuation","expected_hashes":["sha256:local-llamacpp-proof"]}
JSON

python3 adapters/llamacpp_injector.py <<'JSON'
{"action":"export_reverse_runtime_state"}
JSON
```

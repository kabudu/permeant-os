# PermeantOS Evidence Index

This index maps public PermeantOS claims to proof reports, repeatable commands, CI jobs, and known limitations.

Schema version: `permeantos-evidence-index-v0`

| Claim | Status | Runtime path | Evidence | Limitations |
| --- | --- | --- | --- | --- |
| Qwen2.5 MLX to AWS vLLM QATQ exact complex round trip | `validated-real-runtime` | mlx -> vllm | `docs/aws-real-runtime-qatq-exact-complex-2026-06-22.md`<br>`docs/qatq-permeantos-feedback-2026-06-22.md` | The current exact QATQ compatibility path is lossless but not size-reducing; the recorded run transferred about 6.7% more bytes than raw due to container overhead.<br>PermeantOS still needs to switch from the in-tree compatibility shim to the standalone QATQ crate once the QATQ API and lossless compression path are ready.<br>The vLLM adapter relies on runtime internals that may change between vLLM versions. |
| Qwen2.5 MLX full-KV standalone QATQ compression gate | `validated-local-compression` | mlx -> none | `docs/qatq-standalone-compression-gate-2026-06-22.md`<br>`docs/qatq-permeantos-feedback-2026-06-22.md` | This is a local standalone compression proof, not yet a live AWS migration proof using the standalone QATQ crate.<br>The live PermeantOS migration path still needs to replace the in-tree compatibility container with the pinned standalone QATQ crate.<br>The timing numbers were captured from a local debug build and should not be treated as final release-performance figures. |
| Qwen2.5 MLX to AWS vLLM long-horizon round trip | `validated-real-runtime` | mlx -> vllm | `docs/aws-real-runtime-long-horizon-2026-06-21.md`<br>`docs/aws-real-runtime-roundtrip-continuation-2026-06-20.md`<br>`docs/aws-real-runtime-production-transport-2026-06-20.md` | QATQ was lossy at sampled tensor slots; the validated claim is behavioral/decode fidelity, not numerical losslessness.<br>The vLLM adapter relies on runtime internals that may change between vLLM versions.<br>The 128-token horizon applies to the recorded model, runtime, transport, and hardware profile. |
| TinyLlama MLX to AWS vLLM raw-transfer structural E2E | `validated-structural-e2e` | mlx -> vllm | `docs/aws-real-runtime-tinyllama-2026-06-21.md` | Source-exact MLX/vLLM parity is not claimed for this profile because the recorded run diverged at a leading-space token boundary.<br>The validated decode claim is target-baseline/post-migration exactness at 16 tokens. |
| Qwen2.5 MLX to llama.cpp canonical KV feed | `validated-local-runtime` | mlx -> llama.cpp | `docs/llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md`<br>`docs/llama-cpp-raw-kv-internal-write-proof-2026-06-21.md`<br>`docs/llama-cpp-live-state-binding-proof-2026-06-21.md` | This is a local proof, not an AWS cloud migration proof.<br>The raw writer uses llama.cpp private headers matched to the recorded llama.cpp revision.<br>Broader llama.cpp claims still need longer-horizon and additional model-family validation. |
| Agent Memory Graph v0 schema and conformance | `validated-ci` | agent-memory-graph -> agent-memory-graph | `docs/agent-memory-graph.md`<br>`docs/agent-framework-adapters.md`<br>`docs/agent-memory-graph-threat-model.md` | The graph schema is versioned as v0 and remains pre-1.0.<br>Runtime-specific adapters must still prove their own export/import and side-effect policies. |

## Regenerate

```bash
scripts/generate-evidence-index.py --json-out docs/evidence-index.json --markdown-out docs/evidence-index.md
```

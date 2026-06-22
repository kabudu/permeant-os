# PermeantOS White Paper

## Live migration for AI agent state

PermeantOS is an early open-source platform for live AI agent migration. It introduces a state-fluid hypervisor and the Unified State Exchange Format (USXF), a runtime-neutral format for moving active AI state across heterogeneous model runtimes.

Today, PermeantOS provides validated live KV-cache migration paths, Agent Memory Graph binding, production transport foundations, runtime adapter scaffolding, repeatable evidence tooling, a public documentation hub, a generated claim-to-evidence index, checksummed release artifact packaging, package and SDK publication-readiness gates, scheduled/manual evidence jobs, and versioned adapter conformance reporting. The current platform-maturity work focuses on the remaining steps toward a durable open-source release line: broader runtime adapters, longer horizons, compatibility evidence, signed release assets, and contributor-ready runtime contracts.

## Why this matters

Long-running AI agents accumulate context. That context is expensive to reconstruct. If an agent has to move from a laptop to a cloud GPU, from one cloud host to another, or away from a node scheduled for shutdown, the usual approach is to replay or re-prefill the prompt. For long contexts, that can be slow and expensive.

PermeantOS treats agent state as portable infrastructure. Instead of binding state to one machine or runtime, it provides a migration layer that can extract, transfer, verify, and attach live KV cache state on a target runtime.

## What has been demonstrated

PermeantOS has demonstrated that agents can move on validated real-runtime paths. The strongest path migrates a complex Agent Memory Graph package and live KV cache from a local Apple Silicon MLX source runtime to an AWS NVIDIA vLLM target runtime over the production `wss://`/mTLS transport. The target accepts the imported state, continues decoding, resumes graph work, writes new evidence, exports the advanced decode boundary through a reverse runtime API, and returns graph/artifact proof to the origin. MLX then imports the target-advanced boundary and the origin continues from the returned evidence.

Latest long-horizon AWS run:

| Field | Value |
| --- | --- |
| Source | MLX on Apple Silicon |
| Target | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 1920 tokens |
| Transport | production `wss://`/mTLS byte proxy |
| Transfer mode | experimental `qatq` for this historical long-horizon run |
| Agent Memory Graph | 27 nodes, 25 edges, 4 packaged artifacts, bound, aligned, resumed on target, and returned to origin |
| Layers | 24 |
| Hash validation | passed |
| Slot-probe max key diff | `0.006696999999999065` |
| Slot-probe max value diff | `0.000558149999999813` |
| Prefix-cache seeded blocks | 16 |
| Decode fidelity | exact source/post-migration and baseline/post-migration matches at 16, 32, 64, and 128 generated tokens |
| Reverse runtime import | vLLM exported target decode boundary; MLX imported 2048-token target-advanced state and emitted proof hash `sha256:d26fa884e009131be2a0b0ba9e8d0a55ec4d48c2061a5e2579c62c3f7166ff44` |
| Agent activity | AWS target resumed pending graph work, executed approved tool activity, wrote a new artifact, and emitted a proof hash |
| Return-home activity | origin verified the AWS graph/report/artifact and wrote a new continuation artifact from the returned state |

The run proves the core path for the validated configuration: live MLX extraction, secure transport, graph/KV transaction binding, target-side vLLM KV allocation, direct KV write, prefix-cache attachment, artifact hash preservation, memory/retrieval evidence preservation, pending tool policy preservation, post-migration runtime continuation fidelity, reverse runtime export/import, and target-side graph activity resume. After migration, the AWS target exported its target-generated decode boundary through `/export_reverse_runtime_state` with proof hash `sha256:5c189979b52e35b9d3c434b6dc9dec1a075972137242fd94f171b7a096cec302`. The origin MLX runtime imported that boundary, materialized MLX-native KV state for the 2048-token target-advanced prompt, and emitted proof hash `sha256:d26fa884e009131be2a0b0ba9e8d0a55ec4d48c2061a5e2579c62c3f7166ff44`. The AWS target also imported the same complex Agent Memory Graph package, resumed retry-safe pending work, executed an explicitly approved publish write, wrote `reports/publish/announcement.md`, appended new graph evidence, and emitted proof hash `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c`.

The follow-up round-trip run returned the AWS-updated graph/report/artifact evidence to the origin. The origin verified the target proof hash, target graph hash, and target artifact bytes, then wrote `reports/roundtrip/origin-continuation.md` from the returned state. The origin-side round-trip proof hash is `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d`, with final origin graph hash `sha256:35d2b4c784a1243604140b2d017343140fefb8ed3b2722952c8d05a99ba732f8`.

This is a full validated round trip for the current runtime contract. The reverse path exports a canonical target decode boundary rather than copying vLLM GPU blocks byte-for-byte into MLX, because the runtimes use different physical KV layouts. MLX imports the target-generated boundary and materializes MLX-native KV state before continuing.

The long-horizon QATQ run transferred 6,294,528 bytes from a 47,185,920-byte uncompressed KV payload, a compression ratio of `0.1333984375`. QATQ is lossy at the tensor-slot level in this run, so the production PermeantOS claim does not depend on QATQ being lossless. The claim is bounded sampled numeric drift plus exact observed source/post-migration and baseline/post-migration continuations for the configured 128-token horizon. QATQ is being matured separately before it is folded back into PermeantOS as a production codec.

A matched FP8 transfer-quantized run used the same source, target, model,
prefix length, continuation horizon, and Agent Memory Graph manifest. It
reduced transferred bytes from 50,331,648 to 12,582,912 while preserving exact
16-token source/post-migration continuation fidelity. The transfer phase
improved from 72.790 seconds to 63.020 seconds, while total migration time
improved only modestly because this cold-host validation path is dominated by
target runtime setup, commit, and attachment overhead.

Follow-up validation broadened the runtime and model story. A raw-transfer TinyLlama MLX-to-vLLM run proved the first non-Qwen structural migration path, with exact target-baseline/post-migration continuation, reverse import, target graph activity, origin return-home continuation, and verified cleanup. A local MLX-to-llama.cpp proof exported canonical f32 K/V tensors from a live MLX source, verified token/span alignment, wrote those tensors directly into llama.cpp's internal `llama_kv_cache` backend tensors, and matched the MLX source continuation token-for-token at the aligned decode boundary.

## Architecture

PermeantOS migration has eight main stages:

1. Capability exchange between source and target.
2. Warm-start decision comparing migration cost with re-prefill cost.
3. Source runtime KV extraction.
4. Layout normalization into USXF.
5. Signed, encrypted, negotiated transport, preferring private `wss://`/mTLS with explicit fallbacks.
6. CRC-checked compact binary streaming to the target daemon.
7. Target KV allocation, reshape, write, and prefix-cache attachment.
8. Two-phase commit and validation.

USXF is the exchange layer. It records model identity, attention structure, sequence length, tensor dtype, transfer quantization, block hashes, checksums, and signatures.

## The key finding

An earlier validation run appeared to show a source/target continuation mismatch. The root cause was not a KV migration defect. The target context window was exhausted before the full validation continuation could be generated. Reducing the migrated prefix to leave enough target context room first produced exact 16-token source/post-migration fidelity, and the follow-up long-horizon run used a 1920-token prefix to prove exact 128-token source/post-migration and baseline/post-migration fidelity.

This matters because migration fidelity tests must account for tokenizer and runtime-specific context-window behavior. PermeantOS now records enough fidelity metadata to distinguish true migration defects from context exhaustion.

## Roadmap: Agent Memory Graph migration

KV cache migration is the first layer. Full agent migration requires more.

The Agent Memory Graph v0 schema now defines:

- conversation turns;
- tool calls and tool results;
- files and generated artifacts;
- retrieval memories and vector-store bindings;
- pending actions and idempotency policy;
- provenance and signatures;
- token-span mappings from graph nodes to KV cache ranges.

The current Agent Memory Graph work includes a local export/import harness,
complex-agent package generation, graph hash metadata in migration manifests,
analyzer alignment reporting, graph-to-KV span metadata, AWS real-runtime
validation with minimal and complex graph packages, target-side graph resume
proof, reverse runtime import proof, and origin return-home proof. The goal is
to migrate not just model activations, but agent continuity.

## Status

PermeantOS is a validated early platform. It is substantial enough to build on and reproduce, with explicit pre-1.0 limits around supported runtimes, compatibility, and publication.

Current strengths:

- Real complex-agent cross-runtime proof point.
- AWS target-side proof that agent activity continues after migration, including
  policy-governed pending tool work and new post-import graph evidence.
- Reverse vLLM-to-MLX runtime import proof through the live target export API
  and live origin MLX import endpoint.
- Origin return-home proof that verifies AWS-updated graph/artifact evidence
  and continues from the returned state.
- Rust core protocol and daemon.
- MLX and vLLM live runtime adapters.
- Reference PyTorch target adapter for independent migrated-state acceptance
  proofs.
- llama.cpp target adapter scaffolding, live state-file binding proof, raw
  internal KV write proof, and MLX-to-llama.cpp canonical KV feed proof.
- Agent Memory Graph v0 schema and specification.
- Local Agent Memory Graph export/import harness with complex-agent packages.
- Optional Agent Memory Graph hash metadata in migration manifests.
- Analyzer reporting for prompt, graph, and KV-cache alignment.
- Graph-to-KV span metadata in migration manifests and analyzer reports.
- Graph-attached AWS real-runtime validation for the current MLX-to-vLLM path.
- FP8 graph-attached AWS validation with a 4x smaller transferred payload and
  exact 16-token continuation fidelity.
- Raw-transfer TinyLlama MLX-to-vLLM structural E2E proof with reverse import,
  target graph activity, origin return-home continuation, and cleanup evidence.
- Complex-agent AWS validation with artifacts, memory, retrieval evidence,
  credential rebinding, pending tool policy, exact 16-token continuation
  fidelity, and verified cleanup.
- Historical experimental QATQ AWS validation with about 8x smaller transferred
  payload than raw f32, exact 128-token continuation fidelity on the validated
  long-horizon path, target-side Agent Memory Graph resume evidence, and
  origin return-home evidence. QATQ is being matured in its sibling project
  before it is folded back into PermeantOS as a production codec.
- Production transport foundation with signed session hello, compact binary
  frames, bounded payloads, CRC validation, stream IDs, replay rejection, and an
  explicit fallback ladder from private `wss://`/mTLS to QUIC/mTLS to framed
  TCP/mTLS.
- Generated public evidence index mapping validated claims to proof reports,
  repeatable commands, CI jobs, and known limitations.
- Documentation hub on `www.permeantos.org` covering installation, evidence,
  adapter authoring, release artifacts, and roadmap status.
- Checksummed release artifact builder and GitHub Actions artifact workflow for
  pre-publication binary bundles.
- Package and SDK publication-readiness gate covering Rust crate metadata,
  Python SDK metadata, README coverage, and packaging policy before any real
  registry publication.
- Scheduled/manual evidence jobs with a non-provisioning default lane and a
  hard-confirmed AWS real-runtime lane for future self-hosted evidence runners.
- Versioned adapter conformance report covering command-backed runtime adapter
  tests, framework adapter manifests, compatibility matrices, and graph
  export/import fixtures.
- Graph-attached live KV migration planning notes and acceptance criteria.
- Repeatable AWS E2E runner with cleanup verification.
- Conservative AWS prewarm recipe for reducing E2E bootstrap time without
  always-on infrastructure.
- Paper and roadmap.

Current limitations:

- Fidelity has been validated for specific model/runtime paths, including the
  128-token Qwen2.5 MLX-to-vLLM AWS path, a raw-transfer TinyLlama MLX-to-vLLM
  structural path, and a local MLX-to-llama.cpp canonical KV feed proof.
- vLLM integration relies on internal runtime behavior that may change.
- Python adapters are needed for Python-native ML runtimes.
- Runtime coverage is still intentionally bounded. Broader cloud matrices,
  signed GitHub Releases, binary distribution policy, production package
  publication, and longer-horizon quantized-transfer fidelity evaluation remain
  planned.

## Learn more

- Repository: [github.com/kabudu/permeant-os](https://github.com/kabudu/permeant-os)
- Documentation hub: [www.permeantos.org/docs](https://www.permeantos.org/docs/)
- Roadmap: [ROADMAP.md](https://github.com/kabudu/permeant-os/blob/master/ROADMAP.md)
- Evidence index: [docs/evidence-index.md](https://github.com/kabudu/permeant-os/blob/master/docs/evidence-index.md)
- Release artifacts: [docs/release-artifacts.md](https://github.com/kabudu/permeant-os/blob/master/docs/release-artifacts.md)
- Agent Memory Graph schema: [docs/agent-memory-graph.md](https://github.com/kabudu/permeant-os/blob/master/docs/agent-memory-graph.md)
- Model/runtime validation matrix: [docs/model-runtime-validation-matrix.md](https://github.com/kabudu/permeant-os/blob/master/docs/model-runtime-validation-matrix.md)
- llama.cpp canonical KV proof: [docs/llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md](https://github.com/kabudu/permeant-os/blob/master/docs/llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md)
- AWS long-horizon proof: [docs/aws-real-runtime-long-horizon-2026-06-21.md](https://github.com/kabudu/permeant-os/blob/master/docs/aws-real-runtime-long-horizon-2026-06-21.md)
- AWS E2E runbook: [docs/aws-real-runtime-e2e-runner.md](https://github.com/kabudu/permeant-os/blob/master/docs/aws-real-runtime-e2e-runner.md)

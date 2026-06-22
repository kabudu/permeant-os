<p align="center">
  <img src="docs/assets/permeant-logo-transparent.png" alt="PermeantOS logo" width="440" />
</p>

# PermeantOS

PermeantOS is an early open-source platform for live AI agent migration. It provides a state-fluid hypervisor, USXF exchange format, runtime adapters, validation harnesses, and evidence tooling for moving active agent state across heterogeneous inference runtimes.

PermeantOS has demonstrated that agents can move for validated real-runtime paths. In the latest long-horizon run, PermeantOS migrated a `Qwen/Qwen2.5-0.5B-Instruct` KV cache from local Apple Silicon MLX to an AWS NVIDIA vLLM target, bound a 27-node Agent Memory Graph package into the same transaction, wrote matching KV blocks into vLLM, seeded vLLM prefix-cache metadata, preserved four content-addressed artifacts, matched source and target-baseline continuations exactly through a 128-token validation horizon, resumed work on AWS, exported the vLLM decode boundary through a reverse runtime API, imported that target-advanced runtime state back into MLX, continued at the origin, then returned the AWS-updated graph/artifact evidence to the origin and continued from that proof as well. Follow-up validation added raw-transfer TinyLlama MLX-to-vLLM evidence and a local MLX-to-llama.cpp canonical KV feed proof.

## Status

Validated early platform. PermeantOS has moved beyond the initial validation threshold: it has repeatable real-runtime evidence, public schemas, CI, transport foundations, adapter scaffolding, and documented proof reports. It is still pre-1.0 infrastructure, so compatibility guarantees are scoped and runtime support is limited to validated paths.

What works today:

- Rust daemon/client migration protocol.
- Capability exchange and two-phase commit.
- Encrypted and signed transfer envelope.
- CRC-checked streaming payloads.
- Manifest generation and benchmark capture.
- MLX live source adapter.
- vLLM live target adapter with target block allocation, KV writes, prefix-cache seeding, and fidelity probes.
- Reference PyTorch target adapter for independent migrated-state acceptance
  proofs, with optional torch-backed tensors and dependency-light list-backed
  CI mode.
- llama.cpp target adapter scaffolding for accepted-state proofs, installed
  tool capability probes, and a live state-file binding hook that proves exact
  continuation after importing llama.cpp runtime state into a fresh context.
- llama.cpp raw internal KV write proof showing canonical f32 K/V tensors can
  be written directly into `llama_kv_cache` backend tensors, with corruption
  changing decode and canonical restore returning exact continuation.
- Cross-runtime MLX-to-llama.cpp canonical KV feed proof: live MLX exports
  canonical f32 K/V tensors and prompt-span metadata, llama.cpp verifies
  tokenization alignment, writes the external tensors directly into
  `llama_kv_cache`, and matches the MLX source continuation at the aligned
  decode boundary.
- Repeatable AWS real-runtime E2E runner with cleanup verification.
- Conservative AWS prewarm image/container recipe for faster E2E bootstrap without always-on infrastructure.
- Structured benchmark manifest summaries for paper/update tables and failure records.
- Multi-horizon decode-fidelity analysis over captured source, baseline, and post-migration continuations.
- Larger-context benchmark matrix planning with checked vLLM context-window requirements.
- Exact 128-token graph-attached MLX-to-vLLM continuation fidelity for the
  validated Qwen long-horizon AWS run.
- Raw-transfer TinyLlama MLX-to-vLLM structural E2E proof with exact
  target-baseline/post-migration continuation at 16 tokens, all 22 layer slot
  probes matching, reverse import, target graph activity, and origin
  return-home continuation.
- Round-trip Agent Memory Graph continuity proof: origin to AWS, target-side
  work, AWS-updated graph/artifact evidence returned to origin, and origin-side
  continuation from that returned state.
- Reverse vLLM-to-MLX runtime-state import proof: the AWS target exports its
  post-migration decode boundary through `/export_reverse_runtime_state`, the
  origin MLX exporter imports that target-generated boundary, materializes an
  MLX KV cache at the advanced prompt, and emits a new origin continuation.
- Agent Memory Graph v0 schema and specification for portable conversation, tool, artifact, memory, checkpoint, provenance, and KV-span state.
- Local Agent Memory Graph export/import harness with deterministic prompt reconstruction, complex-agent package generation, content-addressed artifact packaging, artifact hash verification, and restored-workspace validation.
- Local artifact migration safety policies for redacted/excluded artifacts, explicit external rebind requirements, and streaming artifact verification/restoration.
- Local tool-call replay safety audit for completed side effects, retry-safe read-only pending work, manual resume policies, and unsafe replay rejection.
- Local vector/retrieval memory snapshot validation and external vector-store rebind reporting.
- Agent Memory Graph adapter conformance layer with LangGraph-style durable-state and MCP-backed tool/resource session mappings.
- Local Agent Memory Graph security policy gate with signed-root attestation, provenance chain checks, secret rejection, credential rebinding, and target/tool/artifact allowlists.
- Optional Agent Memory Graph hash metadata in migration manifests.
- Complex graph-attached AWS real-runtime E2E proof for the current MLX-to-vLLM path.
- Production transport foundation in the Rust transport crate: signed session
  hello, `wss://`/mTLS-oriented profile metadata, compact binary frames,
  bounded payload sizes, CRC validation, stream IDs, and replay rejection.
  Transport negotiation uses an explicit fallback ladder from private
  `wss://`/mTLS to QUIC/mTLS to framed TCP/mTLS, while rejecting insecure
  downgrades. The AWS real-runtime runner now defaults to production
  `wss://`/mTLS transport, with SSH tunneling retained as an explicit fallback
  mode.

What is still experimental:

- Runtime adapters rely on Python because MLX and vLLM expose the needed internals through Python APIs.
- The vLLM attachment path uses implementation details that may change between vLLM versions.
- Long-horizon fidelity has been validated for Qwen2.5 at a 128-token
  continuation horizon, including graph-attached AWS runs and one complex-agent
  graph package. TinyLlama now has raw-transfer structural E2E evidence on the
  same runtime pair, with a documented source/target decode-format mismatch at
  token 0.
- Reverse runtime-state import is validated for the current vLLM-to-MLX path by
  canonical decode-boundary export and MLX cache materialization. Byte-for-byte
  copying of vLLM GPU cache blocks into MLX is not a meaningful cross-runtime
  contract because their physical KV layouts differ.
- Cloud validation is expensive and slow on cold hosts unless a prewarmed image is used.
- Longer-horizon Qwen2.5 MLX-to-vLLM validation is exact through 128 tokens;
  TinyLlama structural validation broadens the model-family evidence, and
  Qwen2.5 now has a local MLX-to-llama.cpp canonical KV feed proof through the
  private-header raw writer. New cloud batches are still needed for broader
  runtime-pair claims and source-exact cross-runtime parity.
- Adaptive transfer codec planning exists for raw, FP8, TurboQuant-style, and
  Quaternion-Augmented TurboQuant candidate modes. Raw and FP8 remain in-tree
  PermeantOS paths; QATQ is represented by a minimal compatibility crate until
  the sibling QATQ project is mature enough to fold back in as a real crate.

## Repository layout

- `crates/`: Rust crates for USXF core logic, transport, orchestration, injector, extractor, and CLI.
- `adapters/`: Python runtime adapters and bridge tools for MLX, vLLM, Runpod, and analysis.
- `docs/`: runbooks, design notes, validation reports, and paper draft.
- `examples/agent-memory-graph/`: local Agent Memory Graph export/import harness and framework adapter conformance mappings.
- `sdk/python/`: early Python SDK package.
- `scripts/`: repeatable cloud validation scripts.
- `ROADMAP.md`: detailed roadmap toward full agent memory graph migration.

## Key documents

- `docs/index.md`: task-oriented documentation hub for installation, evidence,
  adapter authoring, release artifacts, graph state, transport, and validation.
- `ROADMAP.md`: full roadmap, including Agent Memory Graph migration phases.
- `docs/agent-memory-graph.md`: Agent Memory Graph v0 schema specification.
- `docs/versioning-policy.md`: USXF, Agent Memory Graph, report schema, and
  lightweight release versioning policy.
- `docs/release-artifacts.md`: checksummed binary bundle, release manifest, and
  GitHub Actions artifact workflow for pre-publication release packaging.
- `docs/crate-and-sdk-publication-plan.md`: Rust crate and Python SDK
  publication-readiness gate, publish-disabled boundary, and future registry
  release checklist.
- `docs/agent-memory-graph-threat-model.md`: local graph import threat model and Phase 8 security controls.
- `docs/production-transport.md`: production transport foundation, security
  invariants, binary framing, and deployment cutover plan.
- `docs/schemas/agent-memory-graph-v0.schema.json`: machine-readable JSON Schema for the graph envelope.
- `docs/agent-framework-adapters.md`: Agent Memory Graph adapter capability manifest, compatibility matrix, and conformance rules.
- `docs/usxf-arxiv-paper.md`: paper draft covering USXF, PermeantOS, and real-runtime E2E findings.
- `docs/e2e-validation-checkpoint-2026-06-20.md`: fresh local and AWS
  real-runtime E2E checkpoint evidence.
- `paper/arxiv/`: arXiv-oriented LaTeX submission bundle.
- `docs/website/white-paper.md`: website-friendly technical white paper.
- `docs/deployment-and-testing-guide.md`: local, cloud-host, manifest, benchmark, and Runpod workflow guide.
- `docs/benchmark-summary-tooling.md`: structured manifest summary and paper-table tooling.
- `docs/fidelity-horizon-suite.md`: multi-horizon decode-fidelity comparison tooling.
- `docs/context-benchmark-matrix.md`: larger-than-2k context benchmark planning.
- `docs/llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md`: local
  MLX-to-llama.cpp raw canonical KV feed proof.
- `docs/model-runtime-validation-matrix.md`: planned and validated
  model-family/runtime profiles and evidence rules for broadening real-runtime
  claims.
- `docs/evidence-index.md`: public claim-to-evidence index linking validated
  runtime/model paths to proof reports, commands, CI jobs, and known
  limitations.
- `scripts/run-evidence-job.py`: scheduled/manual evidence job runner for
  non-provisioning evidence reports and guarded AWS real-runtime validation.
- `scripts/run-adapter-conformance.py`: runtime/framework adapter conformance
  report for scheduled evidence jobs and contributor validation.
- `docs/aws-real-runtime-long-horizon-2026-06-21.md`: AWS long-horizon
  Qwen2.5 MLX-to-vLLM proof with exact 128-token fidelity, QATQ metrics,
  reverse import, target activity, return-home continuation, and cleanup
  verification.
- `docs/aws-real-runtime-tinyllama-2026-06-21.md`: AWS TinyLlama
  MLX-to-vLLM raw-transfer proof with exact target baseline/post-migration
  continuation, reverse import, Agent Memory Graph activity, origin
  return-home, and cleanup evidence.
- `docs/aws-real-runtime-qwen15-attempts-2026-06-21.md`: investigated
  Qwen2.5 1.5B raw-transfer AWS attempts and the current vLLM/T4 backend
  blocker.
- `docs/transfer-quantization-comparison.md`: paired raw-vs-quantized manifest comparison tooling.
- `docs/aws-real-runtime-transfer-quantization-2026-06-20.md`: raw-vs-FP8 AWS
  real-runtime comparison for the graph-attached MLX-to-vLLM validation path.
- `docs/aws-real-runtime-complex-agent-2026-06-20.md`: complex Agent Memory
  Graph package validation for the graph-attached MLX-to-vLLM path.
- `docs/aws-real-runtime-qatq-2026-06-20.md`: experimental
  Quaternion-Augmented TurboQuant AWS real-runtime validation.
- `docs/agent-activity-continuation-proof-2026-06-20.md`: deterministic
  Agent Memory Graph resume proof showing post-import tool activity and new
  graph evidence.
- `docs/aws-real-runtime-agent-activity-continuation-2026-06-20.md`: AWS
  target-side proof that QATQ migration fidelity and Agent Memory Graph
  post-import tool activity both continue on the real target.
- `docs/aws-real-runtime-roundtrip-continuation-2026-06-20.md`: AWS
  round-trip proof that the target-updated graph/artifact evidence returns to
  the origin and origin-side work continues from that remote proof.
- `docs/aws-real-runtime-production-transport-2026-06-20.md`: AWS
  real-runtime proof that the default production `wss://`/mTLS transport works
  for the current MLX-to-vLLM QATQ round-trip path.
- `docs/adaptive-transfer-codecs.md`: adaptive transfer codec planning, semantics, and fallback behavior.
- `docs/aws-real-runtime-e2e-runner.md`: repeatable AWS real-runtime E2E runner and cleanup/resume runbook.
- `docs/aws-prewarm-image.md`: conservative AWS image/container prewarm recipe and cost guardrails.
- `docs/graph-attached-kv-migration-plan.md`: Phase 3 graph-attached live KV migration plan and acceptance criteria.
- `docs/runtime-adapter-protocol.md`: command-backed extractor/injector contract.
- `docs/pytorch-target-runtime-adapter.md`: reference PyTorch target adapter
  runbook and evidence criteria.
- `docs/llama-cpp-target-runtime-adapter.md`: llama.cpp target adapter runbook,
  capability probe, and live state-binding hook boundary.
- `docs/llama-cpp-target-runtime-local-proof-2026-06-21.md`: local llama.cpp
  accepted-state proof and decode-continuation boundary.
- `docs/llama-cpp-live-state-binding-proof-2026-06-21.md`: live libllama
  state-file binding proof with exact continuation and reverse export hashes.
- `docs/llama-cpp-raw-kv-internal-write-proof-2026-06-21.md`: raw internal
  llama.cpp KV tensor write proof using matching private headers.
- `docs/real-runtime-bringup.md`: live runtime bring-up notes.
- `docs/aws-real-runtime-fidelity-followup-2026-06-16.md`: fidelity investigation history.

## Validated real-runtime result

Latest successful fidelity run:

| Field | Value |
| --- | --- |
| Run ID | `20260621-052744` |
| Manifest | `migration-20260621-053602-9938-manifest.json` |
| Source | local MLX on Apple Silicon |
| Target | AWS `g4dn.xlarge`, vLLM `0.23.0` |
| Model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Prefix length | 1920 tokens |
| Transport | production `wss://`/mTLS byte proxy on port `29443` |
| Transfer quantization | `qatq` |
| Agent Memory Graph | 27 nodes, 25 edges, 4 packaged artifacts, bound/aligned/resumed on target/returned to origin |
| Layers | 24 |
| Hash validation | passed |
| Slot probe max key diff | `0.006696999999999065` |
| Slot probe max value diff | `0.000558149999999813` |
| Prefix-cache seeded blocks | 16 |
| Decode fidelity | exact source/post-migration and baseline/post-migration matches at 16, 32, 64, and 128 generated tokens |
| Transfer bytes | `6,294,528` of `47,185,920` uncompressed bytes; compression ratio `0.1333984375` |
| Reverse runtime import | vLLM exported target decode boundary with proof hash `sha256:5c189979b52e35b9d3c434b6dc9dec1a075972137242fd94f171b7a096cec302`; MLX imported the 2048-token target-advanced boundary and emitted origin proof hash `sha256:d26fa884e009131be2a0b0ba9e8d0a55ec4d48c2061a5e2579c62c3f7166ff44` |
| Agent activity continuation | AWS target resumed pending work, wrote `reports/publish/announcement.md`, emitted proof hash `sha256:b066a1dba9ed250eb54e1344c8d0092d8ad2d90dfe68bbfc1a0c740d18b6969c` |
| Return-home continuation | origin verified the AWS graph/report/artifact, wrote `reports/roundtrip/origin-continuation.md`, emitted proof hash `sha256:052add6058521a13902515f759499b1350d5be4055d070d4e5428a9df0adb36d` |
| Cleanup | instance, security group, and key pair deleted; cleanup verified at `2026-06-21T05:48:33Z` |

The earlier apparent fidelity gap at a longer prefix was traced to target context-window exhaustion, not a KV migration defect.
Historical long-prefix compression runs used experimental QATQ transfer
compression. QATQ remains a promising codec path, but it is being matured as a
separate project before it is folded back into PermeantOS as production
compression. Current core fidelity claims are therefore based on raw/FP8
runtime-state paths, graph/KV/prompt alignment, bounded sampled deltas, and
exact observed continuation.

## Quick start

Prerequisites:

- Rust toolchain.
- Python 3.10+ for adapters.
- Optional: Apple Silicon with MLX for live source tests.
- Optional: AWS account with GPU quota for real vLLM target tests.

Build the Rust CLI:

```bash
cargo build
```

Run a local simulated migration target:

```bash
./target/debug/permeant-cli daemon --addr 127.0.0.1:9099
```

In another terminal, run a simulated migration:

```bash
./target/debug/permeant-cli sim-migrate --target-addr 127.0.0.1:9099 --seq-len 512
```

For real-runtime MLX-to-vLLM validation, start with:

```bash
scripts/aws-real-runtime-e2e.sh preflight
scripts/aws-real-runtime-e2e.sh run
```

Plan the next model-family/runtime proof commands:

```bash
scripts/plan-model-runtime-validations.py --format json
scripts/plan-model-runtime-validations.py \
  --profile gemma-2-2b-it-mlx-vllm \
  --format shell \
  --action preflight
```

Read `docs/aws-real-runtime-e2e-runner.md` first. The preflight command does
not provision infrastructure. The `run` command provisions billable AWS GPU
infrastructure and is designed to clean up after itself, but you should
understand the state file and cleanup command before running it. To reduce
cold-start setup time without leaving infrastructure running, see
`docs/aws-prewarm-image.md`.

Summarize migration manifests after a local or cloud batch:

```bash
scripts/summarize-benchmark-manifests.py benchmark-manifests/<run-label> \
  --markdown-out benchmark-manifests/<run-label>/summary.md
```

Analyze captured continuation fidelity across multiple token horizons:

```bash
scripts/analyze-fidelity-horizons.py \
  --source /tmp/permeant-source-continuation.json \
  --probe .permeant-e2e/aws/<run-id>/vllm-runtime-probe.json \
  --horizons 16,32,64 \
  --markdown-out .permeant-e2e/aws/<run-id>/fidelity-horizons.md
```

Plan larger-than-2k context benchmark points:

```bash
scripts/plan-context-benchmarks.py \
  --markdown-out benchmark-manifests/context-matrix.md \
  --env-out benchmark-manifests/context-matrix.env
```

Plan model-family/runtime validation points:

```bash
scripts/plan-model-runtime-validations.py --format shell --action preflight
```

Compare paired raw and transfer-quantized benchmark manifests:

```bash
scripts/compare-transfer-quantization.py benchmark-manifests/<run-label> \
  --markdown-out benchmark-manifests/<run-label>/transfer-quantization.md
```

Plan adaptive transfer codec experiments and fallbacks:

```bash
scripts/plan-transfer-codecs.py \
  --markdown-out benchmark-manifests/transfer-codec-plan.md
```

## Benchmark snapshot

The current long-horizon proof is intentionally scoped to Qwen2.5 on
MLX-to-vLLM. TinyLlama has now completed a raw-transfer structural E2E proof on
the same runtime pair. Additional model-family profiles are planned in
`docs/model-runtime-validation-matrix.md`; they should not be marked validated
until their real-runtime runs complete with cleanup evidence.

| Run | Target | Source mode | Transport | Seq len | Total time (ms) | Effective bandwidth (Gbps) | Manifest |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| AWS long-horizon WSS QATQ round trip | `g4dn.xlarge` | live MLX | production `wss://`/mTLS + QATQ complex graph-bound vLLM prefix-cache attachment + 128-token fidelity + target graph resume + vLLM reverse export API + MLX reverse import + origin return-home proof | 1920 | 431701.159583 | 0.0004952710276217939 | `migration-20260621-053602-9938-manifest.json` |
| AWS production WSS QATQ round trip | `g4dn.xlarge` | live MLX | production `wss://`/mTLS + QATQ complex graph-bound vLLM prefix-cache attachment + target graph resume + vLLM reverse export API + MLX reverse import + origin return-home proof | 2016 | 414148.584541 | 0.00048287964700385205 | `migration-20260620-225636-64284-manifest.json` |
| AWS QATQ reverse runtime round trip | `g4dn.xlarge` | live MLX | SSH tunnel + QATQ complex graph-bound vLLM prefix-cache attachment + target graph resume + vLLM reverse export API + MLX reverse import + origin return-home proof | 2016 | 389327.437458 | 0.0007638025225847906 | `migration-20260620-211207-46427-manifest.json` |
| AWS QATQ agent-activity continuation | `g4dn.xlarge` | live MLX | SSH tunnel + QATQ complex graph-bound vLLM prefix-cache attachment + target-side graph resume | 2016 | 389836.2535 | 0.0008036472740685385 | `migration-20260620-184608-67621-manifest.json` |
| AWS QATQ complex graph-attached fidelity | `g4dn.xlarge` | live MLX | SSH tunnel + QATQ complex graph-bound vLLM prefix-cache attachment | 2016 | 386467.57175 | 0.0008050778400958065 | `migration-20260620-173846-50882-manifest.json` |
| AWS complex graph-attached real-runtime fidelity | `g4dn.xlarge` | live MLX | SSH tunnel + complex graph-bound vLLM prefix-cache attachment | 2016 | 426187.141167 | 0.005626112414656161 | `migration-20260620-170130-37116-manifest.json` |
| AWS graph-attached FP8 fidelity | `g4dn.xlarge` | live MLX | SSH tunnel + FP8 graph-bound vLLM prefix-cache attachment | 2016 | 389689.972334 | 0.0015973124508454 | `migration-20260620-162809-25370-manifest.json` |
| AWS graph-attached real-runtime fidelity | `g4dn.xlarge` | live MLX | SSH tunnel + graph-bound vLLM prefix-cache attachment | 2016 | 396126.852875 | 0.005531747332504151 | `migration-20260620-153940-11152-manifest.json` |
| AWS real-runtime fidelity | `g4dn.xlarge` | live MLX | SSH tunnel + vLLM prefix-cache attachment | 2016 | see run doc | see run doc | `migration-20260616-231535-66524-manifest.json` |
| AWS GPU | `g4dn.xlarge` | live MLX | SSH tunnel to daemon | 2048 | 25245.342833 | 0.001438227963385703 | `migration-20260615-215310-60139-manifest.json` |
| AWS real runtime | `g4dn.xlarge` | live MLX | SSH tunnel + in-process vLLM hook | 2048 | 49105.921208 | 0.0016397366763484056 | `migration-20260615-232818-54818-manifest.json` |
| AWS CPU fallback | `t3.medium` | live MLX | SSH tunnel to daemon | 2048 | 23106.294833 | 0.0017053993142176205 | `migration-20260615-195032-6976-manifest.json` |
| Runpod live-source proof | RTX 3090 | live MLX | SSH tunnel to daemon | 2048 | 156377.4295 | 0.00011692589682723728 | `migration-20260614-154223-70658-manifest.json` |
| Runpod HTTP-bridge proof | RTX 3090 | live MLX | HTTP bridge | 2048 | 54649.212125 | 0.0016446839797195588 | `migration-20260614-195346-87816-manifest.json` |

## Agent Memory Graph Progress

The next major milestone is full Agent Memory Graph migration: conversation turns, tool calls, artifacts, vector memories, pending work, provenance, and KV spans in one transactional migration envelope.

Completed:

- Agent Memory Graph v0 schema and specification.
- Machine-readable JSON Schema with validation fixture and contract tests.
- Published schema identifier: `https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json`.
- Public versioning policy for USXF, Agent Memory Graph, report schemas, and
  lightweight roadmap releases.
- Local graph export/import harness with deterministic prompt reconstruction, complex-agent package generation, artifact hash verification, prompt token hash capture, and simulated KV hash validation.
- Optional graph hash, artifact hash, prompt hash, and simulated KV hash fields in migration manifests.
- Optional graph-to-KV span metadata in migration manifests when an Agent Memory Graph package is supplied.
- Content-addressed artifact packaging and restored-workspace verification in the local graph harness.
- Artifact redaction/exclusion policies, explicit external rebind validation, and streaming large-file artifact verification/restoration in the local graph harness.
- Tool-call replay safety audit in the local graph harness, including no-replay preservation for completed external writes, retry-safe read-only pending calls, manual resume requirements, and rejection of unsafe side-effect retries.
- Vector/retrieval memory support in the local graph harness, including deterministic vector snapshots, embedding/index compatibility checks, retrieval equivalence validation, and hosted vector-store rebind reporting.
- Agent framework adapter conformance for two independent runtime families: LangGraph-style durable state and MCP-backed tool/resource sessions.
- Security, provenance, and policy hardening in the local graph harness, including signed-root metadata, provenance-chain audit evidence, raw secret rejection, credential rebind enforcement, and target/tool/artifact allowlists.
- Adapter-side graph span metadata emitted by the MLX live runtime and validated against the vLLM target tokenizer view before target ingest.
- Daemon transaction binding for manifest-referenced graph packages, rejected before commit when required graph/KV evidence is incomplete or does not match the migrated KV header.
- Analyzer reporting for prompt, graph, graph/KV span, and KV alignment in fidelity summaries.
- Graph-attached live KV migration planning notes and acceptance criteria.
- Graph-attached real-runtime AWS validation for MLX-to-vLLM KV migration with aligned graph, prompt, and KV evidence.
- FP8 graph-attached AWS validation showing exact 16-token continuation
  fidelity with a 4x smaller transferred payload and expected lossy slot
  deltas.
- Complex-agent AWS validation showing a 27-node graph, 25 edges, four packaged
  artifacts, memory/retrieval state, completed and pending tool policies, one
  graph/KV span, exact 16-token continuation fidelity, and verified AWS
  cleanup.

Remaining:

- Full graph package byte streaming and durable target-side graph session storage.

See `ROADMAP.md` for the detailed phased plan.

## Contributing

Contributions are welcome, especially around:

- Runtime adapters.
- Manifest and analyzer tooling.
- Agent Memory Graph export/import and adapter implementations.
- Reproducible benchmarks.
- Security review.
- Documentation and examples.

Read `CONTRIBUTING.md` before opening a pull request.

## Security

PermeantOS handles sensitive context state. Do not publish real user context, secrets, cloud credentials, private model prompts, or generated migration manifests containing sensitive data.

Report vulnerabilities using the process in `SECURITY.md`.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.

Apache-2.0 is used because PermeantOS is infrastructure software where a permissive license plus an explicit patent grant is preferable for broad academic, startup, and commercial adoption.

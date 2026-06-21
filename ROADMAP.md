# PermeantOS Roadmap

PermeantOS currently proves live KV-cache migration across real heterogeneous runtimes: a local Apple Silicon MLX source can migrate a Qwen2.5 KV cache to an AWS NVIDIA vLLM target, seed the target prefix cache, and produce exact 128-token continuation fidelity for the validated long-horizon run. A raw-transfer TinyLlama run also proves the first non-Qwen structural MLX-to-vLLM migration path, including exact target baseline/post-migration continuation, reverse import, target graph activity, and origin return-home continuation.

This roadmap describes the next major expansion: full agent memory graph migration. The goal is to migrate not only KV cache tensors, but the structured continuity state of an agent: conversation state, tool calls, artifacts, retrieval memory, pending work, provenance, and the KV spans that make resumed decoding fast.

## Current baseline

Implemented and validated:

- Rust hypervisor daemon and migration client.
- Capability exchange and two-phase commit flow.
- Encrypted and signed transfer envelope.
- CRC-checked streaming payload frames.
- USXF-style tensor metadata and manifests.
- MLX source adapter for live KV extraction.
- vLLM target adapter for live KV allocation, direct slot writes, prefix-cache seeding, and continuation validation.
- Repeatable AWS real-runtime E2E runner with cleanup verification.
- Manifest and fidelity analysis tooling.
- Exact MLX-to-vLLM 128-token decode fidelity for
  `Qwen/Qwen2.5-0.5B-Instruct` at a 1920-token prefix.

Known limitations:

- Long-horizon fidelity has been validated for Qwen2.5 at a 128-token
  continuation horizon.
- TinyLlama has completed raw-transfer structural E2E validation on the
  MLX-to-vLLM path; source-exact cross-runtime decode parity remains explicitly
  unclaimed for that profile because MLX and vLLM differed at a leading-space
  token boundary.
- Broader model-family and runtime coverage now has a machine-checkable
  validation matrix, but additional profiles still need real cloud runs before
  they become evidence.
- Fresh cloud hosts are slow because vLLM, Torch, CUDA packages, model weights, and kernels are cold-installed or warmed during each run.
- Python adapters are still required for Python-native runtimes such as MLX and vLLM.
- KV cache migration is not yet packaged as a stable public runtime API.
- Full agent state, tools, files, vector stores, and pending side effects are not yet migrated as a graph.

## North star

A user should be able to pause or relocate an agent from one host/runtime to another and resume with equivalent continuity:

- Same conversation and instruction state.
- Same relevant long-context KV prefix when compatible.
- Same tool-call history and artifact references.
- Same durable memories and retrieval context.
- Same pending plan where safe to resume.
- Clear provenance for every migrated state component.
- No accidental replay of non-idempotent side effects.

## Phase 1: Agent Memory Graph v0 schema

Define a graph layer above KV cache.

Deliverables:

- `docs/agent-memory-graph.md` specification.
- JSON schema for graph export/import.
- Node types for messages, tool calls, tool results, plans, artifacts, memories, credentials references, and KV spans.
- Edge types for causal order, derives-from, references, produced, consumed, supersedes, and resumes.
- Stable IDs for graph nodes and edges.
- Graph-level checksum and per-node hashes.
- Version field, compatibility policy, and extension namespace rules.

Proposed minimal shape:

```json
{
  "graph_version": "0.1",
  "agent": {
    "id": "agent:example",
    "runtime": "local-loop",
    "model": "Qwen/Qwen2.5-0.5B-Instruct"
  },
  "nodes": [
    {"id": "turn:1", "type": "message", "role": "user", "content_hash": "sha256:..."},
    {"id": "tool:1", "type": "tool_call", "name": "aws.ec2.run_instances", "idempotency_key": "..."},
    {"id": "artifact:1", "type": "file", "path": "reports/result.json", "sha256": "..."}
  ],
  "edges": [
    {"from": "turn:1", "to": "tool:1", "type": "caused"},
    {"from": "tool:1", "to": "artifact:1", "type": "produced"}
  ],
  "kv_spans": [
    {"node_id": "turn:1", "token_start": 128, "token_end": 256, "cache_ref": "kv:prefix:0"}
  ]
}
```

Exit criteria:

- A graph can represent a simple chat/tool/artifact session.
- The graph can be hashed deterministically.
- A migrated KV prefix can be linked to graph token spans.

## Phase 2: Minimal local agent export/import harness

Create a small reference agent loop that is intentionally simple and fully inspectable.

Deliverables:

- Example local agent runtime under `examples/agent-memory-graph/`.
- Export command that emits graph JSON plus artifact blobs.
- Import command that reconstructs the agent state.
- Deterministic prompt reconstruction from graph nodes.
- Manifest that records graph hash, artifact hashes, prompt token hash, and KV hash.

Validation:

- Export an agent after several turns and one tool call.
- Import on the same machine.
- Reconstruct the prompt byte-for-byte or token-for-token.
- Continue the agent with the same next response under deterministic decoding.

Exit criteria:

- Graph-only migration works without live KV migration.
- Prompt reconstruction is deterministic.
- Artifacts referenced by the graph are present and hash-verified after import.

## Phase 3: KV-attached graph migration

Attach existing PermeantOS KV migration to the graph layer.

Deliverables:

- [x] Graph nodes include token spans and KV cache references in the local
  Agent Memory Graph package.
- [x] Migration manifest includes both tensor state and graph state.
- [x] Adapter-side MLX source metadata binds the live prefill prompt token
  range to graph/KV span evidence.
- [x] Adapter-side vLLM import worker validates graph span metadata before
  target hook ingest.
- [x] Import path verifies that graph token spans match the target tokenizer
  view when the vLLM staged target payload provides prompt/tokenizer evidence.
- [x] End-to-end daemon transaction binds the graph package and KV state as one
  commit unit.
- [x] Analyzer reports graph/KV alignment status.

Validation:

- Export graph and KV cache from the MLX source.
- Migrate both to vLLM target.
- Verify prompt reconstruction, KV hash validation, slot-probe equality, prefix-cache attachment, and continuation fidelity.

Exit criteria:

- A resumed target can explain which graph nodes map to the migrated KV prefix.
- Decode fidelity remains exact for the validation horizon.
- Analyzer can distinguish graph mismatch, tokenizer mismatch, KV mismatch, and context-window exhaustion.

## Phase 4: Artifact and filesystem migration

Move generated files and structured artifacts as first-class graph objects.

Deliverables:

- [x] Content-addressed artifact store for the local Agent Memory Graph package.
- [x] Path mapping policy for target workspaces in the local import path.
- [x] Redaction/exclusion rules.
- [x] Large-file streaming support.
- [x] Artifact restore report for restored local files.

Validation:

- [x] Agent creates files, references them in messages/tool outputs, migrates,
  and resumes with the same files available in a restored workspace.
- [x] Hash mismatch causes import failure for required local artifacts.
- [x] Unsafe restore paths are rejected before writing target files.

Exit criteria:

- [x] File artifacts are reproducibly restored by the local harness.
- [x] Local graph references fail import when required blobs are missing or
  invalid.
- [x] External artifacts are explicitly marked rebindable before graph
  references may remain unresolved.

## Phase 5: Tool-call replay and side-effect safety

Prevent duplicated external side effects during migration and resume.

Deliverables:

- [x] Tool-call node schema with idempotency keys.
- [x] Pending action states: `not_started`, `in_progress`, `completed`, `failed`, `cancelled`, `needs_user`.
- [x] Resume policies: `retry_safe`, `never_retry`, `ask_user`, `rebind`, `compensate`.
- [x] Tool result provenance and external resource IDs.
- [x] Side-effect audit log.

Validation:

- [x] A completed cloud provisioning tool call is not repeated after import.
- [x] A pending safe read-only tool call may retry.
- [x] A non-idempotent write action requires explicit policy before resume.

Exit criteria:

- [x] Migration can preserve pending work without duplicating destructive or billable actions.
- [x] Analyzer reports unsafe pending actions before commit.

## Phase 6: Vector and retrieval memory support

Support external and embedded memory stores.

Deliverables:

- [x] Memory node type for semantic memories and retrieval chunks.
- [x] Vector store binding metadata.
- [x] Snapshot mode for small/local vector stores.
- [x] Rebind mode for hosted vector stores.
- [x] Embedding model identity and index compatibility checks.

Validation:

- [x] Query results before and after migration are equivalent for a test corpus.
- [x] Missing external vector store credentials produce a clear rebind-required state.

Exit criteria:

- [x] Agent retrieval behavior is preserved or safely marked degraded.

## Phase 7: Runtime adapters for real agent frameworks

Add adapters for common agent systems while keeping the core protocol framework-neutral.

Candidate adapters:

- Minimal local reference loop.
- LangGraph-style durable state.
- OpenAI Agents SDK-style traces/state when suitable APIs are available.
- MCP-backed tool/resource sessions.
- Browser/session state where safe to represent as rebindable capability references.

Deliverables:

- [x] Adapter capability manifest.
- [x] Export/import conformance tests.
- [x] Compatibility matrix.

Exit criteria:

- [x] At least two independent agent runtimes can export/import the Agent Memory Graph v0 schema.

## Phase 8: Security, provenance, and policy

Harden graph migration for real users and shared infrastructure.

Deliverables:

- [x] Per-node signatures or signed graph roots.
- [x] Redaction policies for secrets and credentials.
- [x] Capability rebinding instead of raw credential copying.
- [x] Provenance chain across multi-hop migrations.
- [x] Policy hooks for allowed target runtimes, allowed tools, and allowed artifact paths.
- [x] Threat model document.

Validation:

- [x] Secret values are excluded or encrypted according to policy.
- [x] Tampered graph nodes are detected.
- [x] Target refuses incompatible or untrusted graph imports.

Exit criteria:

- [x] A graph migration can be audited after the fact.
- [x] Sensitive external capabilities are not silently copied to new machines.

## Phase 9: Performance and reliability hardening

Make repeated validation boring and affordable.

Deliverables:

- [x] Conservative prewarmed AWS AMI or container recipe with Rust toolchain,
  vLLM, and CUDA stack; model weights stay outside the image unless a later
  cost/latency calculation justifies baking them in.
- [x] Longer-horizon decode-fidelity benchmark suite for captured source,
  baseline, and post-migration continuations.
- [x] Larger context benchmark matrix planning and runner configuration beyond
  2k tokens.
- [x] Transfer quantization comparison tooling for paired real-runtime
  benchmark manifests, with explicit fidelity-evidence gating.
- [x] Adaptive KV transfer codec experiment planning: capability-negotiated
  raw, FP8, TurboQuant-style, and Quaternion-Augmented TurboQuant candidate
  codecs, with explicit reversible/lossy semantics and fallback to raw transfer
  or re-prefill.
- [x] Failure-injection tests for interrupted graph and KV migration at the
  transport frame boundary.
- [x] Structured benchmark output suitable for paper updates, including JSON
  aggregates, failure records, and Markdown table generation from migration
  manifests.
- [x] Production secure bidirectional migration transport foundation that can
  replace
  ad-hoc SSH tunnels and provider-specific HTTP bridges with private-network
  `wss://`/mTLS binary streaming first, then QUIC or RDMA/UCX/NIXL where the
  target deployment supports it.
- [x] Cut the AWS real-runtime runner over from SSH tunnel transport to the
  production `wss://`/mTLS transport with ephemeral mTLS bootstrap, explicit
  SSH fallback, cleanup verification, and a full real-runtime AWS proof.
- [x] Model-family/runtime validation profile preflight checks for Qwen, Gemma,
  Phi, and explicit custom MLX-to-vLLM profiles.
- [x] Repeatable validation matrix planner that emits preflight/run commands
  for broader real-runtime evidence.
- [x] Execute a cost-balanced AWS long-horizon confirmation for the current
  Qwen2.5 MLX-to-vLLM path with exact 128-token continuation fidelity,
  production `wss://`/mTLS, QATQ, reverse import, target activity, return-home
  continuation, and direct cleanup verification.
- [x] Execute the next non-Qwen model-family AWS real-runtime E2E proof:
  TinyLlama raw transfer over production `wss://`/mTLS with 22 vLLM layers
  written, exact target baseline/post-migration 16-token continuation,
  reverse import, target graph activity, origin return-home continuation, and
  cleanup verification.
- [x] Investigate larger same-family Qwen2.5 1.5B raw-transfer AWS proof:
  source extraction, production transport streaming, and Agent Memory Graph
  binding reached target commit, but the current vLLM `0.23.0`/T4 FlashInfer
  backend rejects the head-dim-128 shape during `BatchPrefillWithPagedKVCache`;
  keep this profile unvalidated until a supported target backend/runtime path
  is implemented.
- [ ] Add at least one independent target runtime path beyond vLLM. The next
  hard step is an out-of-tree llama.cpp live KV binding hook, not an upstream
  llama.cpp patch: bind PermeantOS canonical KV tensors into a live
  `llama_context`, prove the following decode used the imported KV state, and
  only consider upstreaming once the hook proves the API shape and PermeantOS
  has a stronger adoption case.

Exit criteria:

- [x] Real-runtime E2E runner has automated preflight validation for local,
  AWS, source-runtime, and configuration readiness before cloud provisioning.
- [x] Cleanup is verified automatically and records cleanup verification in the
  state file.
- [x] CI runs a non-provisioning AWS E2E preflight smoke test; scheduled
  disposable-infrastructure validation remains future product release work.

## Phase 10: Public API and release packaging

Turn research prototype surfaces into documented integration points.

Deliverables:

- [x] Stable USXF/Agent Memory Graph versioning policy.
- Rust crates API documentation.
- Python adapter SDK documentation.
- Example applications.
- Release checklist.
- Pull request CI for Rust and Python validation.
- Tag and release validation workflow once binaries, crates, or GitHub Releases
  become part of the release process.
- [x] Compatibility guarantees for manifests and graph schemas.

Exit criteria:

- External contributors can build an adapter without reading PermeantOS internals.
- Users can run a minimal local demo in minutes.
- Cloud E2E validation has a repeatable recipe and known cost envelope.

## Productization Track: Open-Source Platform Maturity

PermeantOS has crossed the threshold from speculative prototype to a validated
early platform. The productization track turns the proof trail into a repeatable
open-source project with stable releases, docs, adapter contracts, and public
evidence jobs.

Deliverables:

- Automated CI evidence jobs for local E2E, adapter conformance, schema
  validation, and non-provisioning cloud preflight.
- Scheduled or manually approved real-runtime evidence jobs for AWS validation
  with strict cost controls and cleanup verification.
- Stable release artifacts: GitHub Releases, signed binaries, checksums, and
  installation instructions.
  - [x] Checksummed binary bundle builder, release manifest schema, install
    instructions, and GitHub Actions artifact upload workflow for tags/manual
    dispatch.
- Rust crate publication plan for PermeantOS crates once APIs are stable enough
  for semantic versioning.
- Python adapter SDK packaging once the command/hook surfaces settle.
- Documentation hub on `www.permeantos.org` or a future docs subdomain.
- Runtime adapter authoring guide with conformance fixtures and evidence
  requirements.
- Public evidence dashboard or generated evidence index linking each validated
  runtime/model path to proof reports, commands, and known limitations.
  - [x] Generated evidence index with schema-versioned JSON, Markdown summary,
    proof-report validation, CI drift tests, and CI generator smoke check.
- QATQ reintegration plan: keep PermeantOS using raw/FP8/in-tree compatibility
  paths until the sibling QATQ project matures into a tested crate and optional
  standalone service.

Exit criteria:

- A new contributor can install PermeantOS, run a local demo, run conformance
  tests, and understand validated claims within one hour.
- Every public claim maps to a versioned proof report or CI evidence job.
- Releases include reproducible binaries or package artifacts, not just tags.
- The docs site explains current support without relying on chat history or
  repository archaeology.

## Release milestones

### v0.1 Validated Platform Baseline

Scope:

- Current KV migration system.
- Real MLX-to-vLLM fidelity proof.
- Paper draft.
- Open-source project hygiene.
- Clear limitations and roadmap.
- Local MLX-to-llama.cpp canonical KV feed evidence.

Quality bar:

- Builds locally from documented steps.
- Reproducible local mock migration.
- Documented AWS real-runtime validation path.
- License, contributing, security, and code of conduct present.

### v0.2 Repeatable Open-Source Platform

Scope:

- Release artifacts, checksums, and GitHub Releases.
- Crate and SDK publishing readiness.
- Documentation hub.
- Automated evidence matrix for supported adapters.
- Broader runtime/model validation beyond the first MLX-to-vLLM and
  MLX-to-llama.cpp paths.

Quality bar:

- CI verifies unit, integration, schema, adapter, and local E2E paths.
- Real-runtime evidence jobs are repeatable, cost-bounded, and cleanup-verified.
- Users can install a binary or package and run the starter migration demo.

### v0.3 Agent Graph Prototype

Scope:

- Agent Memory Graph v0 schema.
- Minimal local graph export/import harness.
- Artifact migration.
- Graph manifest hashing.

### v0.4 KV-Attached Graph Migration

Scope:

- Graph plus live KV migration in one transaction.
- Token-span alignment verification.
- Real MLX-to-vLLM graph-attached E2E run.

### v0.5 Framework Adapters

Scope:

- At least two real agent-runtime adapters.
- Tool replay policies.
- Vector memory rebind/snapshot support.

### v1.0 Stable Research System

Scope:

- Stable USXF and Agent Memory Graph schemas.
- Security policy and provenance model.
- Reproducible multi-model benchmark suite.
- Documented extension API.

## Open research questions

- How long must continuation fidelity be validated before a migration is considered behaviorally equivalent?
- How should graph nodes map to tokenizer-specific spans across runtimes with subtly different prompt formatting?
- Which external capabilities should be migratable, rebindable, or explicitly non-migratable?
- How should non-idempotent in-flight tool calls be represented in a way that is both safe and useful?
- Can prefix-cache migration be generalized across vLLM versions without relying on unstable internals?
- What is the right boundary between PermeantOS and existing distributed cache systems such as LMCache or Mooncake?
- Can adaptive KV transfer codecs, including speculative Quaternion-Augmented
  TurboQuant variants, reduce migration bandwidth without breaking continuation
  fidelity, and what metadata is required to safely rehydrate compressed cache
  state onto richer origin hardware profiles?
- Should the production transport baseline be WebSocket-over-mTLS for
  deployability, or should high-throughput deployments move directly to QUIC,
  RDMA/UCX, or NIXL once runtime adapters can keep the pipeline saturated?

## Immediate next steps

- [x] Add `docs/agent-memory-graph.md` with the v0 schema.
- [x] Build a minimal local graph export/import example.
- [x] Add graph hash fields to migration manifests.
- [x] Extend the analyzer to report prompt, graph, and KV alignment together.
- [x] Prepare a conservative prewarmed AWS image or container recipe to reduce
  E2E bootstrap time without adding always-on infrastructure: document the
  build steps, cleanup steps, expected snapshot/storage cost, and keep model
  weights out of the image unless a later cost/latency calculation justifies
  baking them in.
- [x] Build graph-attached live KV migration planning notes and acceptance
  criteria before changing the migration protocol.
- [x] Add pull request CI for Rust and Python validation.
- [ ] Add tag/release validation workflow once release packaging, binaries, or
  crate publishing become part of the product flow.
- [x] Add non-provisioning AWS E2E preflight validation and wire it into PR CI
  with AWS/source/build checks explicitly skipped.
- [x] Add structured benchmark manifest summary tooling and transport-level
  failure-injection tests for interrupted graph/KV migration frames.
- [x] Add multi-horizon decode-fidelity analysis tooling and AWS runner
  integration for captured continuation artifacts.
- [x] Add larger-than-2k context benchmark matrix planning with checked target
  context-window requirements.
- [x] Add paired transfer-quantization comparison tooling for raw-vs-quantized
  manifest batches with explicit fidelity-evidence gating.
- [x] Add adaptive transfer codec experiment planning for raw, FP8,
  TurboQuant-style, and Quaternion-Augmented TurboQuant candidate modes with
  explicit fallback semantics.
- [x] Add production transport foundation with signed session metadata,
  compact binary frames, mTLS-oriented profile negotiation, frame-size bounds,
  CRC validation, stream IDs, and replay rejection.
- [x] Cut the AWS real-runtime runner over to the production `wss://`/mTLS
  transport with certificate bootstrap, explicit fallback, benchmark evidence,
  and full MLX-to-AWS-vLLM-to-MLX round-trip validation.
- [x] Prototype graph-attached migration manifest extensions and analyzer
  checks behind the existing Agent Memory Graph manifest path.
- [x] Add content-addressed artifact packaging and restored-workspace
  verification to the local Agent Memory Graph harness.
- [x] Wire live MLX and vLLM adapters to produce and validate graph-attached
  span metadata for the same prompt used to prefill the migrated KV cache.
- [x] Run a fresh local E2E validation checkpoint against the current checkout,
  including raw, FP8, graph-bound, and command-backed fixture migration paths.
- [x] Run a fresh AWS real-runtime structural E2E migration after the
  non-skipped preflight passes with a reachable local MLX exporter, refreshed
  AWS identity, visible target subnet, and visible target AMI.
- [x] Rerun the AWS real-runtime E2E validation horizon after the runner's
  source-continuation refresh fix to confirm source-exact decode fidelity.
- [x] Add a production secure bidirectional transport design covering private
  network identity, binary streaming frames, backpressure, resume/retry
  semantics, and a benchmark plan against the current SSH-forwarded TCP path.
- [x] Prove round-trip Agent Memory Graph continuity by migrating origin state
  to AWS, executing target-side work, returning the AWS-updated graph/artifact
  evidence to the origin, and requiring origin-side continuation that depends
  on the remote proof.
- [x] Prove reverse vLLM-to-MLX runtime continuation by exporting the target
  decode boundary through a live target API, importing it into the origin MLX
  runtime, materializing origin-native KV state, and requiring a new origin
  continuation from the target-advanced boundary.

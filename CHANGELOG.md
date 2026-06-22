# Changelog

All notable changes to PermeantOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses release tags compatible with semantic versioning.

## [Unreleased]

### Added

- Added a schema-versioned public evidence index with JSON and Markdown outputs,
  linking validated runtime/model claims to proof reports, repeatable commands,
  CI jobs, and explicit limitations.
- Added a pre-publication release artifact builder, checksummed binary bundle
  manifest, install documentation, and GitHub Actions workflow for uploading
  release artifacts on tags or manual dispatch.
- Added a task-oriented documentation hub in the repository and public website
  docs pages for installation, evidence, adapter authoring, release artifacts,
  and roadmap status.
- Added crate and Python SDK publication-readiness metadata, documentation, a
  machine-readable readiness report, and CI gating that keeps registry
  publishing disabled until the real-release policy is complete.
- Added scheduled/manual evidence jobs with a non-provisioning evidence report,
  uploaded artifacts, and a hard-confirmed self-hosted AWS real-runtime lane
  for cost-controlled validation.
- Added a versioned adapter conformance report that runs runtime adapter tests,
  framework adapter manifest/matrix checks, and reference graph export/import
  fixtures for scheduled evidence jobs.
- Added a tag/manual release validation workflow and
  `permeantos-release-validation-v0` report that verifies changelog promotion,
  release artifact checksums, archive contents, and package-readiness evidence
  without publishing GitHub Releases or package registry artifacts.
- Added `permeant-cli starter-demo`, a one-command loopback migration demo for
  installed binaries that validates the committed manifest, emits
  `permeantos-starter-demo-v0`, and runs in PR CI.
- Added `permeantos-publishing-policy-v0`, documenting ownership, credentials,
  signing, registry publishing, rollback, and current no-publishing enforcement,
  with a CI gate that verifies real publishing remains disabled.
- Added model-family/runtime validation profiles and a matrix planner for
  broadening AWS real-runtime E2E evidence beyond the first Qwen MLX-to-vLLM
  path.
- Added a dedicated single-run AWS long-horizon profile for 128-token
  continuation validation with production transport and QATQ.
- Added AWS long-horizon validation report for run `20260621-052744`, proving
  exact 128-token source/post-migration and baseline/post-migration fidelity
  for the Qwen2.5 MLX-to-vLLM production WSS/QATQ path, including reverse
  runtime import, target graph activity, origin return-home continuation, QATQ
  metrics, and direct cleanup verification.
- Added AWS TinyLlama validation report for run `20260621-085222`, proving the
  first raw-transfer non-Qwen MLX-to-vLLM structural E2E path with 22 target
  layers written, exact target baseline/post-migration 16-token continuation,
  vLLM reverse export, MLX reverse import, target graph activity, origin
  return-home continuation, and direct cleanup verification.
- Added AWS Qwen2.5 1.5B raw-transfer attempt report for runs
  `20260621-093155` and `20260621-095626`, documenting successful source
  extraction, production transport streaming, and graph binding up to target
  commit, plus the current vLLM/T4 FlashInfer backend blocker and cleanup
  verification.
- Added a llama.cpp live state-file binding hook and libllama proof harness,
  proving exact continuation after importing a saved llama.cpp runtime state
  into a fresh target context with auditable binding, continuation, and reverse
  export hashes.
- Added a llama.cpp raw internal KV write proof bridge, proving canonical f32
  K/V tensors can be written directly into `llama_kv_cache` backend tensors:
  deliberate KV corruption changes decode, and direct canonical KV restore
  returns exact source continuation without using llama.cpp state files.
- Added a cross-runtime MLX-to-llama.cpp canonical KV feed proof: a live MLX
  source exports canonical f32 K/V tensors and prompt-span metadata, llama.cpp
  tokenization matches the exported span, the raw writer imports the external
  tensors into `llama_kv_cache`, deliberate corruption changes decode, and the
  restored llama.cpp continuation matches the MLX source token-for-token at the
  aligned decode boundary.

### Changed

- Hardened AWS real-runtime preflight checks so validation profiles, runtime
  pairs, and continuation context-window headroom are checked before cloud
  provisioning.
- Validation profiles now carry explicit model cache geometry so non-Qwen
  model-family runs use the correct layer/head/head-dimension contract instead
  of Qwen-oriented defaults.
- AWS target setup now waits on actual apt/dpkg lock files during cold-host
  bootstrap, avoiding false failures from Ubuntu's
  `unattended-upgrade-shutdown` helper.
- Updated README, roadmap, and validation matrix language to mark the
  Qwen2.5 long-horizon AWS profile and TinyLlama structural AWS profile as
  validated while keeping source-exact TinyLlama parity and non-vLLM coverage
  explicitly pending.
- Adjusted the Qwen2.5 1.5B validation profile to use a 1984-token migrated
  prefix after local probing showed the 2016-token prefix left no source
  continuation headroom.

## [0.1.29-production-transport] - 2026-06-21

### Added

- Production transport foundation in `permeant-transport`, including signed
  session hello metadata, `wss://`/mTLS-oriented profile negotiation, compact
  binary frames, negotiated frame-size bounds, CRC validation, stream IDs, and
  duplicate-frame replay rejection.
- Explicit production transport preference ladder with fallback from private
  `wss://`/mTLS to QUIC/mTLS to framed TCP/mTLS, while rejecting candidates
  that disable mTLS or binary framing.
- Production transport design documentation covering security invariants,
  fallback negotiation, binary frame shape, performance rationale, and AWS
  runner cutover plan.
- AWS real-runtime runner production transport cutover: `production-wss` is now
  the default migration transport, with one-day ephemeral mTLS certificates,
  caller-IP-scoped WSS ingress, a local WSS/mTLS client proxy, target WSS/mTLS
  server proxy, and explicit `ssh-tunnel` fallback.
- AWS production WSS real-runtime E2E proof (`20260620-224819`) showing QATQ
  MLX-to-AWS-vLLM migration over production `wss://`/mTLS, exact 16-token
  continuation fidelity, Agent Memory Graph binding/resume, vLLM reverse
  runtime export, MLX reverse import, origin return-home continuation, and
  verified AWS cleanup.

### Fixed

- AWS target setup now disables Cargo HTTP multiplexing and retries `cargo
  build` to tolerate transient crates.io HTTP/2 failures on fresh hosts.
- Production WSS certificate bootstrap now emits a proper CA certificate with
  critical CA/key-usage extensions accepted by strict Python TLS verification.
- AWS runner cleanup trap now installs before provisioning so failures during
  certificate generation still trigger artifact collection and cloud cleanup.

## [0.1.28-qatq-reverse-runtime-e2e] - 2026-06-20

### Added

- Experimental Quaternion-Augmented TurboQuant (`qatq`) transfer codec path
  with quaternion-grouped int4 payload packing, target-side decode, runner
  support, planner support, and tests.
- AWS real-runtime QATQ validation report showing exact 16-token continuation
  fidelity with 6,294,528 transferred bytes on the complex graph-attached
  MLX-to-vLLM path.
- Agent Memory Graph resume proof that imports the complex graph, resumes
  retry-safe pending work, executes an explicitly approved publish write,
  appends post-import activity evidence, and emits pre/post graph proof hashes.
- AWS real-runtime agent activity continuation proof that runs QATQ KV
  migration, validates exact 16-token vLLM continuation, resumes the same
  complex Agent Memory Graph package on the AWS target, executes pending tool
  work, writes a post-migration artifact, and verifies cloud cleanup.
- Agent Memory Graph return-home proof harness and AWS runner option for
  verifying AWS-updated graph/artifact evidence on the origin and continuing
  from the returned state.
- AWS real-runtime round-trip continuation proof showing QATQ origin-to-AWS KV
  migration, exact 16-token target continuation, AWS target graph activity,
  return of AWS-updated graph/artifact evidence, and origin-side continuation
  from the remote proof.
- Reverse vLLM-to-MLX runtime export/import API and AWS real-runtime proof:
  the target exports its post-migration decode boundary through
  `/export_reverse_runtime_state`, the origin MLX exporter imports the
  target-advanced boundary, materializes origin KV state, and emits a new
  origin continuation proof.
- Production secure bidirectional transport roadmap item covering private
  `wss://`/mTLS binary streaming and future QUIC/RDMA/UCX/NIXL evaluation.

## [0.1.27-complex-agent-e2e] - 2026-06-20

### Added

- Complex Agent Memory Graph harness scenario that exports/imports a 27-node
  package with messages, artifacts, memories, retrieval evidence, credential
  rebinding, completed tool calls, pending retry-safe work, and pending
  user-approved external action policy.
- AWS real-runtime complex-agent validation report proving the current
  MLX-to-vLLM path can commit a graph-attached complex agent package with
  exact 16-token continuation fidelity.

### Changed

- README, website white paper source, arXiv paper sources, and E2E checkpoint
  docs now cite the complex-agent proof and distinguish the validated claim
  from broader future runtime/model coverage.
- Agent Memory Graph harness docs now document the `complex-demo` package used
  by the real-runtime proof.

## [0.1.26-graph-attached-fp8-e2e] - 2026-06-20

### Added

- AWS real-runtime E2E runner can now attach an Agent Memory Graph manifest to
  the migration command and records the manifest path in run state.
- Preflight validation now reports explicit skip/pass/fail status for optional
  Agent Memory Graph manifests before cloud resources are provisioned.
- Graph-attached AWS FP8 transfer-quantization comparison documenting a 4x
  smaller transferred payload with exact 16-token continuation fidelity.

### Changed

- AWS real-runtime E2E runner documentation now covers graph-attached KV
  migration validation and the `PERMEANT_AGENT_GRAPH_MANIFEST` override.
- README, white paper, arXiv paper sources, and validation checkpoint docs now
  cite the graph-attached raw and FP8 AWS E2E results.

### Fixed

- AWS real-runtime E2E slot-probe summary now derives top-level max sampled
  deltas from `key_delta`/`value_delta` fields emitted by the target probe, so
  lossy FP8 runs do not report misleading zero max deltas.

## [0.1.25-aws-source-exact-e2e] - 2026-06-20

### Added

- Fresh E2E validation checkpoint documenting current local migration passes,
  AWS real-runtime structural KV migration, source-exact follow-up fidelity,
  and cleanup verification.

### Fixed

- MLX runtime exporter readiness checks now pass through `GET /` and
  `GET /health`.
- AWS real-runtime E2E runner now handles default unquantized transfer without
  expanding an unset Bash array.
- AWS real-runtime E2E runner now refreshes and validates the live source
  continuation artifact before provisioning or copying it to the target, so
  vLLM prefix-cache seeding does not use a stale short prompt.
- Live MLX source extraction now rewrites the source continuation artifact for
  every extraction request.

### Changed

- Marked the fresh AWS real-runtime E2E validation horizon complete after the
  follow-up run restored exact source/post-migration continuation fidelity.

## [0.1.24-versioning-policy] - 2026-06-20

### Added

- Public versioning policy for USXF, Agent Memory Graph, script report schemas,
  compatibility rules, and lightweight roadmap release tags.
- Public USXF and Agent Memory Graph version constants in the Rust USXF core
  crate and Python SDK.
- Versioning policy tests that pin current schema identifiers and report schema
  strings against documentation and source.

### Changed

- Marked the Phase 10 USXF/Agent Memory Graph versioning policy and
  manifest/schema compatibility guarantee items complete for the documented
  policy and pinned public version surfaces.

## [0.1.23-aws-e2e-preflight-validation] - 2026-06-20

### Added

- AWS real-runtime E2E `preflight` command that writes a structured readiness
  report without provisioning cloud resources.
- PR CI smoke coverage for the AWS E2E preflight path with AWS, local build,
  and source-runtime checks explicitly skipped.
- Preflight documentation covering full-readiness checks, CI skip mode, and
  cleanup verification evidence.

### Changed

- AWS E2E cleanup now records `cleanup_verified_at` in the run state after the
  cleanup verification path completes.
- Marked the Phase 9 E2E readiness, cleanup verification, and safe CI preflight
  validation scope complete while leaving real scheduled disposable
  infrastructure runs for future product-release work.

## [0.1.22-adaptive-transfer-codecs] - 2026-06-20

### Added

- Adaptive transfer codec experiment planner for raw, FP8, TurboQuant-style,
  and Quaternion-Augmented TurboQuant candidate modes, including capability
  negotiation, reversible/lossy semantics, transfer estimates, and fallback
  behavior.
- Documentation for current codec support boundaries, speculative codec
  planning, and fidelity-evidence requirements for lossy transfer claims.

### Changed

- Marked the Phase 9 adaptive KV transfer codec experiment item complete for
  the explicit planning and fallback-semantics scope.

## [0.1.21-transfer-quantization-comparison] - 2026-06-20

### Added

- Transfer quantization comparison tooling for paired raw-vs-quantized
  benchmark manifests, including performance deltas, failure accounting,
  Markdown output, and optional fidelity-horizon evidence gating.
- Documentation for using the comparison tool with larger-context matrix runs
  and for separating performance-only evidence from real-runtime fidelity
  claims.

### Changed

- Marked the Phase 9 transfer-quantization comparison roadmap item complete
  for the paired-manifest tooling scope.

## [0.1.20-larger-context-matrix] - 2026-06-20

### Added

- Larger-context benchmark matrix planner for >2k token runs, including
  required vLLM context-window calculation, source/runner environment blocks,
  Markdown output, and validation tests.
- AWS real-runtime runner support for passing `PERMEANT_VLLM_MAX_MODEL_LEN` to
  the target vLLM process and selecting `PERMEANT_TRANSFER_QUANTIZATION=fp8`
  from benchmark matrix environment blocks.
- Larger-context benchmark matrix documentation covering scope, usage, and
  limitations.

## [0.1.19-fidelity-horizon-suite] - 2026-06-20

### Added

- Multi-horizon decode-fidelity analyzer for captured source, target-baseline,
  and post-migration continuation artifacts, with JSON and Markdown output.
- AWS real-runtime runner integration for configurable continuation token
  counts and generated fidelity horizon reports.
- Fidelity horizon suite documentation covering usage, runner integration, and
  current limitations.

## [0.1.18-reliability-benchmark-pack] - 2026-06-20

### Added

- Structured migration benchmark manifest summarizer with JSON aggregates,
  failure records, and optional Markdown paper-table output.
- Transport failure-injection tests for interrupted Agent Memory Graph binding
  frames and interrupted KV payload chunk frames.
- Benchmark summary tooling documentation covering current scope and
  limitations.

### Changed

- Marked the completed Phase 9 local reliability-pack items in the roadmap
  while keeping longer-horizon, larger-context, codec, and external validation
  work open.

## [0.1.17-graph-security-policy] - 2026-06-20

### Added

- Local Agent Memory Graph security policy gate with graph-root attestation,
  trusted signer checks, provenance-chain audit evidence, raw secret rejection,
  credential rebind enforcement, target runtime allowlists, tool allowlists,
  and artifact path allowlists.
- Threat model for local Agent Memory Graph imports, including current controls
  and limitations.
- Harness tests for tampered graph-root signatures, raw secret fields,
  untrusted target runtimes, disallowed tools, disallowed artifact paths, and
  unsafe credential references.

### Changed

- Marked Phase 8 security, provenance, and policy complete for the local Agent
  Memory Graph harness security boundary.

## [0.1.16-agent-framework-adapters] - 2026-06-20

### Added

- Agent Memory Graph framework adapter conformance layer with dependency-free
  LangGraph-style durable-state and MCP-backed tool/resource session mappings.
- Adapter capability manifest, compatibility matrix, export/import
  conformance CLI, and JSON Schema-backed adapter tests.

### Changed

- Marked Phase 7 runtime adapters for real agent frameworks complete for the
  conformance-mapping scope.
- Aligned the local harness retrieval score breakdown payload with the published
  Agent Memory Graph schema.

## [0.1.15-vector-retrieval-memory] - 2026-06-20

### Added

- Local Agent Memory Graph vector/retrieval memory snapshot validation,
  including deterministic embedding records, query/retrieval equivalence checks,
  embedding model/dimension compatibility checks, and explicit hosted
  vector-store rebind reporting.
- Harness tests for vector retrieval equivalence, embedding model/hash mismatch,
  manifest and retrieval-node result mismatch, external vector rebind reporting,
  and missing rebind marker rejection.

### Changed

- Marked Phase 6 vector and retrieval memory support complete in the roadmap for
  the local Agent Memory Graph harness scope.

## [0.1.14-tool-replay-safety] - 2026-06-20

### Added

- Local Agent Memory Graph side-effect audit for tool calls, including
  no-replay preservation for completed external writes, retry-safe read-only
  pending calls, explicit manual policies for side-effecting pending work, and
  unsafe replay rejection before import activation.
- Harness tests for completed cloud provisioning calls, pending read-only retry,
  manual resume policy enforcement, unsafe external-write retry rejection, and
  expired approval rejection.

### Changed

- Marked Phase 5 tool-call replay and side-effect safety complete in the roadmap
  for the local Agent Memory Graph harness scope.

## [0.1.13-artifact-safety-policies] - 2026-06-20

### Added

- Local Agent Memory Graph artifact export policies for redacted and excluded
  artifacts, with omitted blob bytes represented as explicit external rebind
  requirements.
- Streaming artifact hash verification and restore copy helpers in the local
  graph harness for large-file-safe package import.
- Harness tests for redacted/excluded artifact exports, unresolved external
  artifact rejection, explicit rebind markers, and large artifact restore.

### Changed

- Marked Phase 4 artifact/filesystem migration complete in the roadmap for the
  local Agent Memory Graph harness scope.

## [0.1.12-lazarus-hardening] - 2026-06-20

### Added

- PR CI now enforces `cargo fmt --all -- --check` and strict Clippy
  (`cargo clippy --locked --all-targets --all-features -- -D warnings`) in
  addition to the existing Rust, Python, and SDK test suites.
- Contributor documentation now lists the local validation commands expected
  before opening a pull request.

### Changed

- Normalized Rust workspace formatting so `cargo fmt --all -- --check` is a
  passing project gate.
- Tightened Rust implementation quality so strict Clippy passes across all
  targets and features.

### Fixed

- Rejected malformed encrypted USXF envelopes with invalid AES-GCM nonce lengths
  instead of relying on lower-level parsing behavior.
- Rejected invalid daemon payload chunk metadata before staging tensors,
  including out-of-range block indexes, out-of-range layer indexes, mismatched
  tensor names, and duplicate chunks.

## [0.1.11-daemon-graph-transaction-binding] - 2026-06-20

### Added

- Daemon protocol support for Agent Memory Graph transaction binding, including
  target-side graph/KV evidence validation before the final KV commit.

## [0.1.10-target-tokenizer-span-validation] - 2026-06-20

### Added

- Target tokenizer-view validation for Agent Memory Graph span metadata in the
  vLLM import worker, including prompt text, token IDs, token count, and
  tokenizer hash mismatch rejection before target hook ingest.

## [0.1.9-live-graph-span-metadata] - 2026-06-20

### Added

- Adapter-side Agent Memory Graph span metadata helper, MLX live runtime
  emission for prefill prompts, and vLLM import worker validation before target
  hook ingest.

## [0.1.8-artifact-restore-harness] - 2026-06-19

### Added

- Content-addressed artifact packaging and restored-workspace verification in
  the local Agent Memory Graph harness, including import restore reports and
  path traversal rejection for artifact targets.

## [0.1.7-graph-kv-manifest-spans] - 2026-06-19

### Added

- Pull request CI workflow for Rust workspace tests, Python tests, and the
  Python SDK smoke test.
- Graph-attached migration manifest prototype with `kv_spans` metadata,
  CLI validation, local harness export support, and analyzer reporting for
  missing or invalid graph/KV span evidence.

## [0.1.6-graph-attached-kv-plan] - 2026-06-19

### Added

- Graph-attached live KV migration planning notes and acceptance criteria for
  Phase 3, covering transaction stages, manifest evidence, adapter
  responsibilities, analyzer expectations, and failure cases.

## [0.1.5-aws-prewarm-recipe] - 2026-06-19

### Added

- Conservative AWS prewarm image/container recipe with snapshot-cost guardrails,
  cleanup guidance, and a local snapshot storage cost estimator.

## [0.1.4-analyzer-alignment-report] - 2026-06-19

### Added

- Analyzer `alignment` summary for prompt, Agent Memory Graph, and KV-cache
  status in real-runtime fidelity reports.

## [0.1.3-graph-hash-manifests] - 2026-06-19

### Added

- Optional Agent Memory Graph hash metadata in migration benchmark manifests,
  populated from local graph harness manifests through
  `sim-migrate --agent-graph-manifest`.

## [0.1.2-local-agent-graph-harness] - 2026-06-19

### Added

- Minimal local Agent Memory Graph export/import harness under
  `examples/agent-memory-graph/`, including deterministic prompt
  reconstruction, artifact hash verification, prompt token hash capture, and
  simulated KV hash validation.

## [0.1.1-agent-memory-graph-schema] - 2026-06-19

### Added

- Agent Memory Graph v0 specification, JSON schema, validation fixture, and
  contract tests for the Phase 1 roadmap item.
- Schema coverage for memory tiers, temporal belief metadata, retrieval
  provenance, session checkpoints, compaction summaries, trace spans, handoffs,
  participants, and side-effect approval policy.
- Mnemara-inspired local-first memory concepts, including quality and historical
  lifecycle states, trust levels, episodic continuity, salience, conflict review,
  explainable recall planning, score breakdowns, historical recall modes, and
  portable snapshot/package checkpoints.

### Changed

- Converted the roadmap immediate-next-steps section to a checklist and marked
  the Agent Memory Graph v0 schema item complete.

## [0.1.0-research-preview] - 2026-06-18

### Added

- Initial research preview tag for the live KV-cache migration prototype.
- GitHub issue and pull request templates.

[Unreleased]: https://github.com/kabudu/permeant-os/compare/v0.1.29-production-transport...HEAD
[0.1.29-production-transport]: https://github.com/kabudu/permeant-os/compare/v0.1.28-qatq-reverse-runtime-e2e...v0.1.29-production-transport
[0.1.28-qatq-reverse-runtime-e2e]: https://github.com/kabudu/permeant-os/compare/v0.1.27-complex-agent-e2e...v0.1.28-qatq-reverse-runtime-e2e
[0.1.27-complex-agent-e2e]: https://github.com/kabudu/permeant-os/compare/v0.1.26-graph-attached-fp8-e2e...v0.1.27-complex-agent-e2e
[0.1.26-graph-attached-fp8-e2e]: https://github.com/kabudu/permeant-os/compare/v0.1.25-aws-source-exact-e2e...v0.1.26-graph-attached-fp8-e2e
[0.1.25-aws-source-exact-e2e]: https://github.com/kabudu/permeant-os/compare/v0.1.24-versioning-policy...v0.1.25-aws-source-exact-e2e
[0.1.24-versioning-policy]: https://github.com/kabudu/permeant-os/compare/v0.1.23-aws-e2e-preflight-validation...v0.1.24-versioning-policy
[0.1.23-aws-e2e-preflight-validation]: https://github.com/kabudu/permeant-os/compare/v0.1.22-adaptive-transfer-codecs...v0.1.23-aws-e2e-preflight-validation
[0.1.22-adaptive-transfer-codecs]: https://github.com/kabudu/permeant-os/compare/v0.1.21-transfer-quantization-comparison...v0.1.22-adaptive-transfer-codecs
[0.1.21-transfer-quantization-comparison]: https://github.com/kabudu/permeant-os/compare/v0.1.20-larger-context-matrix...v0.1.21-transfer-quantization-comparison
[0.1.20-larger-context-matrix]: https://github.com/kabudu/permeant-os/compare/v0.1.19-fidelity-horizon-suite...v0.1.20-larger-context-matrix
[0.1.19-fidelity-horizon-suite]: https://github.com/kabudu/permeant-os/compare/v0.1.18-reliability-benchmark-pack...v0.1.19-fidelity-horizon-suite
[0.1.18-reliability-benchmark-pack]: https://github.com/kabudu/permeant-os/compare/v0.1.17-graph-security-policy...v0.1.18-reliability-benchmark-pack
[0.1.17-graph-security-policy]: https://github.com/kabudu/permeant-os/compare/v0.1.16-agent-framework-adapters...v0.1.17-graph-security-policy
[0.1.16-agent-framework-adapters]: https://github.com/kabudu/permeant-os/compare/v0.1.15-vector-retrieval-memory...v0.1.16-agent-framework-adapters
[0.1.15-vector-retrieval-memory]: https://github.com/kabudu/permeant-os/compare/v0.1.14-tool-replay-safety...v0.1.15-vector-retrieval-memory
[0.1.14-tool-replay-safety]: https://github.com/kabudu/permeant-os/compare/v0.1.13-artifact-safety-policies...v0.1.14-tool-replay-safety
[0.1.13-artifact-safety-policies]: https://github.com/kabudu/permeant-os/compare/v0.1.12-lazarus-hardening...v0.1.13-artifact-safety-policies
[0.1.12-lazarus-hardening]: https://github.com/kabudu/permeant-os/compare/v0.1.11-daemon-graph-transaction-binding...v0.1.12-lazarus-hardening
[0.1.11-daemon-graph-transaction-binding]: https://github.com/kabudu/permeant-os/compare/v0.1.10-target-tokenizer-span-validation...v0.1.11-daemon-graph-transaction-binding
[0.1.10-target-tokenizer-span-validation]: https://github.com/kabudu/permeant-os/compare/v0.1.9-live-graph-span-metadata...v0.1.10-target-tokenizer-span-validation
[0.1.9-live-graph-span-metadata]: https://github.com/kabudu/permeant-os/compare/v0.1.8-artifact-restore-harness...v0.1.9-live-graph-span-metadata
[0.1.8-artifact-restore-harness]: https://github.com/kabudu/permeant-os/compare/v0.1.7-graph-kv-manifest-spans...v0.1.8-artifact-restore-harness
[0.1.7-graph-kv-manifest-spans]: https://github.com/kabudu/permeant-os/compare/v0.1.6-graph-attached-kv-plan...v0.1.7-graph-kv-manifest-spans
[0.1.6-graph-attached-kv-plan]: https://github.com/kabudu/permeant-os/compare/v0.1.5-aws-prewarm-recipe...v0.1.6-graph-attached-kv-plan
[0.1.5-aws-prewarm-recipe]: https://github.com/kabudu/permeant-os/compare/v0.1.4-analyzer-alignment-report...v0.1.5-aws-prewarm-recipe
[0.1.4-analyzer-alignment-report]: https://github.com/kabudu/permeant-os/compare/v0.1.3-graph-hash-manifests...v0.1.4-analyzer-alignment-report
[0.1.3-graph-hash-manifests]: https://github.com/kabudu/permeant-os/compare/v0.1.2-local-agent-graph-harness...v0.1.3-graph-hash-manifests
[0.1.2-local-agent-graph-harness]: https://github.com/kabudu/permeant-os/compare/v0.1.1-agent-memory-graph-schema...v0.1.2-local-agent-graph-harness
[0.1.1-agent-memory-graph-schema]: https://github.com/kabudu/permeant-os/compare/v0.1.0-research-preview...v0.1.1-agent-memory-graph-schema
[0.1.0-research-preview]: https://github.com/kabudu/permeant-os/releases/tag/v0.1.0-research-preview

# Changelog

All notable changes to PermeantOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses release tags compatible with semantic versioning.

## [Unreleased]

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

[Unreleased]: https://github.com/kabudu/permeant-os/compare/v0.1.18-reliability-benchmark-pack...HEAD
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

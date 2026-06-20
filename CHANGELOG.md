# Changelog

All notable changes to PermeantOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses release tags compatible with semantic versioning.

## [Unreleased]

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

[Unreleased]: https://github.com/kabudu/permeant-os/compare/v0.1.11-daemon-graph-transaction-binding...HEAD
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

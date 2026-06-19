# Changelog

All notable changes to PermeantOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses release tags compatible with semantic versioning.

## [Unreleased]

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

[Unreleased]: https://github.com/kabudu/permeant-os/compare/v0.1.5-aws-prewarm-recipe...HEAD
[0.1.5-aws-prewarm-recipe]: https://github.com/kabudu/permeant-os/compare/v0.1.4-analyzer-alignment-report...v0.1.5-aws-prewarm-recipe
[0.1.4-analyzer-alignment-report]: https://github.com/kabudu/permeant-os/compare/v0.1.3-graph-hash-manifests...v0.1.4-analyzer-alignment-report
[0.1.3-graph-hash-manifests]: https://github.com/kabudu/permeant-os/compare/v0.1.2-local-agent-graph-harness...v0.1.3-graph-hash-manifests
[0.1.2-local-agent-graph-harness]: https://github.com/kabudu/permeant-os/compare/v0.1.1-agent-memory-graph-schema...v0.1.2-local-agent-graph-harness
[0.1.1-agent-memory-graph-schema]: https://github.com/kabudu/permeant-os/compare/v0.1.0-research-preview...v0.1.1-agent-memory-graph-schema
[0.1.0-research-preview]: https://github.com/kabudu/permeant-os/releases/tag/v0.1.0-research-preview

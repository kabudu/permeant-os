# Changelog

All notable changes to PermeantOS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses release tags compatible with semantic versioning.

## [Unreleased]

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

[Unreleased]: https://github.com/kabudu/permeant-os/compare/v0.1.0-research-preview...HEAD
[0.1.0-research-preview]: https://github.com/kabudu/permeant-os/releases/tag/v0.1.0-research-preview

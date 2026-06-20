# Versioning Policy

This policy defines how PermeantOS versions exchange formats, schemas,
generated reports, SDKs, crates, and lightweight roadmap releases.

## Release Tags

Current releases are lightweight roadmap releases. A release consists of:

- a Keep a Changelog section promoted out of `Unreleased`
- an annotated git tag
- pushed default branch and tag

The current tag format is:

```text
v<major>.<minor>.<patch>-<roadmap-slug>
```

These tags are project milestones, not package publication events. Crates,
Python packages, binaries, GitHub Releases, and signed artifacts are not
published until the repository has explicit release infrastructure for them.

## USXF

The current USXF header version is `1.1`.

Compatibility rules:

- Patch-level behavior changes must not change `usxf_version`.
- Readers must reject unsupported `usxf_version` values rather than attempting a
  best-effort import.
- Additive optional metadata belongs in existing optional fields such as
  `extra` when it does not change required validation semantics.
- New required fields, changed tensor semantics, incompatible layout rules, or
  changed cryptographic requirements require a USXF version bump.
- Writers should emit the lowest USXF version that can accurately represent the
  exported cache state.

The Rust crate exposes `USXF_VERSION` from `usxf_core::version`. The Python SDK
exposes `USXF_VERSION` from `permeantos`.

## Agent Memory Graph

The current Agent Memory Graph schema is:

```text
https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json
```

The current graph payload version is `0.1`.

Compatibility rules:

- Readers must accept graphs with the same major graph version and a lower or
  equal minor graph version.
- Readers may preserve unknown namespaced extension fields.
- Readers must reject unknown core node types, edge types, or unsafe policy
  fields unless a future version explicitly defines them.
- Writers must set `graph_version` to the lowest graph version that can
  represent the exported graph.
- Changes that add optional fields or new namespaced extension payloads may stay
  on the current schema path.
- Changes that add required core fields, remove fields, rename fields, or change
  core node/edge semantics require a new schema path and graph version.

The published schema URL is served by the website project. Repository docs and
tests treat that URL as a stable public identifier.

## Tool Report Schemas

Script-generated reports use explicit schema-version strings. Current public
report schemas are:

| Tool | Schema version |
| --- | --- |
| `scripts/summarize-benchmark-manifests.py` | `permeantos-benchmark-summary-v0` |
| `scripts/analyze-fidelity-horizons.py` | `permeantos-fidelity-horizon-suite-v0` |
| `scripts/plan-context-benchmarks.py` | `permeantos-context-benchmark-matrix-v0` |
| `scripts/compare-transfer-quantization.py` | `permeantos-transfer-quantization-comparison-v0` |
| `scripts/plan-transfer-codecs.py` | `permeantos-transfer-codec-plan-v0` |
| `scripts/aws-real-runtime-e2e.sh preflight` | `permeantos-aws-e2e-preflight-v0` |

Compatibility rules:

- Additive optional fields may keep the same report schema version.
- Removing fields, changing field meaning, changing required fields, or changing
  status values requires a new report schema version.
- Scripts should continue to emit stable machine-readable JSON even when they
  also write Markdown summaries.

## Compatibility Guarantees

PermeantOS is still a research preview. The compatibility guarantee is therefore
limited but explicit:

- Published schema identifiers and report schema strings are stable within a
  release tag.
- Breaking format changes require a new version string or schema path.
- Existing tests pin current public version strings so accidental changes are
  caught in CI.
- Prototype runtime internals, cloud scripts, and experimental adapter hooks may
  evolve, but their generated public artifacts must follow this policy.

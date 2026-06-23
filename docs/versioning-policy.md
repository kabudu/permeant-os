# Versioning Policy

This policy defines how PermeantOS versions exchange formats, schemas,
generated reports, SDKs, crates, and lightweight roadmap releases.

## Release Tags

The repository-level release manifest is `release.toml`. It records the current
product name, product SemVer, product tag, package sets, binary package, and
publishing mode. `scripts/check-release-version.py` treats that manifest as the
source of truth and verifies Rust crate versions, internal path dependency
versions, Python SDK version, binary artifact identity, and publishing-disable
flags. In future real-publishing mode, product release tags must match the
manifest exactly.

Current default releases are lightweight platform milestone releases. A
lightweight release consists of:

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
The roadmap now treats that release infrastructure as platform-maturity work
rather than research-only housekeeping.

Milestone tags are validated with `--release-kind milestone`: they may use the
roadmap suffix while package versions remain pinned by `release.toml`. Future
package/product releases are validated with `--release-kind product`: the tag
must equal `product_tag` in `release.toml`, currently `v0.1.0`.

The repository now has release-artifact and release-validation paths for
pre-publication validation. `scripts/build-release-artifacts.py` creates
checksummed binary archives and a manifest, and `scripts/validate-release.py`
checks tag format, changelog promotion, archive checksums, archive contents,
package-readiness evidence, crate packaging evidence, and release version
consistency evidence. The `Release Artifacts` and `Release Validation`
workflows upload those reports as GitHub Actions artifacts for tags or manual
dispatch. The release validation path also checks Rust crate package dry-runs
through `scripts/check-crate-packaging.py` and version alignment through
`scripts/check-release-version.py`. This is packaging readiness, not GitHub
Release publishing. Creating GitHub Releases, signing assets, publishing
crates, or publishing Python packages still requires the real-release gate
described in Lazarus mode and `docs/publishing-policy.md`.

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
| `scripts/generate-evidence-index.py` | `permeantos-evidence-index-v0` |
| `scripts/build-release-artifacts.py` | `permeantos-release-artifacts-v0` |
| `scripts/validate-release.py` | `permeantos-release-validation-v0` |
| `scripts/check-package-readiness.py` | `permeantos-package-readiness-v0` |
| `scripts/check-crate-packaging.py` | `permeantos-crate-packaging-v0` |
| `scripts/check-publishing-policy.py` | `permeantos-publishing-policy-v0` |
| `scripts/check-release-version.py` | `permeantos-release-version-consistency-v0` |
| `scripts/run-evidence-job.py` | `permeantos-evidence-job-v0` |
| `scripts/run-adapter-conformance.py` | `permeantos-adapter-conformance-v0` |
| `permeant-cli starter-demo` | `permeantos-starter-demo-v0` |

Compatibility rules:

- Additive optional fields may keep the same report schema version.
- Removing fields, changing field meaning, changing required fields, or changing
  status values requires a new report schema version.
- Scripts should continue to emit stable machine-readable JSON even when they
  also write Markdown summaries.

## Compatibility Guarantees

PermeantOS is a validated early platform. The compatibility guarantee is still
limited because the project is pre-1.0, but it is explicit:

- Published schema identifiers and report schema strings are stable within a
  release tag.
- Breaking format changes require a new version string or schema path.
- Existing tests pin current public version strings so accidental changes are
  caught in CI.
- Runtime internals, cloud scripts, and experimental adapter hooks may
  evolve, but their generated public artifacts must follow this policy.

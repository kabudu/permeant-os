# Crate And SDK Publication Plan

PermeantOS now has package metadata and a CI gate for Rust crates and the
Python SDK, but it does not publish registry packages yet.

Current readiness schema: `permeantos-package-readiness-v0`.

## Current Gate

Run the package-readiness verifier:

```bash
scripts/check-package-readiness.py --json-out /tmp/permeantos-package-readiness.json
```

The verifier checks that:

- every Rust crate has name, version, edition, description, licence,
  repository, homepage, README, and `publish = false`;
- the Python SDK has package metadata, licence, public URLs, dependencies,
  classifiers, and an existing package README;
- the Python SDK declares `tool.permeantos.release.publish = false`;
- the report records that no crates or Python packages have been published.

Run the crate packaging verifier:

```bash
scripts/check-crate-packaging.py --json-out /tmp/permeantos-crate-packaging.json
```

The packaging verifier checks that every internal path dependency has a
matching version constraint and runs `cargo package --locked --no-verify` for
workspace crates that do not depend on unpublished internal crates. Downstream
crate package verification is reported as deferred until the internal crates are
published in order; Cargo resolves versioned path dependencies against
crates.io during packaging, so those archives cannot be produced honestly before
the upstream packages exist.

`publish = false` is intentional. Publishing remains behind the real-release
gate in `docs/versioning-policy.md` and `docs/publishing-policy.md`: package
ownership, credentials, release validation, semantic versioning, signing,
rollback ownership, and an explicit release request must exist before registry
publication is enabled.

## Rust Crate Plan

The first publishable crate set should be split by API stability:

| Crate | Future role | Current status |
| --- | --- | --- |
| `usxf-core` | Public exchange-format types and version constants | Metadata complete, publish gated |
| `permeant-transport` | Migration frame and session negotiation primitives | Metadata complete, publish gated |
| `permeant-transpiler` | KV layout normalization and transfer codec planning | Metadata complete, publish gated |
| `permeant-extractor` | Source runtime adapter boundary | Metadata complete, publish gated |
| `permeant-injector` | Target runtime adapter boundary | Metadata complete, publish gated |
| `permeant-orchestrator` | Migration orchestration and commit coordination | Metadata complete, publish gated |
| `permeant-qatq-migration` | Exact typed QATQ migration artifact manifests and restore validation | Metadata complete, publish gated |
| `permeant-cli` | Binary CLI package | Metadata complete, publish gated |
| external `qatq` | QATQ exact transfer-compression codec | Consumed from crates.io as `qatq = "0.1.1"` |

Before enabling crates.io publication:

1. Decide crate ownership and reserved package names.
2. Keep internal path dependencies paired with matching version constraints
   suitable for crates.io packaging.
3. Run `scripts/check-crate-packaging.py` and review the dry-run/deferred
   package report.
4. Run full `cargo package --locked` verification in publish order once each
   upstream internal crate is available to downstream package verification.
5. Verify README, licence, repository, homepage, keywords, and categories.
6. Document the crate publish order and rollback procedure.
7. Enable publishing crate by crate by removing `publish = false` only in the
   release PR that performs the real publish.

## Python SDK Plan

The Python SDK currently supports local client and Agent Memory Graph helper
work. It is not yet packaged for PyPI publication.

Before enabling Python package publication:

1. Decide package ownership for `permeantos`.
2. Add wheel/sdist build validation in CI.
3. Add `python -m build` and `twine check` to the release gate.
4. Document supported Python versions and runtime adapter dependency extras.
5. Configure package credentials through the intended secret store.
6. Enable publication by setting `tool.permeantos.release.publish = true` only
   in the release PR that performs the real publish.

## Safety Boundary

The current release artifact workflow creates downloadable binary bundles as
GitHub Actions artifacts. It does not create GitHub Releases, publish crates,
publish Python packages, or sign release assets.

That boundary is enforced by:

- `scripts/check-package-readiness.py`;
- `scripts/check-crate-packaging.py`;
- `tests/test_package_readiness.py`;
- `publish = false` in Rust crate manifests;
- `tool.permeantos.release.publish = false` in the Python SDK manifest;
- the real-release exception in Lazarus mode, `docs/versioning-policy.md`, and
  `docs/publishing-policy.md`.

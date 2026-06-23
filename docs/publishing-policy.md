# Publishing Policy

PermeantOS supports pre-publication release artifacts today. Real publishing is
gated until the project has explicit ownership, credentials, signing, and
rollback readiness.

Current policy schema: `permeantos-publishing-policy-v0`.

## Current Mode

The current mode is `pre-publication`.

Allowed actions:

- build checksummed binary archives with `scripts/build-release-artifacts.py`;
- validate artifacts with `scripts/validate-release.py`;
- upload workflow artifacts from GitHub Actions;
- run package-readiness checks with publishing disabled;
- run Rust crate package dry-runs with publishing disabled;
- create lightweight roadmap tags after changelog promotion.

Forbidden actions until the real-release gate is opened:

- create GitHub Releases;
- upload signed release assets;
- run `cargo publish`;
- run `twine upload`;
- publish containers or package-registry artifacts;
- store package registry tokens outside the intended secret store.

## Ownership

Before real publishing is enabled, the release PR must document:

- GitHub Release owner and approval path;
- crate ownership for every publishable crate;
- PyPI ownership for the Python adapter SDK;
- signing-key owner and rotation plan;
- rollback owner for failed or yanked packages.

## Credentials

Publishing credentials must be configured only through GitHub environments or
the chosen secret store. Credentials must never be committed, written into
generated reports, or printed in CI logs.

Required future secret classes:

- GitHub Release publishing token or GitHub App permission;
- crates.io token scoped to the intended crates;
- PyPI trusted-publishing configuration or scoped token;
- release signing key material or signing-service identity.

## Signing

Signed GitHub Release assets require:

- a documented signing tool and signature format;
- checksum generation before signing;
- signature verification instructions;
- key identity, rotation, and revocation procedure;
- CI validation that refuses unsigned release assets in real-publishing mode.

Until then, release artifacts include checksums but are not signed GitHub
Release assets.

## Registry Publishing

Rust crates and the Python SDK stay publish-disabled in source control until
the release PR that performs the real publish.

Before enabling crates.io:

1. Reserve or confirm crate ownership.
2. Replace path-only dependency edges with publishable version constraints.
3. Run `scripts/check-crate-packaging.py` and review the generated dry-run
   package report.
4. Run full `cargo package --locked` verification in publish order once each
   upstream internal crate is available to downstream package verification.
5. Document publish order, rollback, and yank procedure.
6. Remove `publish = false` only for crates included in the real release.

Before enabling PyPI:

1. Confirm package ownership for `permeantos`.
2. Add wheel and sdist build validation.
3. Run `python -m build` and `twine check`.
4. Document Python version and optional dependency support.
5. Enable publication only in the real-release PR.

## Rollback

The real-release runbook must include:

- how to stop a release after artifact validation but before publishing;
- how to mark a GitHub Release as withdrawn;
- crate yank criteria and owner;
- Python package yank criteria and owner;
- changelog and tag correction procedure.

## Current Enforcement

The current policy is enforced by:

- `scripts/check-publishing-policy.py`;
- `tests/test_publishing_policy.py`;
- `scripts/check-package-readiness.py`;
- `scripts/check-crate-packaging.py`;
- `scripts/validate-release.py`;
- `publish = false` in Rust crate manifests;
- `tool.permeantos.release.publish = false` in the Python SDK manifest;
- GitHub Actions workflows that do not run real publishing commands.

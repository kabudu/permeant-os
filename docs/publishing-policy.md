# Publishing Policy

PermeantOS is configured for its first guarded production release. Real
publishing is available only through the manual `Real Release` workflow and the
protected release environments.

Current policy schema: `permeantos-publishing-policy-v0`.
Current real release config schema: `permeantos-real-release-config-v0`.
Current real release plan schema: `permeantos-real-release-plan-v0`.

## Current Mode

The current mode is `production`.

Allowed actions:

- build checksummed binary archives with `scripts/build-release-artifacts.py`;
- validate artifacts with `scripts/validate-release.py`;
- upload workflow artifacts from GitHub Actions;
- run package-readiness checks that confirm the Rust crates are publishable and
  the Python SDK remains publish-disabled;
- run Rust crate package dry-runs before registry publication;
- run release version consistency checks against `release.toml`;
- run the manual `Real Release` workflow for the product tag recorded in
  `release.toml`;
- create lightweight roadmap tags only when they are not confused with product
  publishing events.

Forbidden actions outside the guarded real-release workflow:

- create GitHub Releases;
- upload signed release assets;
- run `cargo publish`;
- run `twine upload`;
- publish containers or package-registry artifacts;
- store package registry tokens outside the intended secret store.

## Ownership

The real-release path is owned by:

- GitHub Release owner and approval path: `kabudu`, through the protected
  `github-release` environment;
- crate ownership for every publishable crate: `kabudu`, through the protected
  `crates-io` environment;
- PyPI ownership for the Python adapter SDK: deferred because Python publishing
  remains disabled;
- signing-key owner and rotation plan: `kabudu`, through Apple Developer ID
  credentials held as repository secrets and the protected
  `apple-notarization` environment;
- rollback owner for failed or yanked packages: `kabudu`.

## Credentials

Publishing credentials must be configured only through GitHub environments or
the chosen secret store. Credentials must never be committed, written into
generated reports, or printed in CI logs.

Required secret classes:

- GitHub Release publishing token or GitHub App permission;
- `CARGO_REGISTRY_TOKEN`: crates.io token scoped to the intended crates;
- PyPI trusted-publishing configuration or scoped token, when Python publishing
  is enabled in a future release;
- release signing key material or signing-service identity.

## Signing

Signed GitHub Release assets require:

- a documented signing tool and signature format;
- checksum generation before signing;
- signature verification instructions;
- key identity, rotation, and revocation procedure;
- CI validation that refuses unsigned release assets in real-publishing mode.

The macOS product-release path is modelled on the sibling QATQ release
workflow. It requires:

- `APPLE_CERTIFICATE`: base64-encoded Developer ID Application `.p12`
  certificate;
- `APPLE_CERTIFICATE_PASSWORD`: password for that certificate;
- `APPLE_SIGNING_IDENTITY`: Developer ID Application signing identity, either
  as a secret or repository/environment variable;
- `APPLE_ID`: Apple ID for notarization;
- `APPLE_PASSWORD`: app-specific password for notarization;
- `APPLE_TEAM_ID`: Apple Developer Team ID, either as a secret or
  repository/environment variable;
- a protected `apple-notarization` GitHub environment.

The Rust crate publishing path requires:

- `CARGO_REGISTRY_TOKEN`: crates.io API token scoped to the PermeantOS crates;
- a protected `crates-io` GitHub environment.

The workflow imports the certificate into a temporary keychain, signs
`permeant-cli` with `codesign --options runtime`, packages a macOS ZIP archive,
and submits it with `xcrun notarytool submit --wait` before release upload.

## Registry Publishing

Rust crates are publishable only in production mode and only through the
guarded release workflow. The Python SDK stays publish-disabled until a future
release adds wheel/sdist validation and PyPI ownership.

Before running crates.io publication:

1. Reserve or confirm crate ownership.
2. Replace path-only dependency edges with publishable version constraints.
3. Run `scripts/check-crate-packaging.py` and review the generated dry-run
   package report.
4. Run `scripts/check-release-version.py --release-kind product` for the
   intended product tag and confirm it matches `release.toml`.
5. Run `scripts/check-real-release-config.py` for the intended publish targets
   and confirm the real-release PR has intentionally enabled them.
6. Run full `cargo package --locked` verification in publish order once each
   upstream internal crate is available to downstream package verification.
7. Document publish order, rollback, and yank procedure.
8. Confirm `publish = false` has been removed only for crates included in the
   real release.

Before enabling PyPI:

1. Confirm package ownership for `permeantos`.
2. Add wheel and sdist build validation.
3. Run `python -m build` and `twine check`.
4. Document Python version and optional dependency support.
5. Enable publication only in the real-release PR.

## Real Release Workflow

`.github/workflows/real-release.yml` is manual-only and must be run from
`master`. `scripts/plan-real-release.py` emits the plan from `release.toml`,
then `scripts/check-real-release-config.py` requires
`release_mode = "production"`, the requested tag to match `release.toml`, and
explicit publish flags for the requested targets.

Release approvers must review `real-release-plan.json` before approving
protected environments. The report records:

- product tag and release mode;
- Linux and macOS artifact targets and archive formats;
- whether macOS artifacts are expected to be signed and notarized;
- protected environments required for the run;
- required secret names;
- Rust crate publish order.

Publishing jobs are protected by GitHub environments:

- `apple-notarization` for Apple signing and notarization;
- `github-release` for GitHub Release creation;
- `crates-io` for Rust crate publication.

The publishing-policy checker permits `gh release create` and `cargo publish`
only inside that guarded workflow. The commands remain forbidden in normal CI,
release-validation and evidence workflows.

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
- `scripts/check-release-version.py`;
- `scripts/plan-real-release.py`;
- `scripts/check-real-release-config.py`;
- `scripts/validate-release.py`;
- `release.toml` with production publishing flags set only for supported
  targets;
- Rust crate manifests that are publishable only for crates included in the
  product release;
- `tool.permeantos.release.publish = false` in the Python SDK manifest;
- GitHub Actions workflows that do not run real publishing commands.

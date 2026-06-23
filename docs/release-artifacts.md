# Release Artifacts

PermeantOS release artifacts are built by `scripts/build-release-artifacts.py`
and validated by `scripts/validate-release.py`. The builder creates a binary
archive, `checksums.txt`, and a machine-readable `release-manifest.json`
without publishing anything. The validator checks the tag format, changelog
promotion, artifact manifest, archive checksums, archive contents, and optional
package-readiness, crate-packaging, and release-version-consistency reports.

Current artifact schema: `permeantos-release-artifacts-v0`.
Current validation schema: `permeantos-release-validation-v0`.
Current release version consistency schema:
`permeantos-release-version-consistency-v0`.
Current real release config schema: `permeantos-real-release-config-v0`.
Current real release plan schema: `permeantos-real-release-plan-v0`.

## Build Locally

```bash
scripts/build-release-artifacts.py \
  --version v0.1.30-platform \
  --out-dir dist/release
```

By default the script builds the host target with:

```bash
cargo build --locked --release -p permeant-cli
```

The output directory contains:

- `permeantos-<version>-<target>.tar.gz`
- `checksums.txt`
- `release-manifest.json`
- a temporary `staging/` directory used to assemble archives

Each archive includes:

- `bin/permeant-cli`
- `LICENSE`
- `README.md`
- `INSTALL.md`

## GitHub Actions

The `Release Artifacts` workflow runs on:

- manual `workflow_dispatch` with an explicit version string;
- pushes to tags matching `v*`.

It builds the Linux `x86_64-unknown-linux-gnu` bundle and uploads the archive,
checksum file, and manifest as workflow artifacts.

The `Release Validation` workflow runs on the same tag pattern and on manual
dispatch. It builds the Linux artifact bundle, runs the package-readiness and
crate-packaging gates, checks `release.toml` version consistency, and writes
`release-validation.json`. Tag-triggered runs are strict: the matching
changelog section must already be promoted out of `Unreleased`. Manual
candidate runs may set `allow_unreleased_changelog=true` when validating
artifacts before the final changelog promotion. Manual dispatch defaults to
`release_kind=milestone`; future product/package publishing must use
`release_kind=product`, which requires the requested tag to match
`release.toml` exactly.

This workflow intentionally does not create GitHub Releases, publish crates, or
publish package registry artifacts. Those steps remain behind the real-release
gate in `docs/versioning-policy.md` and `docs/publishing-policy.md`: publishing
requires documented ownership, credentials through the intended secure path,
release validation, signing policy, rollback ownership, and an explicit user
request for that release mode.

The `Real Release` workflow is present but fail-closed while `release.toml`
uses `release_mode = "pre-publication"`. It is manual-only and requires
`scripts/plan-real-release.py`, `scripts/check-release-version.py`, and
`scripts/check-real-release-config.py` to pass before any publishing job can
run. `scripts/plan-real-release.py` emits `real-release-plan.json`, the
reviewable release plan for artifact targets, protected environments, required
secrets, and Rust crate publish order. Once a future real-release PR switches
the manifest to production and enables the intended publish flags, the workflow
can:

- build Linux release archives;
- build macOS ZIP archives after signing `permeant-cli` with a Developer ID
  Application certificate;
- submit macOS ZIP archives to Apple notarization with
  `xcrun notarytool submit --wait`;
- create a GitHub Release from staged artifacts behind the `github-release`
  environment;
- publish Rust crates in dependency order behind the `crates-io` environment.

The macOS path follows the sibling QATQ release model: Apple credentials are
provided through GitHub secrets/variables, the certificate is imported into a
temporary keychain, binaries are signed with the hardened runtime option, and
the ZIP archive is notarized before upload.

The Rust publishing path uses the standard Cargo secret name
`CARGO_REGISTRY_TOKEN` from the protected `crates-io` environment.

## Verify An Archive

After downloading workflow artifacts:

```bash
sha256sum -c checksums.txt
tar -tzf permeantos-<version>-<target>.tar.gz
```

On macOS, use:

```bash
shasum -a 256 -c checksums.txt
```

Validate the full local artifact set:

```bash
scripts/check-package-readiness.py --json-out dist/release/package-readiness.json
scripts/check-crate-packaging.py --json-out dist/release/crate-packaging.json
scripts/check-release-version.py \
  --release-version v0.1.30-platform \
  --release-kind milestone \
  --json-out dist/release/release-version.json
scripts/validate-release.py \
  --version v0.1.30-platform \
  --artifact-dir dist/release \
  --package-readiness dist/release/package-readiness.json \
  --crate-packaging dist/release/crate-packaging.json \
  --release-version-consistency dist/release/release-version.json \
  --json-out dist/release/release-validation.json
```

Build a macOS ZIP artifact for signing/notarization workflows:

```bash
scripts/build-release-artifacts.py \
  --version v0.1.0 \
  --target aarch64-apple-darwin \
  --archive-format zip \
  --codesign-identity "Developer ID Application: Example" \
  --out-dir dist/release/macos
```

Preview the real-release plan without publishing:

```bash
scripts/plan-real-release.py \
  --release-version v0.1.0 \
  --json-out dist/real-release/real-release-plan.json
```

## Install

Extract the archive and put the bundled binary on `PATH`:

```bash
tar -xzf permeantos-<version>-<target>.tar.gz
export PATH="$PWD/permeantos-<version>-<target>/bin:$PATH"
permeant-cli --help
```

Run the starter migration demo from the installed binary:

```bash
permeant-cli starter-demo --seq-len 128 --out-dir .permeant-demo
```

The demo starts a loopback daemon, performs a bounded simulated KV migration,
validates the committed manifest, and writes
`.permeant-demo/starter-demo-report.json` using schema
`permeantos-starter-demo-v0`.

## Compatibility Boundary

These artifacts are pre-1.0 platform bundles. They prove that PermeantOS can
produce and validate checksummed binary packages from the repository, but they
are not yet registry-published packages or signed GitHub Release assets. The
next release maturity step is to add GitHub Release creation and signing once
the repository has the explicit publishing policy, signing path, and credentials
path for that mode.

# Release Artifacts

PermeantOS release artifacts are built by `scripts/build-release-artifacts.py`.
The script creates a binary archive, `checksums.txt`, and a machine-readable
`release-manifest.json` without publishing anything.

Current artifact schema: `permeantos-release-artifacts-v0`.

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

This workflow intentionally does not create GitHub Releases, publish crates, or
publish package registry artifacts. Those steps remain behind the real-release
gate in `docs/versioning-policy.md`: publishing requires documented ownership,
credentials through the intended secure path, release validation, and an
explicit user request for that release mode.

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

## Install

Extract the archive and put the bundled binary on `PATH`:

```bash
tar -xzf permeantos-<version>-<target>.tar.gz
export PATH="$PWD/permeantos-<version>-<target>/bin:$PATH"
permeant-cli --help
```

## Compatibility Boundary

These artifacts are pre-1.0 platform bundles. They prove that PermeantOS can
produce checksummed binary packages from the repository, but they are not yet
registry-published packages or signed GitHub Release assets. The next release
maturity step is to add GitHub Release creation and signing once the repository
has the explicit publishing policy and credentials path for that mode.

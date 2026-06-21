#!/usr/bin/env python3
"""Build PermeantOS release artifact bundles and checksums.

This script prepares local release artifacts without publishing them. It is the
source of truth for the release-artifact manifest consumed by CI and future
GitHub Release publishing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-release-artifacts-v0"
PACKAGE = "permeant-cli"
BIN_NAME = "permeant-cli"
ROOT = Path(__file__).resolve().parents[1]
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._+-]+$")


@dataclass(frozen=True)
class Artifact:
    target: str
    archive_path: Path
    archive_sha256: str
    archive_bytes: int
    binary_name: str

    def to_json(self, out_dir: Path) -> dict[str, Any]:
        return {
            "target": self.target,
            "archive": str(self.archive_path.relative_to(out_dir)),
            "archive_sha256": self.archive_sha256,
            "archive_bytes": self.archive_bytes,
            "binary": self.binary_name,
        }


def safe_component(value: str, *, label: str) -> str:
    if not value or not SAFE_COMPONENT.fullmatch(value):
        raise SystemExit(f"{label} must match {SAFE_COMPONENT.pattern}: {value!r}")
    return value


def host_target() -> str:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower() or "unknown"
    if system == "darwin":
        os_name = "apple-darwin"
    elif system == "linux":
        os_name = "unknown-linux-gnu"
    else:
        os_name = system
    arch = {"arm64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine, machine)
    return f"{arch}-{os_name}"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def binary_path_for_target(target: str, *, explicit_binary: Path | None) -> Path:
    if explicit_binary is not None:
        return explicit_binary
    target_dir = ROOT / "target"
    if target == host_target():
        return target_dir / "release" / BIN_NAME
    return target_dir / target / "release" / BIN_NAME


def build_target(target: str, *, skip_build: bool, explicit_binary: Path | None) -> Path:
    if not skip_build:
        command = ["cargo", "build", "--locked", "--release", "-p", PACKAGE]
        if target != host_target():
            command.extend(["--target", target])
        run(command)

    binary = binary_path_for_target(target, explicit_binary=explicit_binary)
    if not binary.is_file():
        raise SystemExit(f"built binary not found for {target}: {binary}")
    return binary


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_if_exists(source: Path, dest: Path) -> None:
    if source.is_file():
        shutil.copy2(source, dest)


def stage_artifact(version: str, target: str, binary: Path, out_dir: Path) -> Path:
    bundle_name = f"permeantos-{version}-{target}"
    stage = out_dir / "staging" / bundle_name
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "bin").mkdir(parents=True)
    shutil.copy2(binary, stage / "bin" / BIN_NAME)
    copy_if_exists(ROOT / "LICENSE", stage / "LICENSE")
    copy_if_exists(ROOT / "README.md", stage / "README.md")

    install = stage / "INSTALL.md"
    install.write_text(
        "\n".join(
            [
                "# PermeantOS Binary Install",
                "",
                f"Artifact version: `{version}`",
                f"Target: `{target}`",
                "",
                "Add the bundled `bin` directory to your `PATH`, or copy `bin/permeant-cli` to a directory already on your `PATH`.",
                "",
                "Verify the downloaded archive against `checksums.txt` before installing.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return stage


def create_archive(stage: Path, out_dir: Path) -> Path:
    archive = out_dir / f"{stage.name}.tar.gz"
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(stage.rglob("*")):
            tar.add(path, arcname=Path(stage.name) / path.relative_to(stage), recursive=False)
    return archive


def write_outputs(version: str, artifacts: list[Artifact], out_dir: Path) -> dict[str, Any]:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "package": PACKAGE,
        "binary": BIN_NAME,
        "artifacts": [artifact.to_json(out_dir) for artifact in artifacts],
        "publishing": {
            "github_release_created": False,
            "crates_published": False,
            "notes": "This manifest records built artifacts only. Publishing requires the documented real-release gate.",
        },
    }
    (out_dir / "release-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum_lines = [f"{artifact.archive_sha256}  {artifact.archive_path.name}" for artifact in artifacts]
    (out_dir / "checksums.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    return manifest


def build_artifacts(version: str, targets: list[str], out_dir: Path, *, skip_build: bool, explicit_binary: Path | None) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for target in targets:
        safe_target = safe_component(target, label="target")
        binary = build_target(safe_target, skip_build=skip_build, explicit_binary=explicit_binary)
        stage = stage_artifact(version, safe_target, binary, out_dir)
        archive = create_archive(stage, out_dir)
        artifacts.append(
            Artifact(
                target=safe_target,
                archive_path=archive,
                archive_sha256=sha256_file(archive),
                archive_bytes=archive.stat().st_size,
                binary_name=BIN_NAME,
            )
        )
    return write_outputs(version, artifacts, out_dir)


def default_version() -> str:
    ref_name = os.getenv("GITHUB_REF_NAME")
    if ref_name:
        return ref_name
    cargo = (ROOT / "crates" / "cli" / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.MULTILINE)
    if not match:
        raise SystemExit("could not determine version from crates/cli/Cargo.toml")
    return f"v{match.group(1)}-local"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=default_version(), help="Release version or tag to embed in artifact names.")
    parser.add_argument("--target", action="append", default=[], help="Rust target triple to build; may be repeated. Defaults to host target.")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist" / "release", help="Directory for archives, checksums, and manifest.")
    parser.add_argument("--skip-build", action="store_true", help="Skip cargo build and package an existing binary. Intended for tests.")
    parser.add_argument("--binary-path", type=Path, help="Existing binary to package when --skip-build is set.")
    args = parser.parse_args()

    version = safe_component(args.version, label="version")
    targets = args.target or [host_target()]
    if args.binary_path and not args.skip_build:
        raise SystemExit("--binary-path is only valid with --skip-build")
    manifest = build_artifacts(
        version,
        targets,
        args.out_dir,
        skip_build=args.skip_build,
        explicit_binary=args.binary_path,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

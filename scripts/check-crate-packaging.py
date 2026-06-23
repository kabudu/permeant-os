#!/usr/bin/env python3
"""Dry-run package PermeantOS Rust crates for future crates.io release.

This gate does not publish anything. It verifies that workspace path
dependencies carry matching version constraints and that crates without
unpublished internal dependencies can produce Cargo package archives. Downstream
crates are reported as packaging-deferred until their internal dependencies are
published in order; Cargo resolves versioned path dependencies against the
registry during packaging, so those archives cannot be produced honestly before
the upstream packages exist on crates.io.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-crate-packaging-v0"
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def workspace_member_manifests() -> list[Path]:
    root = load_toml(ROOT / "Cargo.toml")
    manifests: list[Path] = []
    for member in root.get("workspace", {}).get("members", []):
        manifest = ROOT / member / "Cargo.toml"
        if not manifest.is_file():
            raise SystemExit(f"workspace member manifest missing: {manifest}")
        manifests.append(manifest)
    return sorted(manifests)


def package_name(manifest: Path) -> str:
    return str(load_toml(manifest).get("package", {}).get("name", manifest.parent.name))


def package_version(manifest: Path) -> str:
    version = load_toml(manifest).get("package", {}).get("version")
    if not version:
        raise SystemExit(f"package.version missing in {manifest}")
    return str(version)


def dependency_sections(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sections: list[tuple[str, dict[str, Any]]] = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        value = document.get(section, {})
        if isinstance(value, dict):
            sections.append((section, value))
    for target_name, target in document.get("target", {}).items():
        if not isinstance(target, dict):
            continue
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            value = target.get(section, {})
            if isinstance(value, dict):
                sections.append((f"target.{target_name}.{section}", value))
    return sections


def check_path_dependency_versions(manifests: list[Path]) -> list[Check]:
    checks: list[Check] = []
    for manifest in manifests:
        document = load_toml(manifest)
        for section, dependencies in dependency_sections(document):
            for dep_name, dep_value in dependencies.items():
                if not isinstance(dep_value, dict) or "path" not in dep_value:
                    continue
                dep_manifest = (manifest.parent / str(dep_value["path"]) / "Cargo.toml").resolve()
                if not dep_manifest.is_file():
                    checks.append(
                        Check(
                            f"path-dependency-exists:{package_name(manifest)}:{dep_name}",
                            False,
                            f"{section}.{dep_name} points at missing {dep_manifest}",
                        )
                    )
                    continue
                expected_version = package_version(dep_manifest)
                actual_version = dep_value.get("version")
                checks.append(
                    Check(
                        f"path-dependency-version:{package_name(manifest)}:{dep_name}",
                        actual_version == expected_version,
                        f"{section}.{dep_name} version={actual_version!r}, dependency package version={expected_version!r}",
                    )
                )
    return checks


def internal_path_dependencies(manifest: Path) -> list[str]:
    document = load_toml(manifest)
    deps: list[str] = []
    for _section, dependencies in dependency_sections(document):
        for dep_name, dep_value in dependencies.items():
            if isinstance(dep_value, dict) and "path" in dep_value:
                dep_manifest = (manifest.parent / str(dep_value["path"]) / "Cargo.toml").resolve()
                if dep_manifest.is_file() and ROOT in dep_manifest.parents:
                    deps.append(dep_name)
    return sorted(set(deps))


def run_cargo_package(manifest: Path, target_dir: Path, *, skip_cargo: bool) -> Check:
    name = package_name(manifest)
    internal_deps = internal_path_dependencies(manifest)
    if internal_deps:
        return Check(
            f"cargo-package-deferred:{name}",
            True,
            "deferred until internal dependencies are published: " + ", ".join(internal_deps),
        )
    if skip_cargo:
        return Check(f"cargo-package:{name}", True, "skipped by --skip-cargo")
    command = [
        "cargo",
        "package",
        "--locked",
        "--allow-dirty",
        "--no-verify",
        "-p",
        name,
        "--target-dir",
        str(target_dir),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    detail = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if len(detail) > 4000:
        detail = detail[-4000:]
    return Check(f"cargo-package:{name}", result.returncode == 0, detail or "cargo package completed")


def build_report(*, skip_cargo: bool) -> dict[str, Any]:
    manifests = workspace_member_manifests()
    checks = [*check_path_dependency_versions(manifests)]
    with tempfile.TemporaryDirectory(prefix="permeantos-crate-package-") as temp_dir:
        target_dir = Path(temp_dir) / "target"
        checks.extend(run_cargo_package(manifest, target_dir, skip_cargo=skip_cargo) for manifest in manifests)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "mode": "dry-run",
        "publishing_enabled": False,
        "cargo_package_verify": "direct-for-crates-without-internal-path-dependencies",
        "downstream_package_verify": "deferred-until-internal-crates-are-published",
        "packages": [
            {
                "name": package_name(manifest),
                "version": package_version(manifest),
                "manifest": str(manifest.relative_to(ROOT)),
            }
            for manifest in manifests
        ],
        "checks": [check.to_json() for check in checks],
    }
    report["ok"] = all(check["ok"] for check in report["checks"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, help="Optional path to write the packaging report JSON.")
    parser.add_argument("--skip-cargo", action="store_true", help="Skip cargo package execution and only verify manifests.")
    args = parser.parse_args()

    report = build_report(skip_cargo=args.skip_cargo)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

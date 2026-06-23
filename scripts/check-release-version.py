#!/usr/bin/env python3
"""Verify PermeantOS release version consistency.

This gate makes `release.toml` the source of truth for future product/package
releases. It does not publish anything. In `product` mode it requires the
requested release tag to match the manifest exactly. In `milestone` mode it
allows the existing roadmap tag style while still enforcing package-version
consistency inside the repository.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-release-version-consistency-v0"
MANIFEST_SCHEMA_VERSION = "permeantos-release-manifest-v0"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release.toml"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$")
TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z._-]*)?)$")


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


def package_name(manifest: Path) -> str:
    return str(load_toml(manifest).get("package", {}).get("name", manifest.parent.name))


def package_version(manifest: Path) -> str:
    version = load_toml(manifest).get("package", {}).get("version")
    if not version:
        raise SystemExit(f"package.version missing in {manifest}")
    return str(version)


def workspace_member_manifests() -> list[Path]:
    workspace = load_toml(ROOT / "Cargo.toml")
    manifests: list[Path] = []
    for member in workspace.get("workspace", {}).get("members", []):
        manifest = ROOT / member / "Cargo.toml"
        if not manifest.is_file():
            raise SystemExit(f"workspace member manifest missing: {manifest}")
        manifests.append(manifest)
    return sorted(manifests)


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


def check_manifest(manifest: dict[str, Any]) -> list[Check]:
    version = str(manifest.get("product_version", ""))
    tag = str(manifest.get("product_tag", ""))
    return [
        Check(
            "release-manifest-schema",
            manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION,
            f"schema_version={manifest.get('schema_version')!r}",
        ),
        Check("product-version-semver", SEMVER_RE.fullmatch(version) is not None, f"product_version={version!r}"),
        Check("product-tag-matches-version", tag == f"v{version}", f"product_tag={tag!r}, expected='v{version}'"),
        Check(
            "real-publishing-disabled",
            manifest.get("release_mode") == "pre-publication"
            and manifest.get("rust", {}).get("publish") is False
            and manifest.get("python", {}).get("publish") is False
            and manifest.get("binaries", {}).get("publish") is False
            and manifest.get("github_release", {}).get("publish") is False,
            "release manifest keeps real publishing disabled",
        ),
    ]


def check_rust_versions(manifest: dict[str, Any]) -> list[Check]:
    product_version = str(manifest["product_version"])
    expected_crates = set(manifest.get("rust", {}).get("crates", []))
    binary_crate = manifest.get("rust", {}).get("binary_crate")
    manifests = workspace_member_manifests()
    by_name = {package_name(path): path for path in manifests}
    checks = [
        Check(
            "rust-crate-set",
            set(by_name) == expected_crates,
            f"workspace={sorted(by_name)}, release_manifest={sorted(expected_crates)}",
        ),
        Check("rust-binary-crate", binary_crate in by_name, f"binary_crate={binary_crate!r}"),
    ]
    for name, path in sorted(by_name.items()):
        version = package_version(path)
        checks.append(Check(f"rust-crate-version:{name}", version == product_version, f"{path.relative_to(ROOT)} version={version!r}"))
        document = load_toml(path)
        for section, dependencies in dependency_sections(document):
            for dep_name, dep_value in dependencies.items():
                if not isinstance(dep_value, dict) or "path" not in dep_value:
                    continue
                dep_manifest = (path.parent / str(dep_value["path"]) / "Cargo.toml").resolve()
                if not dep_manifest.is_file() or ROOT not in dep_manifest.parents:
                    continue
                dep_version = package_version(dep_manifest)
                declared = dep_value.get("version")
                checks.append(
                    Check(
                        f"rust-internal-dependency-version:{name}:{dep_name}",
                        declared == dep_version == product_version,
                        f"{section}.{dep_name} version={declared!r}, dependency package version={dep_version!r}",
                    )
                )
    return checks


def check_python_version(manifest: dict[str, Any]) -> list[Check]:
    pyproject = load_toml(ROOT / "sdk" / "python" / "pyproject.toml")
    project = pyproject.get("project", {})
    expected_name = manifest.get("python", {}).get("package")
    product_version = str(manifest["product_version"])
    return [
        Check("python-package-name", project.get("name") == expected_name, f"name={project.get('name')!r}"),
        Check("python-package-version", project.get("version") == product_version, f"version={project.get('version')!r}"),
        Check(
            "python-publishing-disabled",
            pyproject.get("tool", {}).get("permeantos", {}).get("release", {}).get("publish") is False,
            "tool.permeantos.release.publish is false",
        ),
    ]


def check_binary_identity(manifest: dict[str, Any]) -> list[Check]:
    binary_package = manifest.get("binaries", {}).get("package")
    rust_binary = manifest.get("rust", {}).get("binary_crate")
    archive_prefix = manifest.get("binaries", {}).get("archive_prefix")
    return [
        Check("binary-package-matches-rust", binary_package == rust_binary, f"binary package={binary_package!r}, rust binary={rust_binary!r}"),
        Check("binary-archive-prefix", archive_prefix == "permeantos", f"archive_prefix={archive_prefix!r}"),
    ]


def check_release_version_arg(manifest: dict[str, Any], release_version: str | None, release_kind: str) -> list[Check]:
    if release_version is None:
        return [Check("release-version-argument", True, "not provided; manifest consistency only")]
    match = TAG_RE.fullmatch(release_version)
    checks = [
        Check("release-version-format", match is not None, f"release_version={release_version!r}"),
    ]
    if match is None:
        return checks
    if release_kind == "product":
        expected = str(manifest["product_tag"])
        checks.append(Check("product-release-tag", release_version == expected, f"release_version={release_version!r}, expected={expected!r}"))
    elif release_kind == "milestone":
        checks.append(Check("milestone-release-tag", True, f"{release_version!r} accepted as a non-publishing milestone tag"))
    else:
        checks.append(Check("release-kind", release_kind == "manifest-only", f"release_kind={release_kind!r}"))
    return checks


def build_report(release_version: str | None, release_kind: str) -> dict[str, Any]:
    manifest = load_toml(MANIFEST_PATH)
    checks = [
        *check_manifest(manifest),
        *check_rust_versions(manifest),
        *check_python_version(manifest),
        *check_binary_identity(manifest),
        *check_release_version_arg(manifest, release_version, release_kind),
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "product_name": manifest.get("product_name"),
        "product_version": manifest.get("product_version"),
        "product_tag": manifest.get("product_tag"),
        "release_kind": release_kind,
        "release_version": release_version,
        "publishing_enabled": False,
        "checks": [check.to_json() for check in checks],
    }
    report["ok"] = all(check["ok"] for check in report["checks"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-version", help="Optional release tag, for example v0.1.0 or v0.1.30-platform.")
    parser.add_argument(
        "--release-kind",
        choices=("manifest-only", "milestone", "product"),
        default="manifest-only",
        help="Use product to require --release-version to match release.toml exactly.",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.release_kind == "product" and not args.release_version:
        raise SystemExit("--release-kind product requires --release-version")
    report = build_report(args.release_version, args.release_kind)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Emit the PermeantOS real-release plan from release.toml.

This is a planning/reporting gate, not a publisher. It gives CI and reviewers a
single source of truth for product tag, artifact targets, protected
environments, required secrets, and Rust crate publish order before the guarded
real-release workflow runs any side-effecting step.
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


SCHEMA_VERSION = "permeantos-real-release-plan-v0"
MANIFEST_SCHEMA_VERSION = "permeantos-release-manifest-v0"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release.toml"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?(?:\+[0-9A-Za-z][0-9A-Za-z.-]*)?$")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("rb") as handle:
        return tomllib.load(handle)


def artifact_plan(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    binaries = manifest.get("binaries", {})
    artifacts = []
    for target in binaries.get("targets", []):
        is_macos = target.endswith("apple-darwin")
        artifacts.append(
            {
                "target": target,
                "archive_format": binaries.get("macos_archive_format" if is_macos else "linux_archive_format"),
                "signed": bool(is_macos),
                "notarized": bool(is_macos and binaries.get("macos_notarize") is True),
                "environment": binaries.get("macos_environment") if is_macos else None,
            }
        )
    return artifacts


def required_secrets(manifest: dict[str, Any]) -> list[str]:
    secrets: list[str] = []
    if any(target.endswith("apple-darwin") for target in manifest.get("binaries", {}).get("targets", [])):
        secrets.extend(
            [
                "APPLE_CERTIFICATE",
                "APPLE_CERTIFICATE_PASSWORD",
                "APPLE_SIGNING_IDENTITY",
                "APPLE_ID",
                "APPLE_PASSWORD",
                "APPLE_TEAM_ID",
            ]
        )
    if manifest.get("rust", {}).get("crates"):
        secrets.append("CARGO_REGISTRY_TOKEN")
    return secrets


def build_checks(manifest: dict[str, Any], release_version: str | None) -> list[Check]:
    version = str(manifest.get("product_version", ""))
    tag = str(manifest.get("product_tag", ""))
    rust_crates = manifest.get("rust", {}).get("crates", [])
    targets = manifest.get("binaries", {}).get("targets", [])
    artifacts = artifact_plan(manifest)
    macos_artifacts = [artifact for artifact in artifacts if artifact["target"].endswith("apple-darwin")]
    checks = [
        Check("release-manifest-schema", manifest.get("schema_version") == MANIFEST_SCHEMA_VERSION, f"schema_version={manifest.get('schema_version')!r}"),
        Check("product-version-semver", SEMVER_RE.fullmatch(version) is not None, f"product_version={version!r}"),
        Check("product-tag-matches-version", tag == f"v{version}", f"product_tag={tag!r}, expected='v{version}'"),
        Check("rust-publish-order-present", bool(rust_crates), f"{len(rust_crates)} Rust crates listed"),
        Check("rust-publish-environment", manifest.get("rust", {}).get("environment") == "crates-io", f"rust.environment={manifest.get('rust', {}).get('environment')!r}"),
        Check("binary-targets-present", bool(targets), f"targets={targets!r}"),
        Check("linux-target-present", "x86_64-unknown-linux-gnu" in targets, f"targets={targets!r}"),
        Check("macos-target-present", any(target.endswith("apple-darwin") for target in targets), f"targets={targets!r}"),
        Check("macos-zip-format", all(artifact["archive_format"] == "zip" for artifact in macos_artifacts), f"macos_artifacts={macos_artifacts!r}"),
        Check("macos-notarization", all(artifact["notarized"] is True for artifact in macos_artifacts), f"macos_artifacts={macos_artifacts!r}"),
        Check("macos-environment", manifest.get("binaries", {}).get("macos_environment") == "apple-notarization", f"macos_environment={manifest.get('binaries', {}).get('macos_environment')!r}"),
        Check("github-release-environment", manifest.get("github_release", {}).get("environment") == "github-release", f"github_release.environment={manifest.get('github_release', {}).get('environment')!r}"),
    ]
    if release_version is not None:
        checks.append(Check("release-version-matches-manifest", release_version == tag, f"release_version={release_version!r}, product_tag={tag!r}"))
    return checks


def build_report(release_version: str | None) -> dict[str, Any]:
    manifest = load_manifest()
    checks = build_checks(manifest, release_version)
    rust = manifest.get("rust", {})
    binaries = manifest.get("binaries", {})
    github_release = manifest.get("github_release", {})
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "product_name": manifest.get("product_name"),
        "product_version": manifest.get("product_version"),
        "product_tag": manifest.get("product_tag"),
        "release_version": release_version,
        "release_mode": manifest.get("release_mode"),
        "publishing_enabled": manifest.get("release_mode") == "production",
        "rust": {
            "publish": rust.get("publish"),
            "environment": rust.get("environment"),
            "publish_order": rust.get("crates", []),
        },
        "binaries": {
            "publish": binaries.get("publish"),
            "package": binaries.get("package"),
            "archive_prefix": binaries.get("archive_prefix"),
            "artifacts": artifact_plan(manifest),
        },
        "github_release": {
            "publish": github_release.get("publish"),
            "environment": github_release.get("environment"),
        },
        "required_environments": sorted(
            {
                item
                for item in [
                    binaries.get("macos_environment"),
                    rust.get("environment"),
                    github_release.get("environment"),
                ]
                if item
            }
        ),
        "required_secrets": required_secrets(manifest),
        "checks": [check.to_json() for check in checks],
    }
    report["ok"] = all(check["ok"] for check in report["checks"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-version", help="Optional product release tag to compare against release.toml.")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(args.release_version)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

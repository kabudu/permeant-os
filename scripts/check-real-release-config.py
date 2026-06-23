#!/usr/bin/env python3
"""Fail-closed gate for real PermeantOS publishing workflows.

The normal repository state is `pre-publication`; in that state this checker
returns a failing report and publishing workflows must stop before touching any
registry or GitHub Release API. A future real-release PR can flip only the
intended `release.toml` flags and this checker will make that intent explicit.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-real-release-config-v0"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "release.toml"


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


def check_flag(manifest: dict[str, Any], section: str, *, required: bool) -> Check:
    enabled = manifest.get(section, {}).get("publish")
    if not required:
        return Check(f"{section}-publish-requested", True, f"{section}.publish not requested")
    return Check(f"{section}-publish-enabled", enabled is True, f"{section}.publish={enabled!r}")


def build_report(release_version: str, require: list[str]) -> dict[str, Any]:
    manifest = load_manifest()
    product_tag = str(manifest.get("product_tag", ""))
    checks = [
        Check(
            "release-mode-production",
            manifest.get("release_mode") == "production",
            f"release_mode={manifest.get('release_mode')!r}",
        ),
        Check(
            "release-version-matches-manifest",
            release_version == product_tag,
            f"release_version={release_version!r}, product_tag={product_tag!r}",
        ),
        check_flag(manifest, "github_release", required="github-release" in require),
        check_flag(manifest, "binaries", required="binaries" in require),
        check_flag(manifest, "rust", required="rust" in require),
        check_flag(manifest, "python", required="python" in require),
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "release_version": release_version,
        "release_mode": manifest.get("release_mode"),
        "required_publish_targets": require,
        "publishing_enabled": all(check.ok for check in checks),
        "checks": [check.to_json() for check in checks],
    }
    report["ok"] = report["publishing_enabled"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-version", required=True)
    parser.add_argument(
        "--require",
        action="append",
        choices=("github-release", "binaries", "rust", "python"),
        default=[],
        help="Publishing target that must be enabled in release.toml. May be repeated.",
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report(args.release_version, args.require)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

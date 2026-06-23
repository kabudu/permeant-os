#!/usr/bin/env python3
"""Verify PermeantOS publishing policy and real-release gates."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-publishing-policy-v0"
ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs" / "publishing-policy.md"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
REAL_RELEASE_WORKFLOW = WORKFLOW_DIR / "real-release.yml"
FORBIDDEN_WORKFLOW_SNIPPETS = (
    "gh release create",
    "gh release upload",
    "cargo publish",
    "twine upload",
    "npm publish",
    "docker push",
)
REAL_RELEASE_GUARD_SNIPPETS = (
    "scripts/plan-real-release.py",
    "scripts/check-real-release-config.py",
    "environment: github-release",
    "environment: crates-io",
    "environment: apple-notarization",
)
REQUIRED_POLICY_HEADINGS = (
    "## Current Mode",
    "## Ownership",
    "## Credentials",
    "## Signing",
    "## Registry Publishing",
    "## Rollback",
    "## Current Enforcement",
)


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


def workspace_package_defaults() -> dict[str, Any]:
    workspace = load_toml(ROOT / "Cargo.toml")
    return workspace.get("workspace", {}).get("package", {})


def package_value(package: dict[str, Any], workspace_defaults: dict[str, Any], field: str) -> Any:
    value = package.get(field)
    if isinstance(value, dict) and value.get("workspace") is True:
        return workspace_defaults.get(field)
    return value


def check_policy_doc() -> list[Check]:
    manifest = load_toml(ROOT / "release.toml")
    release_mode = manifest.get("release_mode")
    if not POLICY_PATH.is_file():
        return [Check("publishing-policy-doc", False, f"missing {POLICY_PATH}")]
    text = POLICY_PATH.read_text(encoding="utf-8")
    checks = [
        Check("publishing-policy-schema", SCHEMA_VERSION in text, f"{SCHEMA_VERSION} documented"),
        Check(
            "publishing-mode-documented",
            f"The current mode is `{release_mode}`." in text,
            f"current mode is {release_mode}",
        ),
    ]
    for heading in REQUIRED_POLICY_HEADINGS:
        checks.append(Check(f"publishing-policy-heading:{heading.removeprefix('## ')}", heading in text, f"{heading} present"))
    return checks


def check_workflows() -> list[Check]:
    workflow_paths = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    checks: list[Check] = []
    real_release_text = REAL_RELEASE_WORKFLOW.read_text(encoding="utf-8") if REAL_RELEASE_WORKFLOW.is_file() else ""
    real_release_guarded = all(snippet in real_release_text for snippet in REAL_RELEASE_GUARD_SNIPPETS)
    for snippet in FORBIDDEN_WORKFLOW_SNIPPETS:
        offenders = []
        for path in workflow_paths:
            text = path.read_text(encoding="utf-8")
            if snippet not in text:
                continue
            if path == REAL_RELEASE_WORKFLOW and real_release_guarded:
                continue
            offenders.append(str(path.relative_to(ROOT)))
        detail = (
            f"{snippet!r} is absent from normal workflows; guarded real-release workflow exception is present"
            if not offenders
            else f"{snippet!r} appears in {offenders}"
        )
        checks.append(Check(f"workflow-forbids:{snippet}", not offenders, detail))
    checks.append(
        Check(
            "real-release-workflow-guarded",
            not real_release_text or real_release_guarded,
            "real-release workflow uses config gate and protected publishing environments",
        )
    )
    return checks


def check_cargo_publish_status() -> list[Check]:
    manifest = load_toml(ROOT / "release.toml")
    release_mode = manifest.get("release_mode")
    rust_publish_enabled = manifest.get("rust", {}).get("publish") is True
    release_crates = set(manifest.get("rust", {}).get("crates", []))
    defaults = workspace_package_defaults()
    checks: list[Check] = []
    for path in sorted((ROOT / "crates").glob("*/Cargo.toml")):
        package = load_toml(path).get("package", {})
        name = package.get("name", path.parent.name)
        publish = package_value(package, defaults, "publish")
        publishable = publish is not False
        if release_mode == "pre-publication":
            check_name = f"crate-publish-disabled:{name}"
            ok = publish is False
            detail = f"{path.relative_to(ROOT)} publish={publish!r}"
        elif release_mode == "production" and rust_publish_enabled and name in release_crates:
            check_name = f"crate-publish-enabled:{name}"
            ok = publishable
            detail = f"{path.relative_to(ROOT)} is publishable for production release"
        else:
            check_name = f"crate-publish-mode:{name}"
            ok = False
            detail = (
                f"unsupported release mode for {name}: release_mode={release_mode!r}, "
                f"rust.publish={manifest.get('rust', {}).get('publish')!r}"
            )
        checks.append(
            Check(
                check_name,
                ok,
                detail,
            )
        )
    return checks


def check_python_publish_disabled() -> list[Check]:
    pyproject = load_toml(ROOT / "sdk" / "python" / "pyproject.toml")
    release = pyproject.get("tool", {}).get("permeantos", {}).get("release", {})
    return [
        Check(
            "python-publish-disabled:permeantos",
            release.get("publish") is False,
            f"tool.permeantos.release.publish={release.get('publish')!r}",
        )
    ]


def build_report() -> dict[str, Any]:
    manifest = load_toml(ROOT / "release.toml")
    release_mode = manifest.get("release_mode")
    publishing_enabled = (
        release_mode == "production"
        and manifest.get("rust", {}).get("publish") is True
        and manifest.get("binaries", {}).get("publish") is True
        and manifest.get("github_release", {}).get("publish") is True
        and manifest.get("python", {}).get("publish") is False
    )
    checks = [
        *check_policy_doc(),
        *check_workflows(),
        *check_cargo_publish_status(),
        *check_python_publish_disabled(),
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "mode": release_mode,
        "publishing_enabled": publishing_enabled,
        "checks": [check.to_json() for check in checks],
    }
    report["ok"] = all(check["ok"] for check in report["checks"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    report = build_report()
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

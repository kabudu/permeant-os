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
FORBIDDEN_WORKFLOW_SNIPPETS = (
    "gh release create",
    "gh release upload",
    "cargo publish",
    "twine upload",
    "npm publish",
    "docker push",
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
    if not POLICY_PATH.is_file():
        return [Check("publishing-policy-doc", False, f"missing {POLICY_PATH}")]
    text = POLICY_PATH.read_text(encoding="utf-8")
    checks = [
        Check("publishing-policy-schema", SCHEMA_VERSION in text, f"{SCHEMA_VERSION} documented"),
        Check("publishing-mode-pre-publication", "The current mode is `pre-publication`." in text, "current mode is pre-publication"),
    ]
    for heading in REQUIRED_POLICY_HEADINGS:
        checks.append(Check(f"publishing-policy-heading:{heading.removeprefix('## ')}", heading in text, f"{heading} present"))
    return checks


def check_workflows() -> list[Check]:
    workflow_paths = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    workflow_text = "\n".join(path.read_text(encoding="utf-8") for path in workflow_paths)
    return [
        Check(
            f"workflow-forbids:{snippet}",
            snippet not in workflow_text,
            f"{snippet!r} is absent from current workflows",
        )
        for snippet in FORBIDDEN_WORKFLOW_SNIPPETS
    ]


def check_cargo_publish_disabled() -> list[Check]:
    defaults = workspace_package_defaults()
    checks: list[Check] = []
    for path in sorted((ROOT / "crates").glob("*/Cargo.toml")):
        package = load_toml(path).get("package", {})
        name = package.get("name", path.parent.name)
        publish = package_value(package, defaults, "publish")
        checks.append(
            Check(
                f"crate-publish-disabled:{name}",
                publish is False,
                f"{path.relative_to(ROOT)} publish={publish!r}",
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
    checks = [
        *check_policy_doc(),
        *check_workflows(),
        *check_cargo_publish_disabled(),
        *check_python_publish_disabled(),
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "mode": "pre-publication",
        "publishing_enabled": False,
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

#!/usr/bin/env python3
"""Check PermeantOS crate and SDK package publication readiness metadata.

This gate does not publish anything. It verifies that package metadata is
complete enough for release work and that package publishability matches the
current `release.toml` mode.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-package-readiness-v0"
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CARGO_PACKAGE_FIELDS = (
    "name",
    "version",
    "edition",
    "description",
    "license",
    "repository",
    "homepage",
    "readme",
)
REQUIRED_PYPROJECT_FIELDS = (
    "name",
    "version",
    "description",
    "readme",
    "requires-python",
    "license",
    "authors",
    "keywords",
    "classifiers",
    "dependencies",
    "urls",
)


@dataclass(frozen=True)
class PackageStatus:
    package_type: str
    name: str
    path: Path
    publish_enabled: bool
    status: str
    errors: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.package_type,
            "name": self.name,
            "path": str(self.path.relative_to(ROOT)),
            "publish_enabled": self.publish_enabled,
            "status": self.status,
            "errors": list(self.errors),
        }


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def workspace_package_defaults() -> dict[str, Any]:
    workspace = load_toml(ROOT / "Cargo.toml")
    return workspace.get("workspace", {}).get("package", {})


def release_manifest() -> dict[str, Any]:
    return load_toml(ROOT / "release.toml")


def package_value(package: dict[str, Any], workspace_defaults: dict[str, Any], field: str) -> Any:
    value = package.get(field)
    if isinstance(value, dict) and value.get("workspace") is True:
        return workspace_defaults.get(field)
    return value


def check_cargo_package(path: Path, workspace_defaults: dict[str, Any], manifest: dict[str, Any]) -> PackageStatus:
    document = load_toml(path)
    package = document.get("package", {})
    name = str(package.get("name", path.parent.name))
    errors: list[str] = []

    for field in REQUIRED_CARGO_PACKAGE_FIELDS:
        value = package_value(package, workspace_defaults, field)
        if value in (None, "", []):
            errors.append(f"missing package.{field}")

    readme = package_value(package, workspace_defaults, "readme")
    if isinstance(readme, str) and not (ROOT / readme).is_file():
        errors.append(f"package.readme does not exist: {readme}")

    license_value = package_value(package, workspace_defaults, "license")
    if license_value != "Apache-2.0":
        errors.append("package.license must be Apache-2.0")

    repository = package_value(package, workspace_defaults, "repository")
    if repository != "https://github.com/kabudu/permeant-os":
        errors.append("package.repository must point at the canonical repository")

    homepage = package_value(package, workspace_defaults, "homepage")
    if homepage != "https://www.permeantos.org":
        errors.append("package.homepage must point at the public website")

    release_mode = manifest.get("release_mode")
    rust_publish_enabled = manifest.get("rust", {}).get("publish") is True
    release_crates = set(manifest.get("rust", {}).get("crates", []))
    publish = package.get("publish")
    publish_enabled = publish is not False
    if release_mode == "pre-publication":
        if publish_enabled:
            errors.append("package.publish must be false until the real-release gate enables crate publishing")
        status = "ready-gated"
    elif release_mode == "production" and rust_publish_enabled and name in release_crates:
        if not publish_enabled:
            errors.append("package.publish must be publishable for crates included in the production release")
        status = "ready-to-publish"
    else:
        errors.append(f"unsupported release.toml publish mode for {name}: release_mode={release_mode!r}")
        status = "failed"

    return PackageStatus(
        package_type="cargo",
        name=name,
        path=path,
        publish_enabled=publish_enabled,
        status=status if not errors else "failed",
        errors=tuple(errors),
    )


def check_python_sdk(path: Path) -> PackageStatus:
    document = load_toml(path)
    project = document.get("project", {})
    errors: list[str] = []

    for field in REQUIRED_PYPROJECT_FIELDS:
        value = project.get(field)
        if value in (None, "", []):
            errors.append(f"missing project.{field}")

    readme = project.get("readme")
    if isinstance(readme, str) and not (path.parent / readme).is_file():
        errors.append(f"project.readme does not exist: {readme}")

    license_value = project.get("license", {})
    if not isinstance(license_value, dict) or license_value.get("text") != "Apache-2.0":
        errors.append("project.license.text must be Apache-2.0")

    urls = project.get("urls", {})
    if urls.get("Repository") != "https://github.com/kabudu/permeant-os":
        errors.append("project.urls.Repository must point at the canonical repository")
    if urls.get("Documentation") != "https://www.permeantos.org/docs/":
        errors.append("project.urls.Documentation must point at the public docs hub")

    release = document.get("tool", {}).get("permeantos", {}).get("release", {})
    publish_enabled = release.get("publish") is not False
    if publish_enabled:
        errors.append("tool.permeantos.release.publish must be false until the real-release gate enables package publishing")
    if not release.get("publish_reason"):
        errors.append("tool.permeantos.release.publish_reason is required")

    return PackageStatus(
        package_type="python",
        name=str(project.get("name", path.parent.name)),
        path=path,
        publish_enabled=publish_enabled,
        status="ready-gated" if not errors else "failed",
        errors=tuple(errors),
    )


def build_report() -> dict[str, Any]:
    workspace_defaults = workspace_package_defaults()
    manifest = release_manifest()
    package_paths = sorted((ROOT / "crates").glob("*/Cargo.toml"))
    statuses = [check_cargo_package(path, workspace_defaults, manifest) for path in package_paths]
    statuses.append(check_python_sdk(ROOT / "sdk" / "python" / "pyproject.toml"))

    ok = all(status.status in {"ready-gated", "ready-to-publish"} for status in statuses)
    release_mode = manifest.get("release_mode")
    crate_publish_requested = release_mode == "production" and manifest.get("rust", {}).get("publish") is True
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready-to-publish" if ok and crate_publish_requested else "ready-gated" if ok else "failed",
        "release_mode": release_mode,
        "publishing": {
            "crates_published": False,
            "python_packages_published": False,
            "real_release_gate_required": True,
            "crate_publish_requested": crate_publish_requested,
        },
        "packages": [status.to_json() for status in statuses],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, help="Optional path to write the readiness report JSON.")
    args = parser.parse_args()

    report = build_report()
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0 if report["status"] in {"ready-gated", "ready-to-publish"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

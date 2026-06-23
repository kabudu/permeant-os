from __future__ import annotations

import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-crate-packaging.py"


def run_packaging_check(*args: str):
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_crate_packaging_gate_validates_versioned_path_dependencies():
    result = run_packaging_check("--skip-cargo")

    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["schema_version"] == "permeantos-crate-packaging-v0"
    assert report["publishing_enabled"] is False
    assert report["cargo_package_verify"] == "direct-for-crates-without-internal-path-dependencies"
    assert report["downstream_package_verify"] == "deferred-until-internal-crates-are-published"

    packages = {package["name"] for package in report["packages"]}
    assert "usxf-core" in packages
    assert "permeant-cli" in packages
    assert "qatq" not in packages

    path_dependency_checks = [
        check for check in report["checks"] if check["name"].startswith("path-dependency-version:")
    ]
    assert path_dependency_checks
    assert all(check["ok"] for check in path_dependency_checks)


def test_pr_ci_runs_crate_packaging_gate():
    workflow = (ROOT / ".github" / "workflows" / "pr-ci.yml").read_text()

    assert "Verify crate package dry run" in workflow
    assert "scripts/check-crate-packaging.py --json-out /tmp/permeantos-crate-packaging.json" in workflow


def test_release_validation_uploads_crate_packaging_report():
    workflow = (ROOT / ".github" / "workflows" / "release-validation.yml").read_text()

    assert "Check Rust crate packaging dry run" in workflow
    assert "scripts/check-crate-packaging.py --json-out dist/release/crate-packaging.json" in workflow
    assert "dist/release/crate-packaging.json" in workflow

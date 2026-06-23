from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLANNER = ROOT / "scripts" / "plan-real-release.py"


def run_planner(*args: str):
    return subprocess.run(
        [sys.executable, str(PLANNER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_real_release_plan_reports_targets_environments_and_publish_order():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = pathlib.Path(tmpdir) / "real-release-plan.json"

        result = run_planner("--release-version", "v0.1.0", "--json-out", str(report_path))

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-real-release-plan-v0"
        assert report["ok"] is True
        assert report["product_tag"] == "v0.1.0"
        assert report["publishing_enabled"] is True
        assert report["rust"]["publish"] is True
        assert report["binaries"]["publish"] is True
        assert report["github_release"]["publish"] is True
        assert report["required_environments"] == ["apple-notarization", "crates-io", "github-release"]
        assert "APPLE_CERTIFICATE" in report["required_secrets"]
        assert "CARGO_REGISTRY_TOKEN" in report["required_secrets"]
        assert report["rust"]["publish_order"] == [
            "usxf-core",
            "permeant-transport",
            "permeant-transpiler",
            "permeant-extractor",
            "permeant-injector",
            "permeant-orchestrator",
            "permeant-qatq-migration",
            "permeant-cli",
        ]
        artifacts = {artifact["target"]: artifact for artifact in report["binaries"]["artifacts"]}
        assert artifacts["x86_64-unknown-linux-gnu"]["archive_format"] == "tar.gz"
        assert artifacts["aarch64-apple-darwin"]["archive_format"] == "zip"
        assert artifacts["aarch64-apple-darwin"]["notarized"] is True
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["release-version-matches-manifest"]["ok"] is True
        assert checks["macos-notarization"]["ok"] is True


def test_real_release_plan_rejects_mismatched_product_tag():
    result = run_planner("--release-version", "v0.1.99-test")

    assert result.returncode != 0
    report = json.loads(result.stdout)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["release-version-matches-manifest"]["ok"] is False

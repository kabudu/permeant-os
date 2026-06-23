from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-release-version.py"


def run_checker(*args: str):
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_manifest_versions_are_consistent():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = pathlib.Path(tmpdir) / "release-version.json"

        result = run_checker("--json-out", str(report_path))

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-release-version-consistency-v0"
        assert report["ok"] is True
        assert report["product_version"] == "0.1.0"
        assert report["product_tag"] == "v0.1.0"
        assert report["publishing_enabled"] is True
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["release-manifest-schema"]["ok"] is True
        assert checks["release-publishing-mode-valid"]["ok"] is True
        assert checks["rust-crate-set"]["ok"] is True
        assert checks["python-package-version"]["ok"] is True
        assert checks["binary-package-matches-rust"]["ok"] is True
        assert checks["release-version-argument"]["ok"] is True


def test_product_release_tag_must_match_manifest():
    result = run_checker("--release-version", "v0.1.0", "--release-kind", "product")

    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["product-release-tag"]["ok"] is True


def test_product_release_tag_rejects_mismatched_version():
    result = run_checker("--release-version", "v0.1.99-test", "--release-kind", "product")

    assert result.returncode != 0
    report = json.loads(result.stdout)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["product-release-tag"]["ok"] is False


def test_milestone_release_tag_accepts_roadmap_suffix_in_current_mode():
    result = run_checker("--release-version", "v0.1.99-test", "--release-kind", "milestone")

    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["milestone-release-tag"]["ok"] is True
    assert report["publishing_enabled"] is True


def test_release_version_gate_is_wired_into_ci_and_release_validation():
    pr_workflow = (ROOT / ".github" / "workflows" / "pr-ci.yml").read_text()
    release_workflow = (ROOT / ".github" / "workflows" / "release-validation.yml").read_text()

    assert "scripts/check-release-version.py --json-out /tmp/permeantos-release-version.json" in pr_workflow
    assert "scripts/check-release-version.py --release-version" in release_workflow
    assert "--release-version-consistency dist/release/release-version.json" in release_workflow
    assert "dist/release/release-version.json" in release_workflow

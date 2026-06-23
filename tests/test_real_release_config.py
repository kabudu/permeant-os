from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-real-release-config.py"


def run_checker(*args: str):
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_real_release_config_passes_for_guarded_production_targets():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = pathlib.Path(tmpdir) / "real-release-config.json"

        result = run_checker(
            "--release-version",
            "v0.1.0",
            "--require",
            "github-release",
            "--require",
            "binaries",
            "--require",
            "rust",
            "--json-out",
            str(report_path),
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-real-release-config-v0"
        assert report["ok"] is True
        assert report["publishing_enabled"] is True
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["release-version-matches-manifest"]["ok"] is True
        assert checks["release-mode-production"]["ok"] is True
        assert checks["github_release-publish-enabled"]["ok"] is True
        assert checks["binaries-publish-enabled"]["ok"] is True
        assert checks["rust-publish-enabled"]["ok"] is True


def test_real_release_config_rejects_mismatched_product_tag():
    result = run_checker(
        "--release-version",
        "v0.1.1",
        "--require",
        "github-release",
        "--require",
        "binaries",
        "--require",
        "rust",
    )

    assert result.returncode != 0
    report = json.loads(result.stdout)
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["release-version-matches-manifest"]["ok"] is False

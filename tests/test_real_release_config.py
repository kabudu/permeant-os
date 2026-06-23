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


def test_real_release_config_fails_closed_in_pre_publication_mode():
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

        assert result.returncode != 0
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-real-release-config-v0"
        assert report["ok"] is False
        assert report["publishing_enabled"] is False
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["release-version-matches-manifest"]["ok"] is True
        assert checks["release-mode-production"]["ok"] is False
        assert checks["github_release-publish-enabled"]["ok"] is False
        assert checks["binaries-publish-enabled"]["ok"] is False
        assert checks["rust-publish-enabled"]["ok"] is False

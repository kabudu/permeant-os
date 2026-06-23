from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-package-readiness.py"

EXPECTED_PACKAGES = {
    "permeant-cli",
    "permeant-extractor",
    "permeant-injector",
    "permeant-orchestrator",
    "permeant-qatq-migration",
    "permeant-transpiler",
    "permeant-transport",
    "permeantos",
    "usxf-core",
}


def test_package_readiness_report_is_complete_and_gated():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = pathlib.Path(tmpdir) / "package-readiness.json"
        result = subprocess.run(
            [str(CHECKER), "--json-out", str(report_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-package-readiness-v0"
        assert report["status"] == "ready-to-publish"
        assert report["release_mode"] == "production"
        assert report["publishing"] == {
            "crates_published": False,
            "python_packages_published": False,
            "real_release_gate_required": True,
            "crate_publish_requested": True,
        }

        packages = {package["name"]: package for package in report["packages"]}
        assert set(packages) == EXPECTED_PACKAGES

        for name, package in packages.items():
            if name == "permeantos":
                assert package["status"] == "ready-gated"
                assert package["publish_enabled"] is False
            else:
                assert package["status"] == "ready-to-publish"
                assert package["publish_enabled"] is True
            assert package["errors"] == []


def test_package_readiness_schema_is_documented():
    policy = (ROOT / "docs" / "versioning-policy.md").read_text()
    docs = (ROOT / "docs" / "crate-and-sdk-publication-plan.md").read_text()

    assert "permeantos-package-readiness-v0" in policy
    assert "permeantos-package-readiness-v0" in docs
    assert "scripts/check-package-readiness.py" in docs

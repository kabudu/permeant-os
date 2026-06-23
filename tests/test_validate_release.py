from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build-release-artifacts.py"
READINESS = ROOT / "scripts" / "check-package-readiness.py"
VALIDATOR = ROOT / "scripts" / "validate-release.py"


def make_artifacts(version: str, temp: pathlib.Path) -> pathlib.Path:
    binary = temp / "permeant-cli"
    binary.write_text("#!/bin/sh\necho permeant\n", encoding="utf-8")
    binary.chmod(0o755)
    out_dir = temp / "release"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--version",
            version,
            "--target",
            "test-target",
            "--out-dir",
            str(out_dir),
            "--skip-build",
            "--binary-path",
            str(binary),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return out_dir


def make_package_readiness(temp: pathlib.Path) -> pathlib.Path:
    report = temp / "package-readiness.json"
    result = subprocess.run(
        [sys.executable, str(READINESS), "--json-out", str(report)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return report


def make_crate_packaging(temp: pathlib.Path) -> pathlib.Path:
    report = temp / "crate-packaging.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "permeantos-crate-packaging-v0",
                "ok": True,
                "publishing_enabled": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def make_release_version_consistency(temp: pathlib.Path) -> pathlib.Path:
    report = temp / "release-version.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "permeantos-release-version-consistency-v0",
                "ok": True,
                "publishing_enabled": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def run_validator(*args: str):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_validator_accepts_candidate_artifacts_with_unreleased_changelog():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = pathlib.Path(tmpdir)
        version = "v0.1.99-test"
        artifact_dir = make_artifacts(version, temp)
        package_readiness = make_package_readiness(temp)
        crate_packaging = make_crate_packaging(temp)
        release_version_consistency = make_release_version_consistency(temp)
        report_path = temp / "release-validation.json"

        result = run_validator(
            "--version",
            version,
            "--artifact-dir",
            str(artifact_dir),
            "--package-readiness",
            str(package_readiness),
            "--crate-packaging",
            str(crate_packaging),
            "--release-version-consistency",
            str(release_version_consistency),
            "--allow-unreleased-changelog",
            "--json-out",
            str(report_path),
        )

        assert result.returncode == 0, result.stderr + result.stdout
        report = json.loads(report_path.read_text())
        assert report["schema_version"] == "permeantos-release-validation-v0"
        assert report["ok"] is True
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["changelog-promoted"]["ok"] is True
        assert checks["release-manifest-schema"]["ok"] is True
        assert checks["package-publishing-disabled"]["ok"] is True
        assert checks["crate-packaging-ok"]["ok"] is True
        assert checks["crate-packaging-publishing-disabled"]["ok"] is True
        assert checks["release-version-consistency-ok"]["ok"] is True
        assert checks["release-version-publishing-disabled"]["ok"] is True


def test_release_validator_requires_changelog_promotion_for_strict_tag_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = pathlib.Path(tmpdir)
        version = "v0.1.99-test"
        artifact_dir = make_artifacts(version, temp)

        result = run_validator("--version", version, "--artifact-dir", str(artifact_dir))

        assert result.returncode != 0
        report = json.loads(result.stdout)
        checks = {check["name"]: check for check in report["checks"]}
        assert checks["changelog-promoted"]["ok"] is False


def test_release_validator_rejects_checksum_drift():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = pathlib.Path(tmpdir)
        version = "v0.1.99-test"
        artifact_dir = make_artifacts(version, temp)
        checksum_path = artifact_dir / "checksums.txt"
        checksum_path.write_text("0" * 64 + "  " + next(artifact_dir.glob("*.tar.gz")).name + "\n", encoding="utf-8")

        result = run_validator(
            "--version",
            version,
            "--artifact-dir",
            str(artifact_dir),
            "--allow-unreleased-changelog",
        )

        assert result.returncode != 0
        report = json.loads(result.stdout)
        checksum_checks = [check for check in report["checks"] if check["name"].startswith("archive-checksum-sha:")]
        assert checksum_checks
        assert checksum_checks[0]["ok"] is False

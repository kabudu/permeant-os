from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build-release-artifacts.py"


def run_builder(*args: str):
    return subprocess.run(
        [str(BUILDER), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_release_artifact_builder_emits_manifest_checksums_and_archive():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = pathlib.Path(tmpdir)
        binary = temp / "permeant-cli"
        binary.write_text("#!/bin/sh\necho permeant\n", encoding="utf-8")
        binary.chmod(0o755)
        out_dir = temp / "out"

        result = run_builder(
            "--version",
            "v0.1.99-test",
            "--target",
            "test-target",
            "--out-dir",
            str(out_dir),
            "--skip-build",
            "--binary-path",
            str(binary),
        )

        assert result.returncode == 0, result.stderr
        manifest = json.loads((out_dir / "release-manifest.json").read_text())
        assert manifest["schema_version"] == "permeantos-release-artifacts-v0"
        assert manifest["version"] == "v0.1.99-test"
        assert manifest["package"] == "permeant-cli"
        assert manifest["publishing"]["github_release_created"] is False
        assert manifest["publishing"]["crates_published"] is False
        assert len(manifest["artifacts"]) == 1

        artifact = manifest["artifacts"][0]
        archive = out_dir / artifact["archive"]
        assert archive.is_file()
        expected_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        assert artifact["archive_sha256"] == expected_sha
        assert artifact["archive_bytes"] == archive.stat().st_size
        assert (out_dir / "checksums.txt").read_text() == f"{expected_sha}  {archive.name}\n"

        with tarfile.open(archive, "r:gz") as tar:
            raw_names = tar.getnames()
            names = set(raw_names)
        root = "permeantos-v0.1.99-test-test-target"
        assert len(raw_names) == len(names)
        assert f"{root}/bin/permeant-cli" in names
        assert f"{root}/INSTALL.md" in names
        assert f"{root}/LICENSE" in names
        with tarfile.open(archive, "r:gz") as tar:
            install = tar.extractfile(f"{root}/INSTALL.md")
            assert install is not None
            install_text = install.read().decode("utf-8")
        assert "permeant-cli starter-demo --seq-len 128 --out-dir .permeant-demo" in install_text


def test_release_artifact_builder_rejects_unsafe_version_components():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = pathlib.Path(tmpdir)
        binary = temp / "permeant-cli"
        binary.write_text("bin", encoding="utf-8")
        result = run_builder(
            "--version",
            "../bad",
            "--target",
            "test-target",
            "--out-dir",
            str(temp / "out"),
            "--skip-build",
            "--binary-path",
            str(binary),
        )

        assert result.returncode != 0
        assert "version must match" in result.stderr


def test_release_artifact_builder_can_emit_zip_archive():
    with tempfile.TemporaryDirectory() as tmpdir:
        temp = pathlib.Path(tmpdir)
        binary = temp / "permeant-cli"
        binary.write_text("#!/bin/sh\necho permeant\n", encoding="utf-8")
        binary.chmod(0o755)
        out_dir = temp / "out"

        result = run_builder(
            "--version",
            "v0.1.99-test",
            "--target",
            "aarch64-apple-darwin",
            "--archive-format",
            "zip",
            "--out-dir",
            str(out_dir),
            "--skip-build",
            "--binary-path",
            str(binary),
        )

        assert result.returncode == 0, result.stderr
        manifest = json.loads((out_dir / "release-manifest.json").read_text())
        artifact = manifest["artifacts"][0]
        archive = out_dir / artifact["archive"]
        assert archive.suffix == ".zip"
        assert artifact["archive_format"] == "zip"
        assert artifact["signed"] is False
        with zipfile.ZipFile(archive) as zip_file:
            names = set(zip_file.namelist())
            install_text = zip_file.read("permeantos-v0.1.99-test-aarch64-apple-darwin/INSTALL.md").decode("utf-8")
        assert "permeantos-v0.1.99-test-aarch64-apple-darwin/bin/permeant-cli" in names
        assert "permeant-cli starter-demo --seq-len 128 --out-dir .permeant-demo" in install_text


def test_release_validation_workflow_builds_validates_and_uploads_reports():
    workflow = (ROOT / ".github" / "workflows" / "release-validation.yml").read_text()

    assert "scripts/build-release-artifacts.py" in workflow
    assert "scripts/check-package-readiness.py --json-out dist/release/package-readiness.json" in workflow
    assert "scripts/check-crate-packaging.py --json-out dist/release/crate-packaging.json" in workflow
    assert "scripts/check-release-version.py --release-version" in workflow
    assert "scripts/validate-release.py" in workflow
    assert "--package-readiness dist/release/package-readiness.json" in workflow
    assert "--crate-packaging dist/release/crate-packaging.json" in workflow
    assert "--release-version-consistency dist/release/release-version.json" in workflow
    assert "dist/release/release-version.json" in workflow
    assert "dist/release/release-validation.json" in workflow
    assert "actions/upload-artifact@v7.0.1" in workflow
    assert "contents: read" in workflow
    assert "gh release" not in workflow
    assert "cargo publish" not in workflow
    assert "twine upload" not in workflow


def test_pr_ci_runs_starter_migration_demo():
    workflow = (ROOT / ".github" / "workflows" / "pr-ci.yml").read_text()

    assert "Run starter migration demo" in workflow
    assert "cargo run --locked --bin permeant-cli -- starter-demo" in workflow
    assert "--out-dir /tmp/permeantos-starter-demo" in workflow


def test_real_release_workflow_is_manual_guarded_and_notarizes_macos():
    workflow = (ROOT / ".github" / "workflows" / "real-release.yml").read_text()

    assert "workflow_dispatch:" in workflow
    assert "scripts/check-real-release-config.py" in workflow
    assert "--release-kind product" in workflow
    assert "environment: apple-notarization" in workflow
    assert "APPLE_CERTIFICATE" in workflow
    assert "security import" in workflow
    assert "--archive-format zip" in workflow
    assert "--codesign-identity" in workflow
    assert "xcrun notarytool submit" in workflow
    assert "environment: github-release" in workflow
    assert "gh release create" in workflow
    assert "environment: crates-io" in workflow
    assert "cargo publish --locked -p" in workflow

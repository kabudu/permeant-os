from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import tarfile
import tempfile


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

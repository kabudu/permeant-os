import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


RESTORE = Path(__file__).resolve().parents[1] / "scripts" / "restore-zstd-checkpoint.py"
pytestmark = pytest.mark.skipif(not shutil.which("zstd"), reason="Zstd CLI is required")


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("change,expected_error", [
    ("valid", ""),
    ("size", "compressed checkpoint size mismatch"),
    ("archive_digest", "compressed checkpoint digest mismatch"),
    ("truncated_frame", "Zstd checkpoint decode failed"),
    ("excess_output", "decoded checkpoint exceeds trusted size"),
    ("short_output", "restored checkpoint size or digest mismatch"),
    ("plaintext_digest", "restored checkpoint size or digest mismatch"),
])
def test_restore_rejects_untrusted_artifacts_without_publishing(tmp_path, change, expected_error):
    data = b'{"checkpoint":"same byte-for-byte transfer"}' * 128
    artifact = subprocess.run(
        ["zstd", "-q", "-3", "-c"], input=data, capture_output=True, check=True, timeout=10,
    ).stdout
    if change == "truncated_frame":
        artifact = artifact[:-2]
    archive = tmp_path / "checkpoint.zst"
    archive.write_bytes(artifact)
    destination = tmp_path / "verified.json"
    args = [
        sys.executable, str(RESTORE), str(archive), str(destination),
        str(len(artifact) + (change == "size")),
        sha(b"wrong artifact") if change == "archive_digest" else sha(artifact),
        str(len(data) - (change == "excess_output") + (change == "short_output")),
        sha(b"wrong plaintext") if change == "plaintext_digest" else sha(data),
    ]
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if expected_error:
        assert result.returncode != 0
        assert expected_error in result.stderr
        assert not destination.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert destination.read_bytes() == data
        assert destination.stat().st_mode & 0o077 == 0
    assert list(tmp_path.glob(".checkpoint-*")) == []

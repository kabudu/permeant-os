import json
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/live-recovery-gateway.py"


def test_recovery_lease_transition_and_exactly_once_task(tmp_path):
    database = tmp_path / "gateway.sqlite"

    def call(action, **request):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(database), action],
            input=json.dumps(request), text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    assert call("init", source="source-fixture", target="target-fixture") == {"epoch": 1}
    assert call("write", lease="target-fixture")["status"] == "lease_rejected"
    assert call("write", lease="source-fixture", id="source-before-alert", token=0)["status"] == "completed"
    assert call("fence") == {"epoch": 2}
    assert call("write", lease="source-fixture", id="recovered-task", token=123)["status"] == "lease_rejected"
    assert call("write", lease="target-fixture", id="recovered-task", token=123)["status"] == "lease_rejected"
    stale = subprocess.run(
        [sys.executable, str(SCRIPT), str(database), "activate"],
        input='{"epoch":1}', text=True, capture_output=True, check=False,
    )
    assert stale.returncode != 0
    assert call("write", lease="target-fixture", id="recovered-task", token=123)["status"] == "lease_rejected"
    assert call("activate", epoch=2) == {"status": "active", "epoch": 2}
    assert call("write", lease="source-fixture", id="recovered-task", token=123)["status"] == "lease_rejected"
    completion = call("write", lease="target-fixture", id="recovered-task", token=456)
    assert completion["status"] == "completed"
    assert call("activate", epoch=2) == {"status": "active", "epoch": 2}
    retry = call("write", lease="target-fixture", id="recovered-task", token=789)
    assert retry["status"] == "duplicate"
    assert retry["committed_token"] == completion["committed_token"] == 456
    assert retry["committed_unix_ns"] == completion["committed_unix_ns"]
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT id, token FROM tasks ORDER BY id").fetchall() == [
            ("recovered-task", 456), ("source-before-alert", 0),
        ]

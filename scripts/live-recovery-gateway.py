"""Disposable off-origin write authority for the AWS recovery drill."""

import hashlib
import hmac
import json
import sqlite3
import sys
import time
from pathlib import Path


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def execute(database, action, request):
    if action == "init":
        database.execute("CREATE TABLE authority (epoch INTEGER, source TEXT, target TEXT, active INTEGER NOT NULL)")
        database.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, token INTEGER, completed_ns INTEGER)")
        database.execute("INSERT INTO authority VALUES (1, ?, ?, 0)", (
            digest(request["source"]), digest(request["target"]),
        ))
        return {"epoch": 1}
    epoch, source, target, active = database.execute("SELECT * FROM authority").fetchone()
    if action == "fence":
        if epoch != 1:
            raise ValueError("source lease already fenced")
        database.execute("UPDATE authority SET epoch = 2")
        return {"epoch": 2}
    if action == "activate":
        if epoch != 2 or request["epoch"] != epoch:
            raise ValueError("activation requires the current fenced epoch")
        database.execute("UPDATE authority SET active = 1")
        return {"status": "active", "epoch": epoch}
    if action != "write":
        raise ValueError("unknown action")
    if (epoch == 2 and not active) or not hmac.compare_digest(digest(request["lease"]), source if epoch == 1 else target):
        return {"status": "lease_rejected", "epoch": epoch}
    if request["id"] != ("source-before-alert" if epoch == 1 else "recovered-task"):
        raise ValueError("unexpected task ID")
    inserted = database.execute(
        "INSERT OR IGNORE INTO tasks VALUES (?, ?, ?)",
        (request["id"], request["token"], time.time_ns()),
    ).rowcount
    token, committed_ns = database.execute(
        "SELECT token, completed_ns FROM tasks WHERE id = ?", (request["id"],),
    ).fetchone()
    database.commit()
    return {"status": "completed" if inserted else "duplicate", "epoch": epoch,
            "committed_token": token, "committed_unix_ns": committed_ns,
            "observed_unix_ns": time.time_ns()}


def main():
    path, action = sys.argv[1:]
    request = json.load(sys.stdin)
    if action != "init" and not Path(path).is_file():
        raise SystemExit("missing gateway database")
    with sqlite3.connect(path, timeout=10, isolation_level=None) as database:
        database.execute("BEGIN IMMEDIATE")
        result = execute(database, action, request)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Watch the staged import directory and hand ready payloads to a runtime hook.

This is the next step after the directory-spool consumer:
- the receiver writes `*.json` and `*.ready.json`
- this worker notices new ready descriptors
- it loads the full staged payload
- it calls a runtime hook that can register the block into a live target runtime
- it records a small processed marker for observability
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_adapter_utils import AdapterError, load_hook  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AdapterError(f"{path} did not contain a JSON object")
    return payload


def _marker_path(ready_path: Path) -> Path:
    return ready_path.with_suffix(".processed.json")


def _record_processed(ready_path: Path, payload_hash: str, result: dict[str, Any]) -> None:
    _marker_path(ready_path).write_text(
        json.dumps(
            {
                "hash": payload_hash,
                "processed_at_epoch_s": time.time(),
                "result": result,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _full_payload_path(import_dir: Path, ready_payload: dict[str, Any]) -> Path:
    payload_hash = ready_payload.get("hash")
    if not isinstance(payload_hash, str) or not payload_hash:
        raise AdapterError("ready descriptor is missing a valid 'hash'")
    path = import_dir / f"{payload_hash}.json"
    if not path.exists():
        raise AdapterError(f"staged payload missing for hash {payload_hash}")
    return path


def _consume_one(import_dir: Path, ready_path: Path, hook) -> dict[str, Any]:
    ready_payload = _load_json(ready_path)
    payload_path = _full_payload_path(import_dir, ready_payload)
    full_payload = _load_json(payload_path)
    result = hook(full_payload)
    if result is None:
        result = {"success": True}
    if not isinstance(result, dict):
        raise AdapterError("runtime hook must return a dict or None")
    _record_processed(ready_path, ready_payload["hash"], result)
    return result


def run_once(import_dir: Path, hook) -> int:
    processed = 0
    for ready_path in sorted(import_dir.glob("*.ready.json")):
        if _marker_path(ready_path).exists():
            continue
        result = _consume_one(import_dir, ready_path, hook)
        print(json.dumps({"ready": str(ready_path), "result": result}), flush=True)
        processed += 1
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Process staged PermeantOS import descriptors")
    parser.add_argument("--import-dir", required=True)
    parser.add_argument("--hook", required=True, help="module:function or /path/to/file.py:function")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    import_dir = Path(args.import_dir)
    import_dir.mkdir(parents=True, exist_ok=True)
    hook = load_hook(args.hook)

    if args.once:
        run_once(import_dir, hook)
        return 0

    while True:
        run_once(import_dir, hook)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

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

from agent_graph_span_metadata import (  # noqa: E402
    AgentGraphSpanMetadataError,
    validate_prompt_span_metadata,
)
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


def _target_prompt_view(payload: dict[str, Any]) -> dict[str, Any]:
    prompt_view = payload.get("target_prompt")
    if not isinstance(prompt_view, dict):
        prompt_view = {}

    prompt_text = prompt_view.get("text")
    if prompt_text is None:
        prompt_text = payload.get("prompt")
    if prompt_text is not None and not isinstance(prompt_text, str):
        raise AdapterError("target prompt text must be a string when present")

    token_ids = prompt_view.get("token_ids")
    if token_ids is None:
        token_ids = payload.get("prompt_token_ids")
    if token_ids is not None and (
        not isinstance(token_ids, list) or not all(isinstance(item, int) for item in token_ids)
    ):
        raise AdapterError("target prompt token_ids must be an integer list when present")

    token_count = prompt_view.get("token_count")
    if token_count is None:
        tokenization = payload.get("prompt_tokenization")
        if isinstance(tokenization, dict):
            token_count = tokenization.get("token_count")
    if token_count is None and token_ids is not None:
        token_count = len(token_ids)
    if token_count is not None and (not isinstance(token_count, int) or token_count <= 0):
        raise AdapterError("target prompt token_count must be a positive integer when present")

    tokenizer_hash = prompt_view.get("tokenizer_hash")
    if tokenizer_hash is None:
        tokenization = payload.get("prompt_tokenization")
        if isinstance(tokenization, dict):
            tokenizer_hash = tokenization.get("tokenizer_hash")
    if tokenizer_hash is not None and not isinstance(tokenizer_hash, str):
        raise AdapterError("target prompt tokenizer_hash must be a string when present")

    return {
        "expected_prompt": prompt_text,
        "expected_token_count": token_count,
        "expected_token_ids": token_ids,
        "expected_tokenizer_hash": tokenizer_hash,
    }


def _consume_one(import_dir: Path, ready_path: Path, hook) -> dict[str, Any]:
    ready_payload = _load_json(ready_path)
    payload_path = _full_payload_path(import_dir, ready_payload)
    full_payload = _load_json(payload_path)
    graph_span_validation = None
    if "agent_graph_span_metadata" in full_payload:
        try:
            graph_span_validation = validate_prompt_span_metadata(
                full_payload["agent_graph_span_metadata"],
                **_target_prompt_view(full_payload),
            )
        except AgentGraphSpanMetadataError as exc:
            raise AdapterError(f"invalid agent graph span metadata: {exc}") from exc
    result = hook(full_payload)
    if result is None:
        result = {"success": True}
    if not isinstance(result, dict):
        raise AdapterError("runtime hook must return a dict or None")
    if graph_span_validation is not None:
        result = {
            **result,
            "agent_graph_span_validation": graph_span_validation,
        }
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

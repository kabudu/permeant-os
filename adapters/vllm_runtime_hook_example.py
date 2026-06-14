"""Example target-side runtime hook for a live vLLM-adjacent process.

This example keeps the final integration conservative:
- injected blocks are prepared by `vllm_runtime_bridge.py`
- the hook persists a small index for downstream pickup
- verification checks whether hashes were staged and acknowledged

Environment:
- PERMEANT_VLLM_STATE_DIR=/tmp/permeant-vllm-state
- PERMEANT_VLLM_ACK_FILE=/tmp/permeant-vllm-state/acked.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _ack_path() -> Path | None:
    value = os.getenv("PERMEANT_VLLM_ACK_FILE")
    return Path(value) if value else None


def _load_acks(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return set()
    return {item for item in data if isinstance(item, str)}


def runtime_hook(payload: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    if "layers" in payload:
        ack = _ack_path()
        if ack is None:
            return {"success": True}
        ack.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_acks(ack)
        existing.add(payload["hash"])
        ack.write_text(json.dumps(sorted(existing), indent=2), encoding="utf-8")
        return {"success": True}

    if "block_hashes" in payload:
        ack = _ack_path()
        if ack is None:
            return {"success": True}
        existing = _load_acks(ack)
        missing = [item for item in payload["block_hashes"] if item not in existing]
        if missing:
            return {"success": False, "missing_hashes": missing}
        return {"success": True}

    return {"success": False, "error": "unsupported payload"}

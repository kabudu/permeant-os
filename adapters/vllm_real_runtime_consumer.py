"""Import-worker consumer that registers incoming payloads into a real vLLM runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from vllm_live_runtime_registry import runtime_hook


def consume(payload: dict[str, Any]) -> dict[str, Any]:
    target = os.getenv("PERMEANT_VLLM_RUNTIME_TARGET")
    if not target:
        os.environ["PERMEANT_VLLM_RUNTIME_TARGET"] = f"{SCRIPT_DIR / 'vllm_real_runtime_target.py'}:get_runtime"
    os.environ.setdefault("PERMEANT_VLLM_RUNTIME_STATE_FILE", "/tmp/permeant-vllm-runtime-state.json")
    os.environ.setdefault("PERMEANT_VLLM_RUNTIME_PROBE_FILE", "/tmp/permeant-vllm-runtime-probe.json")
    return runtime_hook(payload)

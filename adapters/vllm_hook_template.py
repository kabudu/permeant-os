"""Usable live injector hook for PERMEANT_INJECTOR_HOOK.

Environment:
- PERMEANT_VLLM_STATE_DIR: optional directory where prepared block payloads are written
- PERMEANT_VLLM_RUNTIME_HOOK: optional module/file hook that performs the final runtime-specific injection

Without PERMEANT_VLLM_RUNTIME_HOOK this hook still prepares real vLLM block-shaped tensors
and persists them for offline inspection or for a separate connector process.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from vllm_runtime_bridge import injector_hook as _injector_hook


def injector_hook(request: dict[str, Any]) -> dict[str, Any]:
    return _injector_hook(request)

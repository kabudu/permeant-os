"""Usable injector hook for the reference PyTorch target runtime.

Set this as `PERMEANT_INJECTOR_HOOK` when the command-backed injector should
materialize migrated state in the reference PyTorch adapter:

    export PERMEANT_INJECTOR_HOOK=/ABS/PATH/adapters/pytorch_hook_template.py:injector_hook
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pytorch_runtime_bridge import injector_hook as _injector_hook


def injector_hook(request: dict[str, Any]) -> dict[str, Any]:
    return _injector_hook(request)

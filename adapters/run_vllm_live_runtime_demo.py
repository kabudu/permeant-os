#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_MODULE = "tests.fixtures.vllm_live_runtime_fixture"
STATE_FILE = ROOT / "tmp" / "vllm-live-runtime-demo-state.json"


def main() -> int:
    fixture = importlib.import_module(FIXTURE_MODULE)
    fixture.reset_tensor_backed_runtime()

    os.environ["PERMEANT_VLLM_RUNTIME_TARGET"] = f"{FIXTURE_MODULE}:get_tensor_backed_runtime"
    os.environ["PERMEANT_VLLM_RUNTIME_REGISTER_METHOD"] = "missing_register_method"
    os.environ["PERMEANT_VLLM_RUNTIME_VERIFY_METHOD"] = "missing_verify_method"
    os.environ["PERMEANT_VLLM_RUNTIME_STATE_FILE"] = str(STATE_FILE)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        STATE_FILE.unlink()

    registry = importlib.import_module("adapters.vllm_live_runtime_registry")
    payload = fixture.build_tensor_backed_payload("sha256:demo-inprocess")

    inject_result = registry.runtime_hook(payload)
    verify_result = registry.runtime_hook({"block_hashes": ["sha256:demo-inprocess"]})

    output = {
        "inject_result": inject_result,
        "verify_result": verify_result,
        "runtime_snapshot": fixture.snapshot_tensor_backed_runtime(),
        "state_file": str(STATE_FILE),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

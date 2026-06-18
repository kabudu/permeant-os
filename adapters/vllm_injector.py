#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from runtime_adapter_utils import (
    AdapterError,
    dump_json_stdout,
    load_hook,
    load_json_stdin,
    normalize_injector_response,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def load_state(path: Path) -> dict:
    if path.exists():
        return __import__("json").loads(path.read_text())
    return {"blocks": {}}


def save_state(path: Path, state: dict) -> None:
    path.write_text(__import__("json").dumps(state, indent=2, sort_keys=True))


def handle_fixture_state(request: dict, state_path: Path) -> dict:
    state = load_state(state_path)
    action = request.get("action")

    if action == "inject_block":
        state.setdefault("blocks", {})[request["block_hash"]] = request
        save_state(state_path, state)
        return {"success": True}

    if action == "verify_continuation":
        missing = [
            block_hash
            for block_hash in request.get("expected_hashes", [])
            if block_hash not in state.get("blocks", {})
        ]
        if missing:
            return {"success": False, "missing_hashes": missing}
        return {"success": True}

    return {"success": False, "error": f"unsupported action: {action}"}


def main() -> int:
    try:
        request = load_json_stdin()

        fixture_state = os.environ.get("PERMEANT_INJECTOR_FIXTURE_STATE")
        if fixture_state:
            dump_json_stdout(normalize_injector_response(handle_fixture_state(request, Path(fixture_state))))
            return 0

        hook_spec = os.environ.get("PERMEANT_INJECTOR_HOOK")
        if hook_spec:
            hook = load_hook(hook_spec)
            dump_json_stdout(normalize_injector_response(hook(request)))
            return 0

        if os.environ.get("PERMEANT_VLLM_STATE_DIR") or os.environ.get("PERMEANT_VLLM_RUNTIME_HOOK"):
            hook = load_hook(f"{SCRIPT_DIR / 'vllm_hook_template.py'}:injector_hook")
            dump_json_stdout(normalize_injector_response(hook(request)))
            return 0

        try:
            import vllm  # noqa: F401
        except Exception:
            return fail(
                "vllm_injector: target runtime not available. "
                "Set PERMEANT_INJECTOR_FIXTURE_STATE for offline replay or "
                "PERMEANT_INJECTOR_HOOK for a live adapter implementation."
            )

        return fail(
            "vllm_injector: live target runtime injection is not implemented in-tree yet. "
            "Point PERMEANT_INJECTOR_HOOK at a module function that accepts the documented injector JSON contract."
        )
    except AdapterError as exc:
        return fail(f"vllm_injector: {exc}")
    except Exception as exc:
        return fail(f"vllm_injector: unexpected failure: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

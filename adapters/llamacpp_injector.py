#!/usr/bin/env python3
"""Command-backed injector for the llama.cpp target adapter."""

from __future__ import annotations

import sys
from pathlib import Path

from runtime_adapter_utils import AdapterError, dump_json_stdout, load_json_stdin

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from llamacpp_runtime_bridge import injector_hook


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    try:
        request = load_json_stdin()
        dump_json_stdout(injector_hook(request))
        return 0
    except AdapterError as exc:
        return fail(f"llamacpp_injector: {exc}")
    except Exception as exc:
        return fail(f"llamacpp_injector: unexpected failure: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from runtime_adapter_utils import (
    AdapterError,
    dump_json_stdout,
    load_hook,
    load_json_file,
    load_json_stdin,
    normalize_extractor_payload,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    try:
        request = load_json_stdin()

        fixture_path = os.environ.get("PERMEANT_EXTRACTOR_FIXTURE")
        if fixture_path:
            dump_json_stdout(normalize_extractor_payload(load_json_file(fixture_path)))
            return 0

        hook_spec = os.environ.get("PERMEANT_EXTRACTOR_HOOK")
        if hook_spec:
            hook = load_hook(hook_spec)
            dump_json_stdout(normalize_extractor_payload(hook(request)))
            return 0

        if os.environ.get("PERMEANT_MLX_CACHE_PROVIDER") or os.environ.get("PERMEANT_MLX_CACHE_JSON"):
            hook = load_hook(f"{SCRIPT_DIR / 'mlx_hook_template.py'}:extractor_hook")
            dump_json_stdout(normalize_extractor_payload(hook(request)))
            return 0

        try:
            import mlx  # noqa: F401
        except Exception:
            return fail(
                "mlx_extractor: MLX runtime not available. "
                "Set PERMEANT_EXTRACTOR_FIXTURE for offline replay or "
                "PERMEANT_EXTRACTOR_HOOK for a live adapter implementation."
            )

        return fail(
            "mlx_extractor: live MLX extraction is not implemented in-tree yet. "
            "Point PERMEANT_EXTRACTOR_HOOK at a module function that returns the documented tensor JSON contract."
        )
    except AdapterError as exc:
        return fail(f"mlx_extractor: {exc}")
    except Exception as exc:
        return fail(f"mlx_extractor: unexpected failure: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())

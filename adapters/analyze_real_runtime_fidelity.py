#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _find_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for event in events:
        if event.get("event") == name:
            return event
    return None


def _verification(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = manifest.get("verification")
    return payload if isinstance(payload, dict) else {}


def _first_mismatch(comparison: dict[str, Any] | None) -> int | None:
    if not isinstance(comparison, dict):
        return None
    return comparison.get("first_token_mismatch_index")


def _summarize(manifest: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    events = probe.get("events")
    events = events if isinstance(events, list) else []
    verify = _verification(manifest)
    source_comparison = verify.get("source_comparison")
    baseline_comparison = verify.get("baseline_comparison")
    register_event = _find_event(events, "register_permeant_block") or {}
    baseline_event = _find_event(events, "baseline_continuation") or {}
    generated_event = _find_event(events, "generate_continuation") or {}

    return {
        "migration_id": manifest.get("migration_id"),
        "success": manifest.get("success"),
        "hash_validation_success": verify.get("success"),
        "written_layers": len(register_event.get("written_layers", [])),
        "source_first_mismatch_index": _first_mismatch(source_comparison),
        "baseline_first_mismatch_index": _first_mismatch(baseline_comparison),
        "matches_source_exactly": bool(
            isinstance(source_comparison, dict) and source_comparison.get("matches")
        ),
        "matches_target_baseline_exactly": bool(
            isinstance(baseline_comparison, dict) and baseline_comparison.get("matches")
        ),
        "source_output_text": (verify.get("source_continuation") or {}).get("text"),
        "post_migration_output_text": (verify.get("continuation") or {}).get("text"),
        "baseline_output_text": baseline_event.get("text"),
        "post_migration_token_count": len(generated_event.get("token_ids", [])),
        "baseline_token_count": len(baseline_event.get("token_ids", [])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize a real-runtime fidelity run from manifest and probe artifacts."
    )
    parser.add_argument("--manifest", required=True, help="Path to migration manifest JSON")
    parser.add_argument("--probe", required=True, help="Path to target probe JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON result")
    args = parser.parse_args()

    summary = _summarize(
        _load_json(Path(args.manifest)),
        _load_json(Path(args.probe)),
    )
    if args.pretty:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()

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


def _find_events(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") == name]


def _verification(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = manifest.get("verification")
    return payload if isinstance(payload, dict) else {}


def _verification_from_probe(events: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _find_event(events, "verify_permeant_hashes")
    return payload if isinstance(payload, dict) else {}


def _first_mismatch(comparison: dict[str, Any] | None) -> int | None:
    if not isinstance(comparison, dict):
        return None
    return comparison.get("first_token_mismatch_index")


def _summarize(manifest: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    events = probe.get("events")
    events = events if isinstance(events, list) else []
    verify = _verification(manifest) or _verification_from_probe(events)
    source_comparison = verify.get("source_comparison")
    baseline_comparison = verify.get("baseline_comparison")
    register_event = _find_event(events, "register_permeant_block") or {}
    baseline_event = _find_event(events, "baseline_continuation") or {}
    generated_event = _find_event(events, "generate_continuation") or {}
    source_reference = verify.get("source_continuation") or {}
    decode_snapshots = _find_events(events, "decode_attachment_snapshot")
    attachment_attempts = _find_events(events, "migrated_decode_attachment_attempt")
    post_decode_snapshots = [
        event
        for event in decode_snapshots
        if str(event.get("stage", "")).startswith("generate_continuation:")
    ]
    post_decode_after = next(
        (
            event
            for event in reversed(post_decode_snapshots)
            if str(event.get("stage", "")).endswith(":after_generate")
        ),
        {},
    )
    prompt_tokenization = post_decode_after.get("prompt_tokenization")
    outputs = post_decode_after.get("outputs")
    last_attachment_attempt = attachment_attempts[-1].get("attempt", {}) if attachment_attempts else {}
    block_table_candidate = (
        last_attachment_attempt.get("migration_block_table_candidate", {})
        if isinstance(last_attachment_attempt, dict)
        else {}
    )
    prefix_cache_seed = (
        last_attachment_attempt.get("prefix_cache_seed", {})
        if isinstance(last_attachment_attempt, dict)
        else {}
    )

    return {
        "migration_id": manifest.get("migration_id") or manifest.get("run_id"),
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
        "source_output_text": source_reference.get("text")
        or (source_comparison or {}).get("expected_text"),
        "post_migration_output_text": (verify.get("continuation") or {}).get("text")
        or generated_event.get("text")
        or (source_comparison or {}).get("actual_text"),
        "baseline_output_text": baseline_event.get("text"),
        "post_migration_token_count": len(generated_event.get("token_ids", [])),
        "baseline_token_count": len(baseline_event.get("token_ids", [])),
        "decode_attachment_snapshot_count": len(decode_snapshots),
        "post_migration_decode_snapshot_available": bool(post_decode_after),
        "post_migration_prompt_token_count": (
            prompt_tokenization or {}
        ).get("token_count")
        if isinstance(prompt_tokenization, dict)
        else None,
        "post_migration_output_request_id": (
            ((outputs or {}).get("items") or [{}])[0].get("request_id")
            if isinstance(outputs, dict)
            else None
        ),
        "post_migration_runtime_object_count": len(
            post_decode_after.get("candidate_runtime_objects", [])
        )
        if isinstance(post_decode_after, dict)
        else 0,
        "migrated_decode_attachment_attempt_count": len(attachment_attempts),
        "migrated_decode_attachment_supported": bool(last_attachment_attempt.get("supported"))
        if last_attachment_attempt
        else False,
        "migrated_decode_attachment_reason": last_attachment_attempt.get("reason")
        if last_attachment_attempt
        else None,
        "migration_target_block_count": block_table_candidate.get("target_block_count")
        if isinstance(block_table_candidate, dict)
        else None,
        "migration_target_block_size": block_table_candidate.get("target_block_size")
        if isinstance(block_table_candidate, dict)
        else None,
        "vllm_prefix_cache_seed_success": bool(prefix_cache_seed.get("success"))
        if isinstance(prefix_cache_seed, dict)
        else False,
        "vllm_prefix_cache_seeded_block_count": prefix_cache_seed.get("seeded_block_count")
        if isinstance(prefix_cache_seed, dict)
        else None,
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

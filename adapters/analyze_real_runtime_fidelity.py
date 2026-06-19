#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


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


def _comparison_field(comparison: dict[str, Any] | None, field: str) -> Any:
    if not isinstance(comparison, dict):
        return None
    return comparison.get(field)


def _status(success: bool | None, available: bool = True) -> str:
    if not available:
        return "unavailable"
    if success is True:
        return "aligned"
    if success is False:
        return "diverged"
    return "unknown"


def _artifact_hashes(agent_graph: dict[str, Any]) -> dict[str, str]:
    artifacts = agent_graph.get("artifacts")
    if not isinstance(artifacts, list):
        return {}
    hashes = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        digest = artifact.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            hashes[path] = digest
    return hashes


def _kv_span_checks(agent_graph: dict[str, Any]) -> dict[str, Any]:
    spans = agent_graph.get("kv_spans")
    if not isinstance(spans, list):
        return {
            "available": False,
            "span_count": 0,
            "invalid_span_count": 0,
            "token_coverage": None,
            "cache_refs": [],
            "failure_classes": ["missing_kv_spans"],
        }
    if not spans:
        return {
            "available": True,
            "span_count": 0,
            "invalid_span_count": 0,
            "token_coverage": 0,
            "cache_refs": [],
            "failure_classes": ["missing_kv_spans"],
        }

    invalid = 0
    token_coverage = 0
    cache_refs: list[str] = []
    failure_classes: list[str] = []

    for span in spans:
        if not isinstance(span, dict):
            invalid += 1
            failure_classes.append("invalid_kv_span")
            continue

        node_id = span.get("node_id")
        cache_ref = span.get("cache_ref")
        token_start = span.get("token_start")
        token_end = span.get("token_end")
        tokenizer_hash = span.get("tokenizer_hash")
        block_hashes = span.get("block_hashes", [])

        valid = True
        if not isinstance(node_id, str) or not node_id:
            valid = False
        if not isinstance(cache_ref, str) or not cache_ref:
            valid = False
        else:
            cache_refs.append(cache_ref)
        if not isinstance(token_start, int) or not isinstance(token_end, int) or token_end <= token_start:
            valid = False
        else:
            token_coverage += token_end - token_start
        if tokenizer_hash is not None and (
            not isinstance(tokenizer_hash, str) or SHA256_RE.match(tokenizer_hash) is None
        ):
            valid = False
        if not isinstance(block_hashes, list) or any(
            not isinstance(item, str) or SHA256_RE.match(item) is None for item in block_hashes
        ):
            valid = False

        if not valid:
            invalid += 1
            failure_classes.append("invalid_kv_span")

    return {
        "available": True,
        "span_count": len(spans),
        "invalid_span_count": invalid,
        "token_coverage": token_coverage,
        "cache_refs": sorted(set(cache_refs)),
        "failure_classes": sorted(set(failure_classes)),
    }


def _alignment_summary(
    manifest: dict[str, Any],
    verify: dict[str, Any],
    source_comparison: dict[str, Any] | None,
    prompt_tokenization: dict[str, Any] | None,
    register_event: dict[str, Any],
    prefix_cache_seed: dict[str, Any],
) -> dict[str, Any]:
    agent_graph = manifest.get("agent_graph")
    agent_graph = agent_graph if isinstance(agent_graph, dict) else {}
    source_comparison_available = isinstance(source_comparison, dict)
    prompt_matches = (
        source_comparison.get("prompt_matches")
        if source_comparison_available
        else None
    )
    prompt_token_count = (
        prompt_tokenization.get("token_count")
        if isinstance(prompt_tokenization, dict)
        else None
    )
    graph_available = bool(agent_graph)
    kv_span_checks = _kv_span_checks(agent_graph) if graph_available else {
        "available": False,
        "span_count": 0,
        "invalid_span_count": 0,
        "token_coverage": None,
        "cache_refs": [],
        "failure_classes": ["missing_graph_package"],
    }
    kv_validation = verify.get("success")
    prefix_cache_success = (
        prefix_cache_seed.get("success")
        if isinstance(prefix_cache_seed, dict)
        else None
    )
    written_layers = register_event.get("written_layers", [])
    written_layer_count = len(written_layers) if isinstance(written_layers, list) else 0

    prompt = {
        "status": _status(prompt_matches, source_comparison_available),
        "source_prompt_matches_target": prompt_matches,
        "source_shared_prefix_token_count": _comparison_field(
            source_comparison,
            "shared_prefix_token_count",
        ),
        "source_expected_token_count": _comparison_field(
            source_comparison,
            "expected_token_count",
        ),
        "source_actual_token_count": _comparison_field(
            source_comparison,
            "actual_token_count",
        ),
        "target_prompt_token_count": prompt_token_count,
        "graph_prompt_byte_hash": agent_graph.get("prompt_byte_hash"),
        "graph_prompt_token_hash": agent_graph.get("prompt_token_hash"),
        "tokenizer_hash": agent_graph.get("tokenizer_hash"),
    }

    if not graph_available:
        graph_status = "unavailable"
    elif kv_span_checks["invalid_span_count"] > 0:
        graph_status = "diverged"
    elif not kv_span_checks["available"] or kv_span_checks["span_count"] == 0:
        graph_status = "partial"
    else:
        graph_status = "aligned"

    graph = {
        "status": graph_status,
        "graph_hash": agent_graph.get("graph_hash"),
        "graph_path": agent_graph.get("graph_path"),
        "manifest_path": agent_graph.get("manifest_path"),
        "artifact_hashes": _artifact_hashes(agent_graph),
        "kv_spans_available": kv_span_checks["available"],
        "kv_span_count": kv_span_checks["span_count"],
        "invalid_kv_span_count": kv_span_checks["invalid_span_count"],
        "kv_span_token_coverage": kv_span_checks["token_coverage"],
        "kv_span_cache_refs": kv_span_checks["cache_refs"],
        "failure_classes": kv_span_checks["failure_classes"],
    }

    kv = {
        "status": _status(
            kv_validation if isinstance(kv_validation, bool) else None,
            bool(verify),
        ),
        "hash_validation_success": kv_validation,
        "graph_kv_hash": agent_graph.get("kv_hash"),
        "graph_kv_span_count": kv_span_checks["span_count"],
        "graph_kv_span_token_coverage": kv_span_checks["token_coverage"],
        "written_layer_count": written_layer_count,
        "vllm_prefix_cache_seed_success": prefix_cache_success,
        "vllm_prefix_cache_seeded_block_count": prefix_cache_seed.get("seeded_block_count")
        if isinstance(prefix_cache_seed, dict)
        else None,
    }

    statuses = [prompt["status"], graph["status"], kv["status"]]
    if "diverged" in statuses:
        overall_status = "diverged"
    elif all(status == "aligned" for status in statuses):
        overall_status = "aligned"
    elif any(status in {"aligned", "partial"} for status in statuses):
        overall_status = "partial"
    else:
        overall_status = "unknown"

    return {
        "overall_status": overall_status,
        "prompt": prompt,
        "graph": graph,
        "kv": kv,
    }


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

    summary = {
        "migration_id": manifest.get("migration_id") or manifest.get("run_id"),
        "success": manifest.get("success"),
        "hash_validation_success": verify.get("success"),
        "written_layers": len(register_event.get("written_layers", [])),
        "source_first_mismatch_index": _first_mismatch(source_comparison),
        "source_shared_prefix_token_count": _comparison_field(source_comparison, "shared_prefix_token_count"),
        "source_expected_token_count": _comparison_field(source_comparison, "expected_token_count"),
        "source_actual_token_count": _comparison_field(source_comparison, "actual_token_count"),
        "source_actual_ended_before_reference": bool(
            _comparison_field(source_comparison, "actual_ended_before_reference")
        ),
        "baseline_first_mismatch_index": _first_mismatch(baseline_comparison),
        "baseline_shared_prefix_token_count": _comparison_field(baseline_comparison, "shared_prefix_token_count"),
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
    summary["alignment"] = _alignment_summary(
        manifest=manifest,
        verify=verify,
        source_comparison=source_comparison,
        prompt_tokenization=prompt_tokenization,
        register_event=register_event,
        prefix_cache_seed=prefix_cache_seed,
    )
    return summary


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

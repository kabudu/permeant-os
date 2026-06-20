#!/usr/bin/env python3
"""Evaluate decode fidelity across multiple continuation horizons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_HORIZONS = [16, 32, 64, 128]


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def parse_horizons(value: str) -> list[int]:
    horizons = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        horizon = int(item)
        if horizon <= 0:
            raise ValueError("horizons must be positive integers")
        horizons.append(horizon)
    if not horizons:
        raise ValueError("at least one horizon is required")
    return sorted(set(horizons))


def probe_event(probe: dict[str, Any], event_name: str) -> dict[str, Any] | None:
    events = probe.get("events")
    if not isinstance(events, list):
        return None
    for event in reversed(events):
        if isinstance(event, dict) and event.get("event") == event_name:
            return event
    return None


def tokens(record: dict[str, Any] | None) -> list[int]:
    if not isinstance(record, dict):
        return []
    value = record.get("token_ids")
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return []
        result.append(item)
    return result


def prompt(record: dict[str, Any] | None) -> str | None:
    value = record.get("prompt") if isinstance(record, dict) else None
    return value if isinstance(value, str) else None


def first_mismatch_index(expected: list[int], actual: list[int], limit: int | None = None) -> int | None:
    max_len = min(len(expected), len(actual))
    if limit is not None:
        max_len = min(max_len, limit)
    for index in range(max_len):
        if expected[index] != actual[index]:
            return index
    if limit is not None and max_len >= limit:
        return None
    if len(expected) != len(actual):
        return max_len
    return None


def compare_pair(name: str, expected_record: dict[str, Any] | None, actual_record: dict[str, Any] | None, horizons: list[int]) -> dict[str, Any]:
    expected = tokens(expected_record)
    actual = tokens(actual_record)
    expected_prompt = prompt(expected_record)
    actual_prompt = prompt(actual_record)
    prompt_matches = None
    if expected_prompt is not None and actual_prompt is not None:
        prompt_matches = expected_prompt == actual_prompt

    horizon_results = []
    for horizon in horizons:
        expected_available = len(expected) >= horizon
        actual_available = len(actual) >= horizon
        mismatch = first_mismatch_index(expected, actual, horizon)
        exact = expected_available and actual_available and mismatch is None
        if exact:
            status = "exact"
        elif not expected_available or not actual_available:
            status = "insufficient_tokens"
        else:
            status = "diverged"
        horizon_results.append(
            {
                "horizon": horizon,
                "status": status,
                "exact": exact,
                "first_mismatch_index": mismatch,
                "expected_available_tokens": len(expected),
                "actual_available_tokens": len(actual),
                "expected_has_horizon": expected_available,
                "actual_has_horizon": actual_available,
            }
        )

    exact_horizons = [item["horizon"] for item in horizon_results if item["exact"]]
    first_failure = next((item for item in horizon_results if not item["exact"]), None)
    return {
        "name": name,
        "available": bool(expected and actual),
        "prompt_matches": prompt_matches,
        "expected_token_count": len(expected),
        "actual_token_count": len(actual),
        "first_mismatch_index": first_mismatch_index(expected, actual),
        "max_exact_horizon": max(exact_horizons) if exact_horizons else 0,
        "first_failed_horizon": first_failure["horizon"] if first_failure else None,
        "horizons": horizon_results,
    }


def summarize(
    source: dict[str, Any],
    post_migration: dict[str, Any],
    baseline: dict[str, Any] | None,
    horizons: list[int],
) -> dict[str, Any]:
    comparisons = [
        compare_pair("source_vs_post_migration", source, post_migration, horizons),
    ]
    if baseline is not None:
        comparisons.append(compare_pair("baseline_vs_post_migration", baseline, post_migration, horizons))

    available_comparisons = [comparison for comparison in comparisons if comparison["available"]]
    complete_exact_horizons = []
    for horizon in horizons:
        if available_comparisons and all(
            any(item["horizon"] == horizon and item["exact"] for item in comparison["horizons"])
            for comparison in available_comparisons
        ):
            complete_exact_horizons.append(horizon)

    return {
        "schema_version": "permeantos-fidelity-horizon-suite-v0",
        "horizons": horizons,
        "max_complete_exact_horizon": max(complete_exact_horizons) if complete_exact_horizons else 0,
        "comparisons": comparisons,
    }


def markdown_table(summary: dict[str, Any]) -> str:
    lines = [
        "| Comparison | Horizon | Status | First mismatch | Expected tokens | Actual tokens |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for comparison in summary["comparisons"]:
        for horizon in comparison["horizons"]:
            mismatch = horizon["first_mismatch_index"]
            lines.append(
                "| {name} | {horizon} | {status} | {mismatch} | {expected} | {actual} |".format(
                    name=comparison["name"],
                    horizon=horizon["horizon"],
                    status=horizon["status"],
                    mismatch="" if mismatch is None else mismatch,
                    expected=horizon["expected_available_tokens"],
                    actual=horizon["actual_available_tokens"],
                )
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Source continuation JSON")
    parser.add_argument("--post", type=Path, help="Post-migration continuation JSON")
    parser.add_argument("--baseline", type=Path, help="Optional target baseline continuation JSON")
    parser.add_argument("--probe", type=Path, help="Optional target probe JSON containing continuation events")
    parser.add_argument("--horizons", default=",".join(str(item) for item in DEFAULT_HORIZONS))
    parser.add_argument("--markdown-out", type=Path, help="Optional Markdown report path")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    probe = load_json(args.probe) if args.probe else {}
    source = load_json(args.source)
    post = load_json(args.post) if args.post else probe_event(probe, "generate_continuation")
    baseline = load_json(args.baseline) if args.baseline else probe_event(probe, "baseline_continuation")
    if post is None:
        raise SystemExit("post-migration continuation not supplied and not found in probe")

    summary = summarize(
        source=source,
        post_migration=post,
        baseline=baseline,
        horizons=parse_horizons(args.horizons),
    )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown_table(summary))
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))


if __name__ == "__main__":
    main()

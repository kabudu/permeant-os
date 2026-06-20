#!/usr/bin/env python3
"""Summarize PermeantOS migration benchmark manifests.

The script accepts manifest files or directories containing
`migration-*-manifest.json` files and emits structured JSON suitable for paper
tables, release notes, or scheduled validation records.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


MANIFEST_GLOB = "migration-*-manifest.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def discover_manifest_paths(inputs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(sorted(item.glob(MANIFEST_GLOB)))
        else:
            paths.append(item)
    unique = sorted({path.resolve() for path in paths})
    return unique


def _number(manifest: dict[str, Any], key: str) -> float | None:
    value = manifest.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def classify_failure(manifest: dict[str, Any]) -> str | None:
    if manifest.get("success") is True:
        return None
    phase_status = manifest.get("phase_status")
    if phase_status:
        return str(phase_status)
    if manifest.get("success") is False:
        return "failed"
    return "unknown"


def summarize_numbers(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def summarize_group(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [classify_failure(manifest) for manifest in manifests]
    failure_classes = [failure for failure in failures if failure]
    successful = [manifest for manifest in manifests if classify_failure(manifest) is None]
    return {
        "run_count": len(manifests),
        "success_count": len(successful),
        "failure_count": len(failure_classes),
        "phase_status_counts": dict(sorted(Counter(str(manifest.get("phase_status", "unknown")) for manifest in manifests).items())),
        "failure_class_counts": dict(sorted(Counter(failure_classes).items())),
        "transfer_time_ms": summarize_numbers(
            [value for manifest in successful if (value := _number(manifest, "transfer_time_ms")) is not None]
        ),
        "total_time_ms": summarize_numbers(
            [value for manifest in successful if (value := _number(manifest, "total_time_ms")) is not None]
        ),
        "effective_bandwidth_gbps": summarize_numbers(
            [value for manifest in successful if (value := _number(manifest, "effective_bandwidth_gbps")) is not None]
        ),
        "chunks_sent": summarize_numbers(
            [value for manifest in successful if (value := _number(manifest, "chunks_sent")) is not None]
        ),
    }


def summarize_manifests(paths: list[Path]) -> dict[str, Any]:
    loaded = []
    for path in paths:
        manifest = _load_json(path)
        manifest["_source_path"] = str(path)
        loaded.append(manifest)

    groups: dict[tuple[int | str, str], list[dict[str, Any]]] = defaultdict(list)
    for manifest in loaded:
        key = (
            manifest.get("sequence_length", "unknown"),
            str(manifest.get("transfer_quantization", "unknown")),
        )
        groups[key].append(manifest)

    group_summaries = []
    for (sequence_length, transfer_quantization), manifests in sorted(groups.items(), key=group_sort_key):
        summary = summarize_group(manifests)
        summary.update(
            {
                "sequence_length": sequence_length,
                "transfer_quantization": transfer_quantization,
                "run_ids": [str(manifest.get("run_id", path_name(manifest))) for manifest in manifests],
            }
        )
        group_summaries.append(summary)

    failure_records = [
        {
            "run_id": str(manifest.get("run_id", path_name(manifest))),
            "source_path": manifest["_source_path"],
            "phase_status": manifest.get("phase_status"),
            "failure_class": failure,
            "error_message": manifest.get("error_message"),
        }
        for manifest in loaded
        if (failure := classify_failure(manifest)) is not None
    ]

    return {
        "schema_version": "permeantos-benchmark-summary-v0",
        "manifest_count": len(loaded),
        "success_count": sum(1 for manifest in loaded if classify_failure(manifest) is None),
        "failure_count": len(failure_records),
        "groups": group_summaries,
        "failure_records": failure_records,
        "paper_table_rows": [
            {
                "sequence_length": group["sequence_length"],
                "transfer_quantization": group["transfer_quantization"],
                "runs": group["run_count"],
                "successes": group["success_count"],
                "median_transfer_time_ms": group["transfer_time_ms"]["median"],
                "median_total_time_ms": group["total_time_ms"]["median"],
                "median_effective_bandwidth_gbps": group["effective_bandwidth_gbps"]["median"],
            }
            for group in group_summaries
        ],
    }


def path_name(manifest: dict[str, Any]) -> str:
    return Path(str(manifest.get("_source_path", "unknown"))).name


def group_sort_key(item: tuple[tuple[int | str, str], list[dict[str, Any]]]) -> tuple[int, int | str, str]:
    sequence_length, transfer_quantization = item[0]
    if isinstance(sequence_length, int):
        return (0, sequence_length, transfer_quantization)
    return (1, str(sequence_length), transfer_quantization)


def markdown_table(summary: dict[str, Any]) -> str:
    lines = [
        "| Seq len | Transfer quantization | Runs | Successes | Median transfer ms | Median total ms | Median bandwidth Gbps |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["paper_table_rows"]:
        lines.append(
            "| {sequence_length} | {transfer_quantization} | {runs} | {successes} | {median_transfer_time_ms} | {median_total_time_ms} | {median_effective_bandwidth_gbps} |".format(
                **row
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Manifest files or directories containing migration manifests.")
    parser.add_argument("--markdown-out", type=Path, help="Optional path for a paper-table Markdown summary.")
    args = parser.parse_args()

    paths = discover_manifest_paths(args.inputs)
    summary = summarize_manifests(paths)
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown_table(summary))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

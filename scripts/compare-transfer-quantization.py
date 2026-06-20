#!/usr/bin/env python3
"""Compare paired PermeantOS transfer-quantization benchmark manifests."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


MANIFEST_GLOB = "migration-*-manifest.json"
DEFAULT_IDENTITY_FIELDS = [
    "sequence_length",
    "model_identity",
    "model_architecture",
    "dtype",
    "source_quantization",
    "target_device",
]


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def discover_manifest_paths(inputs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            paths.extend(sorted(item.glob(MANIFEST_GLOB)))
        else:
            paths.append(item)
    return sorted({path.resolve() for path in paths})


def classify_failure(manifest: dict[str, Any]) -> str | None:
    if manifest.get("success") is True:
        return None
    phase_status = manifest.get("phase_status")
    if phase_status:
        return str(phase_status)
    if manifest.get("success") is False:
        return "failed"
    return "unknown"


def number(manifest: dict[str, Any], key: str) -> float | None:
    value = manifest.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def quantization_mode(manifest: dict[str, Any]) -> str:
    return str(manifest.get("transfer_quantization", "unknown"))


def run_id(manifest: dict[str, Any]) -> str:
    return str(manifest.get("run_id", Path(str(manifest.get("_source_path", "unknown"))).stem))


def group_key(manifest: dict[str, Any], fields: list[str]) -> tuple[Any, ...]:
    return tuple(manifest.get(field, "unknown") for field in fields)


def fidelity_horizon(manifest: dict[str, Any]) -> int | None:
    for key in ("fidelity_max_complete_exact_horizon", "max_complete_exact_horizon"):
        value = manifest.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    summary = manifest.get("fidelity_horizon_summary")
    if isinstance(summary, dict):
        value = summary.get("max_complete_exact_horizon")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def fidelity_status(manifests: list[dict[str, Any]], required_horizon: int | None) -> dict[str, Any]:
    horizons = [horizon for manifest in manifests if (horizon := fidelity_horizon(manifest)) is not None]
    if not required_horizon:
        return {
            "status": "not_required",
            "required_horizon": None,
            "verified_run_count": len(horizons),
            "max_observed_horizon": max(horizons) if horizons else None,
        }
    verified = [horizon for horizon in horizons if horizon >= required_horizon]
    if verified:
        status = "verified"
    elif horizons:
        status = "below_required_horizon"
    else:
        status = "unverified"
    return {
        "status": status,
        "required_horizon": required_horizon,
        "verified_run_count": len(verified),
        "max_observed_horizon": max(horizons) if horizons else None,
    }


def summarize_mode(manifests: list[dict[str, Any]], required_fidelity_horizon: int | None) -> dict[str, Any]:
    successful = [manifest for manifest in manifests if classify_failure(manifest) is None]
    failures = [failure for manifest in manifests if (failure := classify_failure(manifest)) is not None]
    return {
        "run_count": len(manifests),
        "success_count": len(successful),
        "failure_count": len(failures),
        "failure_class_counts": dict(sorted(Counter(failures).items())),
        "run_ids": [run_id(manifest) for manifest in manifests],
        "successful_run_ids": [run_id(manifest) for manifest in successful],
        "median_transfer_time_ms": median(
            [value for manifest in successful if (value := number(manifest, "transfer_time_ms")) is not None]
        ),
        "median_total_time_ms": median(
            [value for manifest in successful if (value := number(manifest, "total_time_ms")) is not None]
        ),
        "median_effective_bandwidth_gbps": median(
            [value for manifest in successful if (value := number(manifest, "effective_bandwidth_gbps")) is not None]
        ),
        "median_transferred_bytes": median(
            [value for manifest in successful if (value := number(manifest, "transferred_bytes")) is not None]
        ),
        "fidelity": fidelity_status(successful, required_fidelity_horizon),
    }


def compare_modes(
    baseline_mode: str,
    candidate_mode: str,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    required_fidelity_horizon: int | None,
) -> dict[str, Any]:
    if baseline is None or candidate is None:
        return {
            "baseline_mode": baseline_mode,
            "candidate_mode": candidate_mode,
            "comparison_status": "insufficient_data",
            "reason": "missing_baseline_or_candidate_mode",
        }
    if baseline["success_count"] == 0 or candidate["success_count"] == 0:
        return {
            "baseline_mode": baseline_mode,
            "candidate_mode": candidate_mode,
            "comparison_status": "insufficient_data",
            "reason": "missing_successful_baseline_or_candidate_run",
        }

    transfer_ratio = ratio(candidate["median_transfer_time_ms"], baseline["median_transfer_time_ms"])
    total_ratio = ratio(candidate["median_total_time_ms"], baseline["median_total_time_ms"])
    bandwidth_ratio = ratio(candidate["median_effective_bandwidth_gbps"], baseline["median_effective_bandwidth_gbps"])
    baseline_fidelity = baseline["fidelity"]
    candidate_fidelity = candidate["fidelity"]
    if required_fidelity_horizon and (
        baseline_fidelity["status"] != "verified" or candidate_fidelity["status"] != "verified"
    ):
        comparison_status = "performance_only"
    else:
        comparison_status = "comparable"

    return {
        "baseline_mode": baseline_mode,
        "candidate_mode": candidate_mode,
        "comparison_status": comparison_status,
        "baseline_fidelity_status": baseline_fidelity["status"],
        "candidate_fidelity_status": candidate_fidelity["status"],
        "fidelity_status": "verified"
        if baseline_fidelity["status"] == "verified" and candidate_fidelity["status"] == "verified"
        else candidate_fidelity["status"],
        "transfer_time_delta_ms": (
            candidate["median_transfer_time_ms"] - baseline["median_transfer_time_ms"]
            if candidate["median_transfer_time_ms"] is not None and baseline["median_transfer_time_ms"] is not None
            else None
        ),
        "transfer_time_ratio": transfer_ratio,
        "transfer_time_improvement_percent": (1.0 - transfer_ratio) * 100.0 if transfer_ratio is not None else None,
        "total_time_delta_ms": (
            candidate["median_total_time_ms"] - baseline["median_total_time_ms"]
            if candidate["median_total_time_ms"] is not None and baseline["median_total_time_ms"] is not None
            else None
        ),
        "total_time_ratio": total_ratio,
        "effective_bandwidth_ratio": bandwidth_ratio,
        "transferred_bytes_ratio": ratio(candidate["median_transferred_bytes"], baseline["median_transferred_bytes"]),
    }


def build_comparison(
    paths: list[Path],
    baseline_mode: str = "none",
    identity_fields: list[str] | None = None,
    required_fidelity_horizon: int | None = None,
) -> dict[str, Any]:
    fields = identity_fields or DEFAULT_IDENTITY_FIELDS
    loaded = []
    for path in paths:
        manifest = load_json(path)
        manifest["_source_path"] = str(path)
        loaded.append(manifest)

    grouped: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for manifest in loaded:
        grouped[group_key(manifest, fields)][quantization_mode(manifest)].append(manifest)

    groups = []
    for key in sorted(grouped, key=lambda item: tuple(str(part) for part in item)):
        modes = {
            mode: summarize_mode(manifests, required_fidelity_horizon)
            for mode, manifests in sorted(grouped[key].items())
        }
        comparisons = [
            compare_modes(baseline_mode, mode, modes.get(baseline_mode), summary, required_fidelity_horizon)
            for mode, summary in modes.items()
            if mode != baseline_mode
        ]
        groups.append(
            {
                "identity": dict(zip(fields, key, strict=True)),
                "modes": modes,
                "comparisons": comparisons,
            }
        )

    return {
        "schema_version": "permeantos-transfer-quantization-comparison-v0",
        "manifest_count": len(loaded),
        "baseline_mode": baseline_mode,
        "identity_fields": fields,
        "required_fidelity_horizon": required_fidelity_horizon,
        "groups": groups,
    }


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def markdown_table(summary: dict[str, Any]) -> str:
    lines = [
        "| Sequence length | Candidate | Status | Fidelity | Baseline transfer ms | Candidate transfer ms | Transfer delta ms | Transfer improvement % | Total ratio | Bandwidth ratio |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    baseline_mode = summary["baseline_mode"]
    for group in summary["groups"]:
        baseline = group["modes"].get(baseline_mode)
        for comparison in group["comparisons"]:
            candidate = group["modes"].get(comparison["candidate_mode"], {})
            lines.append(
                "| {sequence_length} | {candidate_mode} | {comparison_status} | {fidelity_status} | {baseline_transfer} | {candidate_transfer} | {transfer_delta} | {transfer_improvement} | {total_ratio} | {bandwidth_ratio} |".format(
                    sequence_length=format_value(group["identity"].get("sequence_length")),
                    candidate_mode=comparison["candidate_mode"],
                    comparison_status=comparison["comparison_status"],
                    fidelity_status=comparison.get("fidelity_status", ""),
                    baseline_transfer=format_value(baseline.get("median_transfer_time_ms") if baseline else None),
                    candidate_transfer=format_value(candidate.get("median_transfer_time_ms")),
                    transfer_delta=format_value(comparison.get("transfer_time_delta_ms")),
                    transfer_improvement=format_value(comparison.get("transfer_time_improvement_percent")),
                    total_ratio=format_value(comparison.get("total_time_ratio")),
                    bandwidth_ratio=format_value(comparison.get("effective_bandwidth_ratio")),
                )
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Manifest files or directories containing migration manifests.")
    parser.add_argument("--baseline-mode", default="none", help="Transfer quantization mode to treat as the baseline.")
    parser.add_argument(
        "--identity-fields",
        default=",".join(DEFAULT_IDENTITY_FIELDS),
        help="Comma-separated manifest fields that must match for paired comparison.",
    )
    parser.add_argument(
        "--require-fidelity-horizon",
        type=int,
        help="Require candidate manifests to carry fidelity horizon evidence at or above this token horizon.",
    )
    parser.add_argument("--markdown-out", type=Path, help="Optional path for a Markdown comparison table.")
    args = parser.parse_args()

    if args.require_fidelity_horizon is not None and args.require_fidelity_horizon <= 0:
        raise SystemExit("--require-fidelity-horizon must be positive")
    identity_fields = [field.strip() for field in args.identity_fields.split(",") if field.strip()]
    if not identity_fields:
        raise SystemExit("--identity-fields must contain at least one field")

    summary = build_comparison(
        discover_manifest_paths(args.inputs),
        baseline_mode=args.baseline_mode,
        identity_fields=identity_fields,
        required_fidelity_horizon=args.require_fidelity_horizon,
    )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown_table(summary))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

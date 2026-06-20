#!/usr/bin/env python3
"""Plan adaptive KV transfer codec experiments and safe fallbacks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, NamedTuple


DEFAULT_PREFERENCE_ORDER = ["qatq", "turboquant", "fp8", "raw"]


class CodecDefinition(NamedTuple):
    name: str
    label: str
    reversible: bool
    loss_semantics: str
    bytes_per_element: float
    runner_supported: bool
    fidelity_required: bool
    manifest_value: str
    notes: str


CODECS: dict[str, CodecDefinition] = {
    "raw": CodecDefinition(
        name="raw",
        label="Raw f32 transfer",
        reversible=True,
        loss_semantics="reversible",
        bytes_per_element=4.0,
        runner_supported=True,
        fidelity_required=False,
        manifest_value="none",
        notes="Current unquantized transfer path. Highest bandwidth cost, lowest codec risk.",
    ),
    "fp8": CodecDefinition(
        name="fp8",
        label="Scaled FP8 E4M3 transfer",
        reversible=False,
        loss_semantics="lossy_quantized",
        bytes_per_element=1.0,
        runner_supported=True,
        fidelity_required=True,
        manifest_value="fp8",
        notes="Current lossy transfer quantization path. Requires fidelity evidence for claims.",
    ),
    "turboquant": CodecDefinition(
        name="turboquant",
        label="TurboQuant-style candidate",
        reversible=False,
        loss_semantics="lossy_experimental_candidate",
        bytes_per_element=0.5,
        runner_supported=False,
        fidelity_required=True,
        manifest_value="turboquant",
        notes="Planning placeholder for future codec experiments; not executable by the current runner.",
    ),
    "qatq": CodecDefinition(
        name="qatq",
        label="Quaternion-Augmented TurboQuant candidate",
        reversible=False,
        loss_semantics="lossy_experimental_candidate",
        bytes_per_element=0.5,
        runner_supported=False,
        fidelity_required=True,
        manifest_value="qatq",
        notes="Planning placeholder for future quaternion-augmented codec experiments; not executable by the current runner.",
    ),
}


def parse_codec_list(value: str) -> list[str]:
    aliases = {
        "none": "raw",
        "unquantized": "raw",
        "quaternion-augmented-turboquant": "qatq",
        "quaternion_augmented_turboquant": "qatq",
        "quaternion_turboquant": "qatq",
    }
    codecs = []
    for item in value.split(","):
        key = item.strip().lower()
        if not key:
            continue
        key = aliases.get(key, key)
        if key not in CODECS:
            raise ValueError(f"unsupported codec: {item}")
        codecs.append(key)
    if not codecs:
        raise ValueError("at least one codec is required")
    return sorted(set(codecs), key=codecs.index)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def kv_bytes(seq_len: int, n_layers: int, n_kv_heads: int, head_dim: int, bytes_per_element: float) -> int:
    return int(n_layers * 2 * n_kv_heads * head_dim * seq_len * bytes_per_element)


def transfer_time_seconds(bytes_count: int, network_bandwidth_bps: float, protocol_overhead_secs: float) -> float:
    return ((bytes_count * 8) / network_bandwidth_bps) + protocol_overhead_secs


def prefill_time_seconds(seq_len: int) -> float:
    seq_len_f = float(seq_len)
    return (seq_len_f * 1e-5) + (seq_len_f**2 * 6e-10)


def runner_env(codec: CodecDefinition, seq_len: int) -> dict[str, str] | None:
    if not codec.runner_supported:
        return None
    return {
        "PERMEANT_SEQ_LEN": str(seq_len),
        "PERMEANT_TRANSFER_QUANTIZATION": codec.manifest_value,
    }


def build_plan(
    sequence_lengths: list[int],
    source_codecs: list[str],
    target_codecs: list[str],
    preference_order: list[str],
    n_layers: int,
    n_kv_heads: int,
    head_dim: int,
    network_bandwidth_bps: float,
    protocol_overhead_secs: float,
    require_runner_supported: bool,
) -> dict[str, Any]:
    source_supported = set(source_codecs)
    target_supported = set(target_codecs)
    catalog = {name: codec._asdict() for name, codec in CODECS.items()}
    points = []

    for seq_len in sequence_lengths:
        prefill_secs = prefill_time_seconds(seq_len)
        candidates = []
        for codec_name in preference_order:
            codec = CODECS[codec_name]
            source_ok = codec_name in source_supported
            target_ok = codec_name in target_supported
            capability_supported = source_ok and target_ok
            executable = capability_supported and (codec.runner_supported or not require_runner_supported)
            estimated_bytes = kv_bytes(seq_len, n_layers, n_kv_heads, head_dim, codec.bytes_per_element)
            estimated_transfer_secs = transfer_time_seconds(
                estimated_bytes,
                network_bandwidth_bps=network_bandwidth_bps,
                protocol_overhead_secs=protocol_overhead_secs,
            )
            candidate = {
                "codec": codec.name,
                "label": codec.label,
                "capability_supported": capability_supported,
                "source_supported": source_ok,
                "target_supported": target_ok,
                "runner_supported": codec.runner_supported,
                "executable": executable,
                "reversible": codec.reversible,
                "loss_semantics": codec.loss_semantics,
                "fidelity_required": codec.fidelity_required,
                "estimated_bytes": estimated_bytes,
                "estimated_transfer_time_secs": estimated_transfer_secs,
                "estimated_transfer_vs_prefill_ratio": estimated_transfer_secs / prefill_secs if prefill_secs else None,
                "manifest_transfer_quantization": codec.manifest_value,
                "runner_env": runner_env(codec, seq_len) if capability_supported and codec.runner_supported else None,
                "notes": codec.notes,
            }
            if not capability_supported:
                candidate["rejection_reason"] = "not_supported_by_source_and_target"
            elif require_runner_supported and not codec.runner_supported:
                candidate["rejection_reason"] = "not_supported_by_current_runner"
            else:
                candidate["rejection_reason"] = None
            candidates.append(candidate)

        selected = next((candidate for candidate in candidates if candidate["executable"]), None)
        fallback_action = None
        if selected and selected["codec"] == "raw" and any(
            candidate["codec"] != "raw" and candidate["rejection_reason"] is not None
            for candidate in candidates[: candidates.index(selected)]
        ):
            fallback_action = "fallback_raw_transfer"
        elif selected is None:
            raw = next((candidate for candidate in candidates if candidate["codec"] == "raw"), None)
            if raw and raw["capability_supported"] and raw["runner_supported"]:
                selected = raw
                fallback_action = "fallback_raw_transfer"
            else:
                fallback_action = "fallback_re_prefill"

        points.append(
            {
                "sequence_length": seq_len,
                "prefill_time_secs": prefill_secs,
                "selected_codec": selected["codec"] if selected else None,
                "selected_manifest_transfer_quantization": selected["manifest_transfer_quantization"] if selected else None,
                "fallback_action": fallback_action,
                "requires_fidelity_evidence": bool(selected and selected["fidelity_required"]),
                "candidates": candidates,
            }
        )

    return {
        "schema_version": "permeantos-transfer-codec-plan-v0",
        "source_supported_codecs": source_codecs,
        "target_supported_codecs": target_codecs,
        "preference_order": preference_order,
        "require_runner_supported": require_runner_supported,
        "network_bandwidth_bps": network_bandwidth_bps,
        "protocol_overhead_secs": protocol_overhead_secs,
        "model_shape": {
            "n_layers": n_layers,
            "n_kv_heads": n_kv_heads,
            "head_dim": head_dim,
        },
        "codec_catalog": catalog,
        "points": points,
    }


def markdown_table(plan: dict[str, Any]) -> str:
    lines = [
        "| Seq len | Selected codec | Fallback | Fidelity evidence | Estimated transfer secs | Transfer/prefill ratio | Runner env quantization |",
        "| ---: | --- | --- | --- | ---: | ---: | --- |",
    ]
    for point in plan["points"]:
        selected = next(
            (candidate for candidate in point["candidates"] if candidate["codec"] == point["selected_codec"]),
            None,
        )
        env_quant = ""
        transfer_secs = ""
        ratio = ""
        if selected:
            transfer_secs = f"{selected['estimated_transfer_time_secs']:.4g}"
            ratio_value = selected["estimated_transfer_vs_prefill_ratio"]
            ratio = f"{ratio_value:.4g}" if ratio_value is not None else ""
            env = selected.get("runner_env") or {}
            env_quant = env.get("PERMEANT_TRANSFER_QUANTIZATION", "")
        lines.append(
            "| {seq_len} | {codec} | {fallback} | {fidelity} | {transfer_secs} | {ratio} | {env_quant} |".format(
                seq_len=point["sequence_length"],
                codec=point["selected_codec"] or "re_prefill",
                fallback=point["fallback_action"] or "",
                fidelity=str(point["requires_fidelity_evidence"]),
                transfer_secs=transfer_secs,
                ratio=ratio,
                env_quant=env_quant,
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seq-lens", default="4096,8192,16384,32768")
    parser.add_argument("--source-codecs", default="raw,fp8")
    parser.add_argument("--target-codecs", default="raw,fp8")
    parser.add_argument("--preference-order", default=",".join(DEFAULT_PREFERENCE_ORDER))
    parser.add_argument("--n-layers", type=positive_int, default=24)
    parser.add_argument("--n-kv-heads", type=positive_int, default=2)
    parser.add_argument("--head-dim", type=positive_int, default=64)
    parser.add_argument("--network-bandwidth-bps", type=positive_float, default=25_000_000_000.0)
    parser.add_argument("--protocol-overhead-secs", type=float, default=0.15)
    parser.add_argument(
        "--allow-unimplemented-codecs",
        action="store_true",
        help="Allow candidate codecs that are capability-supported but not executable by the current runner.",
    )
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.protocol_overhead_secs < 0:
        raise SystemExit("--protocol-overhead-secs must be zero or positive")

    plan = build_plan(
        sequence_lengths=parse_int_list(args.seq_lens),
        source_codecs=parse_codec_list(args.source_codecs),
        target_codecs=parse_codec_list(args.target_codecs),
        preference_order=parse_codec_list(args.preference_order),
        n_layers=args.n_layers,
        n_kv_heads=args.n_kv_heads,
        head_dim=args.head_dim,
        network_bandwidth_bps=args.network_bandwidth_bps,
        protocol_overhead_secs=args.protocol_overhead_secs,
        require_runner_supported=not args.allow_unimplemented_codecs,
    )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown_table(plan))
    print(json.dumps(plan, indent=2 if args.pretty else None, sort_keys=True))


def parse_int_list(value: str) -> list[int]:
    values = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        parsed = int(item)
        if parsed <= 0:
            raise ValueError("sequence lengths must be positive")
        values.append(parsed)
    if not values:
        raise ValueError("at least one sequence length is required")
    return sorted(set(values))


if __name__ == "__main__":
    main()

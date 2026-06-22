#!/usr/bin/env python3
"""Generate PermeantOS public evidence index records.

The evidence index is a curated, machine-readable map from public claims to
versioned proof reports, validation commands, and claim boundaries. It is
intentionally explicit rather than inferred from Markdown headings: broadening a
public claim should be a reviewed source change.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-evidence-index-v0"
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    title: str
    claim: str
    status: str
    model: str
    model_family: str
    source_runtime: str
    target_runtime: str
    transport: str
    transfer_mode: str
    horizon_tokens: int | None
    proof_reports: tuple[str, ...]
    commands: tuple[str, ...]
    ci_jobs: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


EVIDENCE: tuple[EvidenceRecord, ...] = (
    EvidenceRecord(
        id="qwen25-mlx-vllm-aws-standalone-qatq-compression-roundtrip",
        title="Qwen2.5 MLX to AWS vLLM standalone QATQ compression round trip",
        claim=(
            "Live Qwen2.5 KV state migrated from local MLX to AWS vLLM over "
            "production WSS/mTLS using the standalone QATQ crate, exact "
            "128-token continuation fidelity, a passing QATQ <= raw/zstd/lz4 "
            "live compression gate on streamed block artifacts, complex Agent "
            "Memory Graph target activity, reverse runtime import, and origin "
            "return-home continuation."
        ),
        status="validated-real-runtime",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="vllm",
        transport="production-wss-mtls",
        transfer_mode="standalone-qatq-exact",
        horizon_tokens=128,
        proof_reports=(
            "docs/aws-real-runtime-qatq-standalone-compression-2026-06-22.md",
            "docs/qatq-permeantos-feedback-2026-06-22.md",
        ),
        commands=(
            "PERMEANT_TRANSFER_QUANTIZATION=qatq PERMEANT_QATQ_STANDALONE_PATH=/Users/kabudu/projex/qatq PERMEANT_SEQ_LEN=1920 PERMEANT_CONTINUATION_MAX_TOKENS=128 scripts/aws-real-runtime-e2e.sh run",
        ),
        ci_jobs=(
            "PR CI / Python tests / Run AWS E2E preflight smoke test",
            "PR CI / Python tests / Run Python tests",
        ),
        limitations=(
            "This validates the recorded Qwen2.5 MLX-to-vLLM AWS path; additional models and runtime adapters still need standalone-QATQ live validation.",
            "PermeantOS currently consumes the sibling QATQ checkout by path for local/AWS validation until the QATQ API freeze and package decision are complete.",
            "The vLLM adapter relies on runtime internals that may change between vLLM versions.",
        ),
    ),
    EvidenceRecord(
        id="qwen25-mlx-vllm-aws-qatq-exact-complex-roundtrip",
        title="Qwen2.5 MLX to AWS vLLM QATQ exact complex round trip",
        claim=(
            "Live Qwen2.5 KV state migrated from local MLX to AWS vLLM over "
            "production WSS/mTLS with every transfer chunk using the QATQ exact "
            "container path, exact 128-token continuation fidelity, complex "
            "Agent Memory Graph target activity, reverse runtime import, and "
            "origin return-home continuation."
        ),
        status="validated-real-runtime",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="vllm",
        transport="production-wss-mtls",
        transfer_mode="qatq-exact-f32le",
        horizon_tokens=128,
        proof_reports=(
            "docs/aws-real-runtime-qatq-exact-complex-2026-06-22.md",
            "docs/qatq-permeantos-feedback-2026-06-22.md",
        ),
        commands=(
            "PERMEANT_TRANSFER_QUANTIZATION=qatq PERMEANT_SEQ_LEN=1920 PERMEANT_CONTINUATION_MAX_TOKENS=128 scripts/aws-real-runtime-e2e.sh run",
        ),
        ci_jobs=(
            "PR CI / Python tests / Run AWS E2E preflight smoke test",
            "PR CI / Python tests / Run Python tests",
        ),
        limitations=(
            "The current exact QATQ compatibility path is lossless but not size-reducing; the recorded run transferred about 6.7% more bytes than raw due to container overhead.",
            "PermeantOS still needs to switch from the in-tree compatibility shim to the standalone QATQ crate once the QATQ API and lossless compression path are ready.",
            "The vLLM adapter relies on runtime internals that may change between vLLM versions.",
        ),
    ),
    EvidenceRecord(
        id="qwen25-mlx-kv-standalone-qatq-compression-gate",
        title="Qwen2.5 MLX full-KV standalone QATQ compression gate",
        claim=(
            "A full 1,920-token Qwen2.5 MLX KV bundle with all 24 key/value "
            "layers was exported as raw f32 little-endian bytes, compressed "
            "with the standalone QATQ crate, restored byte-for-byte, and "
            "benchmarked against raw, zstd, and lz4 on the same packed bundle."
        ),
        status="validated-local-compression",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="none",
        transport="local-files",
        transfer_mode="standalone-qatq-exact-container",
        horizon_tokens=None,
        proof_reports=(
            "docs/qatq-standalone-compression-gate-2026-06-22.md",
            "docs/qatq-permeantos-feedback-2026-06-22.md",
        ),
        commands=(
            "scripts/export-qatq-captures.py --model Qwen/Qwen2.5-0.5B-Instruct --seq-lens 1920 --layer-points 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 --tensor-roles key,value",
            "/Users/kabudu/projex/qatq/target/debug/qatq-bench --no-synthetic --exact-only --gate-policy competitive-compression --input permeantos-qwen25-1920-full-kv:<packed-bundle.f32le>",
            "/Users/kabudu/projex/qatq/target/debug/qatq encode-chunked --max-values-per-chunk 65536 --dtype f32 <packed-bundle.f32le> <packed-bundle.qatc>",
            "/Users/kabudu/projex/qatq/target/debug/qatq decode <packed-bundle.qatc> <decoded.f32le> && cmp <packed-bundle.f32le> <decoded.f32le>",
        ),
        ci_jobs=(),
        limitations=(
            "This is a local standalone compression proof, not yet a live AWS migration proof using the standalone QATQ crate.",
            "The live PermeantOS migration path still needs to replace the in-tree compatibility container with the pinned standalone QATQ crate.",
            "The timing numbers were captured from a local debug build and should not be treated as final release-performance figures.",
        ),
    ),
    EvidenceRecord(
        id="qwen25-mlx-vllm-aws-long-horizon-roundtrip",
        title="Qwen2.5 MLX to AWS vLLM long-horizon round trip",
        claim=(
            "Live Qwen2.5 KV state and a 27-node Agent Memory Graph migrated "
            "from local MLX to AWS vLLM, continued on the target, exported a "
            "target-advanced runtime boundary, returned graph/artifact evidence "
            "to the origin, and continued from that returned proof."
        ),
        status="validated-real-runtime",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="vllm",
        transport="production-wss-mtls",
        transfer_mode="qatq-historical-experimental",
        horizon_tokens=128,
        proof_reports=(
            "docs/aws-real-runtime-long-horizon-2026-06-21.md",
            "docs/aws-real-runtime-roundtrip-continuation-2026-06-20.md",
            "docs/aws-real-runtime-production-transport-2026-06-20.md",
        ),
        commands=(
            "scripts/plan-model-runtime-validations.py --profile qwen2.5-0.5b-long-horizon-aws --format shell --action preflight",
            "scripts/plan-model-runtime-validations.py --profile qwen2.5-0.5b-long-horizon-aws --format shell --action run",
        ),
        ci_jobs=(
            "PR CI / Python tests / Run AWS E2E preflight smoke test",
            "PR CI / Python tests / Run Python tests",
        ),
        limitations=(
            "QATQ was lossy at sampled tensor slots; the validated claim is behavioral/decode fidelity, not numerical losslessness.",
            "The vLLM adapter relies on runtime internals that may change between vLLM versions.",
            "The 128-token horizon applies to the recorded model, runtime, transport, and hardware profile.",
        ),
    ),
    EvidenceRecord(
        id="tinyllama-mlx-vllm-aws-raw-structural",
        title="TinyLlama MLX to AWS vLLM raw-transfer structural E2E",
        claim=(
            "A non-Qwen Llama-family model completed raw-transfer MLX-to-vLLM "
            "structural migration with exact target-baseline/post-migration "
            "continuation, reverse import, target graph activity, origin "
            "return-home continuation, and cleanup evidence."
        ),
        status="validated-structural-e2e",
        model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        model_family="llama",
        source_runtime="mlx",
        target_runtime="vllm",
        transport="production-wss-mtls",
        transfer_mode="raw-f32",
        horizon_tokens=16,
        proof_reports=("docs/aws-real-runtime-tinyllama-2026-06-21.md",),
        commands=(
            "scripts/plan-model-runtime-validations.py --profile tinyllama-1.1b-chat-mlx-vllm --format shell --action preflight",
            "scripts/plan-model-runtime-validations.py --profile tinyllama-1.1b-chat-mlx-vllm --format shell --action run",
        ),
        ci_jobs=("PR CI / Python tests / Run AWS E2E preflight smoke test",),
        limitations=(
            "Source-exact MLX/vLLM parity is not claimed for this profile because the recorded run diverged at a leading-space token boundary.",
            "The validated decode claim is target-baseline/post-migration exactness at 16 tokens.",
        ),
    ),
    EvidenceRecord(
        id="qwen25-mlx-llamacpp-canonical-kv-feed",
        title="Qwen2.5 MLX to llama.cpp canonical KV feed",
        claim=(
            "Canonical f32 K/V tensors exported from live MLX were written "
            "directly into llama.cpp internal KV memory with tokenizer/span "
            "alignment, and llama.cpp matched the MLX source continuation at "
            "the aligned decode boundary."
        ),
        status="validated-local-runtime",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="llama.cpp",
        transport="local-files",
        transfer_mode="raw-f32",
        horizon_tokens=8,
        proof_reports=(
            "docs/llama-cpp-cross-runtime-canonical-kv-proof-2026-06-21.md",
            "docs/llama-cpp-raw-kv-internal-write-proof-2026-06-21.md",
            "docs/llama-cpp-live-state-binding-proof-2026-06-21.md",
        ),
        commands=(
            "scripts/export-mlx-canonical-kv-for-llamacpp.py --model Qwen/Qwen2.5-0.5B-Instruct --seq-len 17 --continuation-tokens 8 --output-dir /private/tmp/permeant-cross-runtime-llamacpp/qwen25-mlx-seq17",
            "target/llamacpp_raw_kv_bridge --external-kv-manifest /private/tmp/permeant-cross-runtime-llamacpp/qwen25-mlx-seq17/mlx-to-llamacpp-canonical-kv.tsv --n-predict 8",
        ),
        ci_jobs=("PR CI / Python tests / Run Python tests",),
        limitations=(
            "This is a local proof, not an AWS cloud migration proof.",
            "The raw writer uses llama.cpp private headers matched to the recorded llama.cpp revision.",
            "Broader llama.cpp claims still need longer-horizon and additional model-family validation.",
        ),
    ),
    EvidenceRecord(
        id="agent-memory-graph-v0-schema",
        title="Agent Memory Graph v0 schema and conformance",
        claim=(
            "The Agent Memory Graph v0 schema represents conversation, tools, "
            "artifacts, retrieval memory, pending actions, provenance, and KV "
            "token-span bindings with deterministic local validation."
        ),
        status="validated-ci",
        model="runtime-neutral",
        model_family="runtime-neutral",
        source_runtime="agent-memory-graph",
        target_runtime="agent-memory-graph",
        transport="schema",
        transfer_mode="not-applicable",
        horizon_tokens=None,
        proof_reports=(
            "docs/agent-memory-graph.md",
            "docs/agent-framework-adapters.md",
            "docs/agent-memory-graph-threat-model.md",
        ),
        commands=("python -m pytest tests/test_agent_memory_graph_schema.py tests/test_agent_memory_graph_harness.py tests/test_agent_framework_adapters.py",),
        ci_jobs=("PR CI / Python tests / Run Python tests",),
        limitations=(
            "The graph schema is versioned as v0 and remains pre-1.0.",
            "Runtime-specific adapters must still prove their own export/import and side-effect policies.",
        ),
    ),
)


def validate_records(records: tuple[EvidenceRecord, ...]) -> None:
    ids = [record.id for record in records]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise SystemExit(f"duplicate evidence id(s): {', '.join(duplicates)}")

    for record in records:
        if not record.proof_reports:
            raise SystemExit(f"{record.id}: at least one proof report is required")
        for relative in record.proof_reports:
            path = ROOT / relative
            if not path.is_file():
                raise SystemExit(f"{record.id}: missing proof report {relative}")
        if record.horizon_tokens is not None and record.horizon_tokens <= 0:
            raise SystemExit(f"{record.id}: horizon_tokens must be positive when set")
        if not record.limitations:
            raise SystemExit(f"{record.id}: limitations are required for bounded public claims")


def build_index(records: tuple[EvidenceRecord, ...]) -> dict[str, Any]:
    validate_records(records)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_count": len(records),
        "records": [record.to_json() for record in records],
    }


def markdown(index: dict[str, Any]) -> str:
    lines = [
        "# PermeantOS Evidence Index",
        "",
        "This index maps public PermeantOS claims to proof reports, repeatable commands, CI jobs, and known limitations.",
        "",
        f"Schema version: `{index['schema_version']}`",
        "",
        "| Claim | Status | Runtime path | Evidence | Limitations |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in index["records"]:
        reports = "<br>".join(f"`{path}`" for path in record["proof_reports"])
        limitations = "<br>".join(record["limitations"])
        runtime_path = f"{record['source_runtime']} -> {record['target_runtime']}"
        lines.append(
            "| {title} | `{status}` | {runtime_path} | {reports} | {limitations} |".format(
                title=record["title"],
                status=record["status"],
                runtime_path=runtime_path,
                reports=reports,
                limitations=limitations,
            )
        )
    lines.extend(
        [
            "",
            "## Regenerate",
            "",
            "```bash",
            "scripts/generate-evidence-index.py --json-out docs/evidence-index.json --markdown-out docs/evidence-index.md",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, help="Write the evidence index JSON to this path.")
    parser.add_argument("--markdown-out", type=Path, help="Write the evidence index Markdown table to this path.")
    args = parser.parse_args()

    index = build_index(EVIDENCE)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown(index))
    if not args.json_out and not args.markdown_out:
        print(json.dumps(index, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

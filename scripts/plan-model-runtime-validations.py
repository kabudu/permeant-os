#!/usr/bin/env python3
"""Plan real-runtime validation runs across model families and runtimes."""

from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ValidationProfile:
    name: str
    model: str
    model_family: str
    source_runtime: str
    target_runtime: str
    seq_len: int
    max_model_len: int
    continuation_tokens: int
    fidelity_horizons: str
    instance_type: str
    transfer_quantization: str
    layer_count: int
    q_heads: int
    kv_heads: int
    head_dim: int
    hidden_size: int
    block_size: int
    maturity: str
    notes: str

    def env(self) -> dict[str, str]:
        return {
            "AWS_INSTANCE_TYPE": self.instance_type,
            "PERMEANT_VALIDATION_PROFILE": self.name,
            "PERMEANT_MODEL": self.model,
            "PERMEANT_MODEL_FAMILY": self.model_family,
            "PERMEANT_SOURCE_RUNTIME": self.source_runtime,
            "PERMEANT_TARGET_RUNTIME": self.target_runtime,
            "PERMEANT_SEQ_LEN": str(self.seq_len),
            "PERMEANT_VLLM_MAX_MODEL_LEN": str(self.max_model_len),
            "PERMEANT_CONTINUATION_MAX_TOKENS": str(self.continuation_tokens),
            "PERMEANT_FIDELITY_HORIZONS": self.fidelity_horizons,
            "PERMEANT_TRANSFER_QUANTIZATION": self.transfer_quantization,
            "PERMEANT_MODEL_LAYER_COUNT": str(self.layer_count),
            "PERMEANT_MODEL_Q_HEADS": str(self.q_heads),
            "PERMEANT_MODEL_KV_HEADS": str(self.kv_heads),
            "PERMEANT_MODEL_HEAD_DIM": str(self.head_dim),
            "PERMEANT_MODEL_HIDDEN_SIZE": str(self.hidden_size),
            "PERMEANT_MODEL_BLOCK_SIZE": str(self.block_size),
            "PERMEANT_MIGRATION_TRANSPORT": "production-wss",
            "PERMEANT_REVERSE_RUNTIME_IMPORT": "1",
            "PERMEANT_AGENT_ACTIVITY_RESUME": "1",
            "PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH": "1",
            "PERMEANT_AGENT_ACTIVITY_RETURN_HOME": "1",
        }

    def command(self, action: str) -> str:
        assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in self.env().items())
        return f"{assignments} scripts/aws-real-runtime-e2e.sh {action}"


PROFILES: tuple[ValidationProfile, ...] = (
    ValidationProfile(
        name="qwen2.5-0.5b-mlx-vllm",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="vllm",
        seq_len=2016,
        max_model_len=2048,
        continuation_tokens=16,
        fidelity_horizons="16,32,64,128",
        instance_type="g4dn.xlarge",
        transfer_quantization="qatq",
        layer_count=24,
        q_heads=14,
        kv_heads=2,
        head_dim=64,
        hidden_size=896,
        block_size=256,
        maturity="validated",
        notes="Current production WSS/QATQ round-trip proof baseline.",
    ),
    ValidationProfile(
        name="qwen2.5-1.5b-mlx-vllm",
        model="Qwen/Qwen2.5-1.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="vllm",
        seq_len=1984,
        max_model_len=2048,
        continuation_tokens=16,
        fidelity_horizons="16,32,64,128",
        instance_type="g4dn.xlarge",
        transfer_quantization="none",
        layer_count=28,
        q_heads=12,
        kv_heads=2,
        head_dim=128,
        hidden_size=1536,
        block_size=256,
        maturity="next-same-family",
        notes="Same family, larger model; uses raw transfer while QATQ is perfected separately and a 1984-token prefix to preserve continuation headroom.",
    ),
    ValidationProfile(
        name="qwen2.5-0.5b-long-horizon-aws",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_family="qwen2.5",
        source_runtime="mlx",
        target_runtime="vllm",
        seq_len=1920,
        max_model_len=2048,
        continuation_tokens=128,
        fidelity_horizons="16,32,64,128",
        instance_type="g4dn.xlarge",
        transfer_quantization="qatq",
        layer_count=24,
        q_heads=14,
        kv_heads=2,
        head_dim=64,
        hidden_size=896,
        block_size=256,
        maturity="validated-long-horizon-aws",
        notes="Validated AWS confirmation profile for 128-token continuation fidelity with production transport.",
    ),
    ValidationProfile(
        name="tinyllama-1.1b-chat-mlx-vllm",
        model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        model_family="llama",
        source_runtime="mlx",
        target_runtime="vllm",
        seq_len=1984,
        max_model_len=2048,
        continuation_tokens=16,
        fidelity_horizons="16,32,64,128",
        instance_type="g4dn.xlarge",
        transfer_quantization="none",
        layer_count=22,
        q_heads=32,
        kv_heads=4,
        head_dim=64,
        hidden_size=2048,
        block_size=256,
        maturity="validated-structural-e2e",
        notes="Validated Llama-family raw-transfer structural E2E path; target baseline/post-migration continuation is exact, while source-exact cross-runtime parity remains unclaimed.",
    ),
    ValidationProfile(
        name="gemma-2-2b-it-mlx-vllm",
        model="google/gemma-2-2b-it",
        model_family="gemma2",
        source_runtime="mlx",
        target_runtime="vllm",
        seq_len=2016,
        max_model_len=2048,
        continuation_tokens=16,
        fidelity_horizons="16,32,64,128",
        instance_type="g4dn.xlarge",
        transfer_quantization="none",
        layer_count=26,
        q_heads=8,
        kv_heads=4,
        head_dim=256,
        hidden_size=2304,
        block_size=256,
        maturity="candidate-new-family",
        notes="New model family candidate; uses raw transfer while QATQ is perfected separately.",
    ),
    ValidationProfile(
        name="phi-3.5-mini-mlx-vllm",
        model="microsoft/Phi-3.5-mini-instruct",
        model_family="phi3.5",
        source_runtime="mlx",
        target_runtime="vllm",
        seq_len=2016,
        max_model_len=2048,
        continuation_tokens=16,
        fidelity_horizons="16,32,64,128",
        instance_type="g4dn.xlarge",
        transfer_quantization="none",
        layer_count=32,
        q_heads=32,
        kv_heads=32,
        head_dim=96,
        hidden_size=3072,
        block_size=256,
        maturity="candidate-new-family",
        notes="New model family candidate; may need a larger target or shorter context depending on vLLM memory pressure and uses raw transfer while QATQ is perfected separately.",
    ),
)


def selected_profiles(names: list[str]) -> list[ValidationProfile]:
    by_name = {profile.name: profile for profile in PROFILES}
    if not names:
        return list(PROFILES)
    missing = [name for name in names if name not in by_name]
    if missing:
        raise SystemExit(f"unknown validation profile(s): {', '.join(missing)}")
    return [by_name[name] for name in names]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", action="append", default=[], help="profile name to include; may be repeated")
    parser.add_argument("--format", choices=("json", "shell"), default="json")
    parser.add_argument("--action", choices=("preflight", "run"), default="preflight")
    args = parser.parse_args()

    profiles = selected_profiles(args.profile)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema_version": "permeantos-model-runtime-validation-plan-v0",
                    "profiles": [
                        {
                            **asdict(profile),
                            "env": profile.env(),
                            "command": profile.command(args.action),
                        }
                        for profile in profiles
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for profile in profiles:
            print(profile.command(args.action))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

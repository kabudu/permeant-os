#!/usr/bin/env python3
"""Run repeatable PermeantOS evidence jobs for CI and manual validation.

The default mode is deliberately non-provisioning: it produces evidence reports
without touching cloud resources. Real AWS runtime migration is only available
through an explicit mode so scheduled or PR jobs cannot spend money by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-evidence-job-v0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "dist" / "evidence"
NON_PROVISIONING_TESTS = (
    "tests/test_agent_framework_adapters.py",
    "tests/test_runtime_adapters.py",
    "tests/test_pytorch_runtime_adapter.py",
    "tests/test_llamacpp_runtime_adapter.py",
    "tests/test_generate_evidence_index.py",
    "tests/test_plan_model_runtime_validations.py",
    "tests/test_aws_real_runtime_e2e_preflight.py",
    "tests/test_package_readiness.py",
)
SOCKET_TESTS = ("tests/test_runtime_http_bridge.py",)


@dataclass(frozen=True)
class StepResult:
    name: str
    command: list[str]
    returncode: int
    stdout_path: Path
    stderr_path: Path

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_json(self, out_dir: Path) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "ok": self.ok,
            "stdout": str(self.stdout_path.relative_to(out_dir)),
            "stderr": str(self.stderr_path.relative_to(out_dir)),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_step(name: str, command: list[str], out_dir: Path, *, env: dict[str, str] | None = None) -> StepResult:
    safe_name = name.replace(" ", "-").replace("/", "-")
    stdout_path = out_dir / f"{safe_name}.stdout.txt"
    stderr_path = out_dir / f"{safe_name}.stderr.txt"
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return StepResult(name, command, result.returncode, stdout_path, stderr_path)


def write_report(out_dir: Path, mode: str, steps: list[StepResult], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "generated_at": utc_now(),
        "ok": all(step.ok for step in steps),
        "steps": [step.to_json(out_dir) for step in steps],
        "cloud_resources_created": False,
        "cleanup_required": False,
    }
    if extra:
        report.update(extra)
    report_path = out_dir / "evidence-job-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def non_provisioning(out_dir: Path) -> dict[str, Any]:
    steps: list[StepResult] = []
    python = sys.executable
    evidence_tests = list(NON_PROVISIONING_TESTS)
    include_socket_tests = os.getenv("PERMEANT_EVIDENCE_INCLUDE_SOCKET_TESTS", "1") != "0"
    if include_socket_tests:
        evidence_tests.extend(SOCKET_TESTS)

    steps.append(run_step("adapter-and-evidence-tests", [python, "-m", "pytest", *evidence_tests], out_dir))
    steps.append(
        run_step(
            "generate-evidence-index",
            [
                str(ROOT / "scripts" / "generate-evidence-index.py"),
                "--json-out",
                str(out_dir / "evidence-index.json"),
                "--markdown-out",
                str(out_dir / "evidence-index.md"),
            ],
            out_dir,
        )
    )
    steps.append(
        run_step(
            "plan-model-runtime-validations",
            [
                str(ROOT / "scripts" / "plan-model-runtime-validations.py"),
                "--format",
                "json",
            ],
            out_dir,
        )
    )
    steps.append(
        run_step(
            "aws-preflight-non-provisioning",
            [str(ROOT / "scripts" / "aws-real-runtime-e2e.sh"), "preflight"],
            out_dir,
            env={
                **os.environ,
                "PERMEANT_STATE_DIR": str(out_dir / "aws-preflight-state"),
                "PERMEANT_PREFLIGHT_SKIP_AWS": "1",
                "PERMEANT_PREFLIGHT_SKIP_BUILD": "1",
                "PERMEANT_PREFLIGHT_SKIP_SOURCE": "1",
            },
        )
    )
    steps.append(
        run_step(
            "package-readiness",
            [
                str(ROOT / "scripts" / "check-package-readiness.py"),
                "--json-out",
                str(out_dir / "package-readiness.json"),
            ],
            out_dir,
        )
    )
    return write_report(
        out_dir,
        "non-provisioning",
        steps,
        {
            "claim_boundary": "No cloud resources are created. AWS, local build, and live source-runtime checks are recorded as skipped in the AWS preflight report.",
            "socket_tests_included": include_socket_tests,
        },
    )


def aws_real_runtime(out_dir: Path, *, confirm: str, profile: str) -> dict[str, Any]:
    if confirm != "RUN_AWS_REAL_RUNTIME":
        raise SystemExit("aws-real-runtime mode requires --confirm RUN_AWS_REAL_RUNTIME")
    steps = [
        run_step(
            "aws-real-runtime-run",
            [str(ROOT / "scripts" / "aws-real-runtime-e2e.sh"), "run"],
            out_dir,
            env={
                **os.environ,
                "PERMEANT_STATE_DIR": str(out_dir / "aws-state"),
                "PERMEANT_VALIDATION_PROFILE": profile,
            },
        )
    ]
    report = write_report(
        out_dir,
        "aws-real-runtime",
        steps,
        {
            "cloud_resources_created": True,
            "cleanup_required": not steps[0].ok,
            "validation_profile": profile,
            "claim_boundary": "This mode can provision AWS resources. It must run only from a manually approved environment with AWS credentials, a live source runtime, and cleanup verification.",
        },
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("non-provisioning", "aws-real-runtime"), default="non-provisioning")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--profile", default="qwen2.5-0.5b-mlx-vllm")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "non-provisioning":
        report = non_provisioning(args.out_dir)
    else:
        report = aws_real_runtime(args.out_dir, confirm=args.confirm, profile=args.profile)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run PermeantOS runtime and framework adapter conformance checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "permeantos-adapter-conformance-v0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "dist" / "adapter-conformance"
TESTS = (
    "tests/test_runtime_adapters.py",
    "tests/test_pytorch_runtime_adapter.py",
    "tests/test_llamacpp_runtime_adapter.py",
    "tests/test_agent_framework_adapters.py",
)
FRAMEWORK_ADAPTERS = ROOT / "examples" / "agent-memory-graph" / "framework_adapters.py"
FRAMEWORK_ADAPTER_IDS = ("langgraph_durable_state", "mcp_resource_session")


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


def run_step(name: str, command: list[str], out_dir: Path) -> StepResult:
    safe_name = name.replace(" ", "-").replace("/", "-")
    stdout_path = out_dir / f"{safe_name}.stdout.txt"
    stderr_path = out_dir / f"{safe_name}.stderr.txt"
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    return StepResult(name, command, result.returncode, stdout_path, stderr_path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    steps: list[StepResult] = []
    steps.append(run_step("runtime-adapter-pytest", [python, "-m", "pytest", *TESTS], args.out_dir))

    manifest_step = run_step("framework-adapter-manifest", [python, str(FRAMEWORK_ADAPTERS), "manifest"], args.out_dir)
    steps.append(manifest_step)
    if manifest_step.ok:
        write_json(args.out_dir / "framework-adapter-manifest.json", json.loads(manifest_step.stdout_path.read_text()))

    matrix_step = run_step("framework-adapter-matrix", [python, str(FRAMEWORK_ADAPTERS), "matrix"], args.out_dir)
    steps.append(matrix_step)
    if matrix_step.ok:
        write_json(args.out_dir / "framework-adapter-matrix.json", json.loads(matrix_step.stdout_path.read_text()))

    exported_adapters: list[dict[str, Any]] = []
    for adapter_id in FRAMEWORK_ADAPTER_IDS:
        export_dir = args.out_dir / "exports" / adapter_id
        export_step = run_step(
            f"framework-export-{adapter_id}",
            [python, str(FRAMEWORK_ADAPTERS), "export", adapter_id, str(export_dir)],
            args.out_dir,
        )
        steps.append(export_step)
        import_step = run_step(
            f"framework-import-{adapter_id}",
            [python, str(FRAMEWORK_ADAPTERS), "import", str(export_dir)],
            args.out_dir,
        )
        steps.append(import_step)
        exported_adapters.append(
            {
                "adapter_id": adapter_id,
                "export_dir": str(export_dir.relative_to(args.out_dir)),
                "export_ok": export_step.ok,
                "import_ok": import_step.ok,
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "ok": all(step.ok for step in steps),
        "runtime_adapter_tests": list(TESTS),
        "framework_adapter_ids": list(FRAMEWORK_ADAPTER_IDS),
        "exported_adapters": exported_adapters,
        "steps": [step.to_json(args.out_dir) for step in steps],
    }
    write_json(args.out_dir / "adapter-conformance-report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

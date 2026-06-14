#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "target" / "debug" / "permeant-cli"
GENERATOR = ROOT / "adapters" / "generate_mock_extractor_fixture.py"
EXTRACTOR = ROOT / "adapters" / "mlx_extractor.py"
INJECTOR = ROOT / "adapters" / "vllm_injector.py"


def wait_for_listen(log_path: Path, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if log_path.exists() and "Daemon listening" in log_path.read_text(errors="ignore"):
            return
        time.sleep(0.1)
    raise RuntimeError(f"daemon did not report readiness within {timeout_seconds} seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local end-to-end migration using command-backed extractor/injector fixtures")
    parser.add_argument("--seq-len", type=int, default=8192)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--kv-heads", type=int, default=2)
    parser.add_argument("--head-dim", type=int, default=64)
    parser.add_argument("--quant", action="store_true")
    parser.add_argument("--addr", default="127.0.0.1:29099")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="permeant-fixture-roundtrip-") as tmpdir:
        tmp = Path(tmpdir)
        fixture_path = tmp / "extractor_fixture.json"
        injector_state = tmp / "injector_state.json"
        daemon_log = tmp / "daemon.log"

        subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                "--seq-len",
                str(args.seq_len),
                "--layers",
                str(args.layers),
                "--kv-heads",
                str(args.kv_heads),
                "--head-dim",
                str(args.head_dim),
                "--output",
                str(fixture_path),
            ],
            check=True,
        )

        env = os.environ.copy()
        env["PERMEANT_EXTRACTOR_MODE"] = "json_command"
        env["PERMEANT_EXTRACTOR_CMD"] = f"{sys.executable} {EXTRACTOR}"
        env["PERMEANT_EXTRACTOR_FIXTURE"] = str(fixture_path)
        env["PERMEANT_INJECTOR_MODE"] = "json_command"
        env["PERMEANT_INJECTOR_CMD"] = f"{sys.executable} {INJECTOR}"
        env["PERMEANT_INJECTOR_FIXTURE_STATE"] = str(injector_state)

        with daemon_log.open("w") as log_file:
            daemon = subprocess.Popen(
                [str(CLI), "daemon", "--addr", args.addr],
                cwd=ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

        try:
            wait_for_listen(daemon_log)
            cmd = [str(CLI), "sim-migrate", "--target-addr", args.addr, "--seq-len", str(args.seq_len)]
            if args.quant:
                cmd.append("--quant")
            result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            summary = {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "daemon_log": daemon_log.read_text(errors="ignore"),
                "injector_state_path": str(injector_state),
            }
            print(json.dumps(summary))
            return result.returncode
        finally:
            daemon.poll()
            if daemon.returncode is None:
                daemon.send_signal(signal.SIGTERM)
                try:
                    daemon.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())

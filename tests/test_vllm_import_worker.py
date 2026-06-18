import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
PYTHON = sys.executable


class VllmImportWorkerTests(unittest.TestCase):
    def test_once_mode_processes_ready_descriptor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import_dir = Path(tmpdir)
            payload_hash = "sha256:test-import-worker"
            (import_dir / f"{payload_hash}.json").write_text(
                json.dumps(
                    {
                        "hash": payload_hash,
                        "block_size": 256,
                        "layer_count": 1,
                        "layers": [{"layer_index": 0, "shape_mode": "preblocked"}],
                    }
                ),
                encoding="utf-8",
            )
            (import_dir / f"{payload_hash}.ready.json").write_text(
                json.dumps({"hash": payload_hash}),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = str(ADAPTERS) + os.pathsep + env.get("PYTHONPATH", "")
            env["PERMEANT_VLLM_CONSUMER_MODE"] = "dry_run"

            result = subprocess.run(
                [
                    PYTHON,
                    str(ADAPTERS / "vllm_import_worker.py"),
                    "--import-dir",
                    str(import_dir),
                    "--hook",
                    str(ADAPTERS / "my_vllm_consumer.py") + ":consume",
                    "--once",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            processed = import_dir / f"{payload_hash}.ready.processed.json"
            self.assertTrue(processed.exists())
            payload = json.loads(processed.read_text(encoding="utf-8"))
            self.assertEqual(payload["hash"], payload_hash)
            self.assertTrue(payload["result"]["success"])


if __name__ == "__main__":
    unittest.main()

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

    def test_once_mode_validates_agent_graph_span_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import_dir = Path(tmpdir)
            payload_hash = "sha256:test-import-worker-graph-span"
            metadata = {
                "version": "0.1",
                "source_runtime": "fixture-mlx",
                "model_id": "fixture-model",
                "prompt": {
                    "byte_hash": "sha256:" + "a" * 64,
                    "token_hash": "sha256:" + "b" * 64,
                    "token_count": 4,
                    "tokenizer_hash": "sha256:" + "c" * 64,
                },
                "kv_spans": [
                    {
                        "node_id": "checkpoint:prompt",
                        "token_start": 0,
                        "token_end": 4,
                        "cache_ref": "kv:fixture:prefill",
                        "tokenizer_hash": "sha256:" + "c" * 64,
                        "block_hashes": ["sha256:" + "d" * 64],
                    }
                ],
            }
            (import_dir / f"{payload_hash}.json").write_text(
                json.dumps(
                    {
                        "hash": payload_hash,
                        "block_size": 256,
                        "layer_count": 1,
                        "layers": [{"layer_index": 0, "shape_mode": "preblocked"}],
                        "agent_graph_span_metadata": metadata,
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
            payload = json.loads(processed.read_text(encoding="utf-8"))
            validation = payload["result"]["agent_graph_span_validation"]
            self.assertTrue(validation["success"])
            self.assertEqual(validation["cache_refs"], ["kv:fixture:prefill"])

    def test_once_mode_rejects_invalid_agent_graph_span_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import_dir = Path(tmpdir)
            payload_hash = "sha256:test-import-worker-bad-graph-span"
            (import_dir / f"{payload_hash}.json").write_text(
                json.dumps(
                    {
                        "hash": payload_hash,
                        "block_size": 256,
                        "layer_count": 1,
                        "layers": [{"layer_index": 0, "shape_mode": "preblocked"}],
                        "agent_graph_span_metadata": {"version": "0.1", "kv_spans": []},
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

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid agent graph span metadata", result.stderr)


if __name__ == "__main__":
    unittest.main()

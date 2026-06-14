import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
PYTHON = sys.executable


class RuntimeHttpBridgeTests(unittest.TestCase):
    def test_receiver_and_hook_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ADAPTERS) + os.pathsep + env.get("PYTHONPATH", "")
            env["PERMEANT_VLLM_RUNTIME_URL"] = "http://127.0.0.1:29113"
            env["PERMEANT_VLLM_RUNTIME_TOKEN"] = "test-token"

            receiver = subprocess.Popen(
                [
                    PYTHON,
                    str(ADAPTERS / "vllm_runtime_receiver.py"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "29113",
                    "--state-dir",
                    str(state_dir),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 10
                ready = False
                while time.time() < deadline:
                    line = receiver.stdout.readline()
                    if "listening" in line:
                        ready = True
                        break
                self.assertTrue(ready, "receiver did not report readiness")

                inject_payload = {
                    "hash": "sha256:test-bridge",
                    "block_size": 256,
                    "layers": [
                        {
                            "layer_index": 0,
                            "seq_len": 4,
                            "kv_heads": 2,
                            "head_dim": 3,
                            "key_blocks": [[[[0.1, 0.2, 0.3, 0.4]]]],
                            "value_blocks": [[[[0.5, 0.6, 0.7]]]],
                        }
                    ],
                }
                verify_payload = {"block_hashes": ["sha256:test-bridge"]}

                inject = subprocess.run(
                    [
                        PYTHON,
                        "-c",
                        (
                            "import json; "
                            "from vllm_http_runtime_hook import runtime_hook; "
                            "print(json.dumps(runtime_hook("
                            + json.dumps(inject_payload)
                            + ")))"
                        ),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(inject.returncode, 0, inject.stderr)
                self.assertTrue(json.loads(inject.stdout)["success"])

                verify = subprocess.run(
                    [
                        PYTHON,
                        "-c",
                        (
                            "import json; "
                            "from vllm_http_runtime_hook import runtime_hook; "
                            "print(json.dumps(runtime_hook("
                            + json.dumps(verify_payload)
                            + ")))"
                        ),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(verify.returncode, 0, verify.stderr)
                self.assertTrue(json.loads(verify.stdout)["success"])
                self.assertTrue((state_dir / "sha256:test-bridge.json").exists())
            finally:
                receiver.poll()
                if receiver.returncode is None:
                    receiver.send_signal(signal.SIGTERM)
                    receiver.wait(timeout=5)
                if receiver.stdout is not None:
                    receiver.stdout.close()
                if receiver.stderr is not None:
                    receiver.stderr.close()


class MlxRuntimeHttpBridgeTests(unittest.TestCase):
    def test_exporter_and_provider_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hook_path = Path(tmpdir) / "provider_hook.py"
            hook_path.write_text(
                "\n".join(
                    [
                        "def provider(request):",
                        "    return {",
                        "        'tensors': [",
                        "            {'name': 'layer.0.key', 'shape': [4, 2, 3], 'data': [0.1] * 24},",
                        "            {'name': 'layer.0.value', 'shape': [4, 2, 3], 'data': [0.2] * 24},",
                        "        ]",
                        "    }",
                    ]
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = str(ADAPTERS) + os.pathsep + env.get("PYTHONPATH", "")
            env["PERMEANT_MLX_RUNTIME_URL"] = "http://127.0.0.1:29114"
            env["PERMEANT_MLX_RUNTIME_TOKEN"] = "mlx-test-token"
            env["PERMEANT_MLX_EXPORTER_HOOK"] = f"{hook_path}:provider"

            exporter = subprocess.Popen(
                [
                    PYTHON,
                    str(ADAPTERS / "mlx_runtime_exporter.py"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "29114",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.time() + 10
                ready = False
                while time.time() < deadline:
                    line = exporter.stdout.readline()
                    if "listening" in line:
                        ready = True
                        break
                self.assertTrue(ready, "exporter did not report readiness")

                request = {"seq_len": 4, "n_layers": 1, "n_kv_heads": 2, "head_dim": 3}
                run = subprocess.run(
                    [
                        PYTHON,
                        "-c",
                        (
                            "import json; "
                            "from mlx_http_cache_provider import get_live_cache; "
                            "print(json.dumps(get_live_cache("
                            + json.dumps(request)
                            + ")))"
                        ),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                payload = json.loads(run.stdout)
                self.assertEqual(len(payload["tensors"]), 2)
                self.assertEqual(payload["tensors"][0]["name"], "layer.0.key")
            finally:
                exporter.poll()
                if exporter.returncode is None:
                    exporter.send_signal(signal.SIGTERM)
                    exporter.wait(timeout=5)
                if exporter.stdout is not None:
                    exporter.stdout.close()
                if exporter.stderr is not None:
                    exporter.stderr.close()


if __name__ == "__main__":
    unittest.main()

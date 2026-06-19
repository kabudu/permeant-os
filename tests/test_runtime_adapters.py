import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PYTHON = sys.executable


class RuntimeAdapterTests(unittest.TestCase):
    def run_script(self, script_name, payload, extra_env=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ADAPTERS) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [PYTHON, str(ADAPTERS / script_name)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        return result

    def test_extractor_fixture_mode(self):
        request = {"seq_len": 4, "n_layers": 1, "n_kv_heads": 2, "head_dim": 3}
        result = self.run_script(
            "mlx_extractor.py",
            request,
            {"PERMEANT_EXTRACTOR_FIXTURE": str(FIXTURES / "extractor_response.json")},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("tensors", payload)
        self.assertEqual(len(payload["tensors"]), 2)
        self.assertEqual(payload["tensors"][0]["name"], "layer.0.key")

    def test_extractor_hook_mode(self):
        request = {"seq_len": 4, "n_layers": 2, "n_kv_heads": 2, "head_dim": 3}
        result = self.run_script(
            "mlx_extractor.py",
            request,
            {"PERMEANT_EXTRACTOR_HOOK": str(FIXTURES / "runtime_adapter_hooks.py") + ":extractor_hook"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["tensors"]), 4)
        self.assertEqual(payload["tensors"][3]["name"], "layer.1.value")

    def test_extractor_preserves_agent_graph_span_metadata(self):
        request = {"seq_len": 4, "n_layers": 1, "n_kv_heads": 2, "head_dim": 3}
        result = self.run_script(
            "mlx_extractor.py",
            request,
            {"PERMEANT_EXTRACTOR_HOOK": str(FIXTURES / "runtime_adapter_hooks.py") + ":graph_span_extractor_hook"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("agent_graph_span_metadata", payload)
        self.assertEqual(payload["agent_graph_span_metadata"]["prompt"]["token_count"], 4)

    def test_injector_fixture_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "injector_state.json"
            inject_request = {
                "action": "inject_block",
                "block_size": 256,
                "block_hash": "sha256:test-block",
                "tensors": [{"name": "layer.0.key", "shape": [1, 2, 3, 4], "data": [0.1, 0.2]}],
            }
            verify_request = {
                "action": "verify_continuation",
                "block_size": 256,
                "expected_hashes": ["sha256:test-block"],
            }
            env = {"PERMEANT_INJECTOR_FIXTURE_STATE": str(state_path)}

            inject_result = self.run_script("vllm_injector.py", inject_request, env)
            self.assertEqual(inject_result.returncode, 0, inject_result.stderr)
            self.assertTrue(json.loads(inject_result.stdout)["success"])

            verify_result = self.run_script("vllm_injector.py", verify_request, env)
            self.assertEqual(verify_result.returncode, 0, verify_result.stderr)
            self.assertTrue(json.loads(verify_result.stdout)["success"])

    def test_injector_hook_mode(self):
        request = {"action": "verify_continuation", "block_size": 256, "expected_hashes": ["sha256:ok"]}
        result = self.run_script(
            "vllm_injector.py",
            request,
            {"PERMEANT_INJECTOR_HOOK": str(FIXTURES / "runtime_adapter_hooks.py") + ":injector_hook"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["success"])


if __name__ == "__main__":
    unittest.main()

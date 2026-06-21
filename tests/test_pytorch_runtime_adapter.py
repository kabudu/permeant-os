import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "adapters"
PYTHON = sys.executable
MODULE_NAME = "adapters.pytorch_runtime_bridge"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reload_module(state_file: Path, probe_file: Path):
    env = {
        "PERMEANT_PYTORCH_RUNTIME_STATE_FILE": str(state_file),
        "PERMEANT_PYTORCH_RUNTIME_PROBE_FILE": str(probe_file),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        return importlib.import_module(MODULE_NAME)


def _inject_request(block_hash="sha256:pytorch-reference"):
    return {
        "action": "inject_block",
        "block_hash": block_hash,
        "tensors": [
            {
                "name": "layer.0.key",
                "shape": [2, 2, 3],
                "data": [
                    0.0,
                    1.0,
                    2.0,
                    10.0,
                    11.0,
                    12.0,
                    100.0,
                    101.0,
                    102.0,
                    110.0,
                    111.0,
                    112.0,
                ],
            },
            {
                "name": "layer.0.value",
                "shape": [2, 2, 3],
                "data": [
                    1000.0,
                    1001.0,
                    1002.0,
                    1010.0,
                    1011.0,
                    1012.0,
                    1100.0,
                    1101.0,
                    1102.0,
                    1110.0,
                    1111.0,
                    1112.0,
                ],
            },
        ],
    }


class PytorchRuntimeAdapterTests(unittest.TestCase):
    def test_reference_pytorch_runtime_accepts_and_verifies_migrated_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module = _reload_module(tmp / "pytorch-state.json", tmp / "pytorch-probe.json")

            result = module.runtime_hook(_inject_request())

            self.assertTrue(result["success"])
            accepted = result["accepted_state"]
            self.assertEqual(accepted["target_runtime"], "pytorch-reference")
            self.assertIn(accepted["tensor_backend"], {"python-list", "torch"})
            self.assertEqual(accepted["layer_count"], 1)
            self.assertEqual(accepted["layers"][0]["shape"], [2, 2, 3])
            self.assertTrue(accepted["layers"][0]["key_sha256"].startswith("sha256:"))
            self.assertTrue(accepted["layers"][0]["value_sha256"].startswith("sha256:"))

            verify = module.runtime_hook(
                {
                    "action": "verify_continuation",
                    "expected_hashes": ["sha256:pytorch-reference"],
                    "prompt": "continue from migrated state",
                }
            )
            self.assertTrue(verify["success"])
            self.assertEqual(verify["verified_hashes"], ["sha256:pytorch-reference"])
            self.assertTrue(verify["continuation_proof"]["proof_hash"].startswith("sha256:"))
            self.assertIn("no language decode is claimed", verify["continuation_proof"]["note"])

    def test_reference_pytorch_runtime_persists_hashes_for_command_processes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ADAPTERS) + os.pathsep + env.get("PYTHONPATH", "")
            env["PERMEANT_PYTORCH_RUNTIME_STATE_FILE"] = str(tmp / "pytorch-state.json")

            inject = subprocess.run(
                [PYTHON, str(ADAPTERS / "pytorch_injector.py")],
                input=json.dumps(_inject_request("sha256:pytorch-command")),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(inject.returncode, 0, inject.stderr)
            inject_payload = json.loads(inject.stdout)
            self.assertTrue(inject_payload["success"])
            self.assertEqual(inject_payload["accepted_state"]["hash"], "sha256:pytorch-command")

            verify = subprocess.run(
                [PYTHON, str(ADAPTERS / "pytorch_injector.py")],
                input=json.dumps(
                    {
                        "action": "verify_continuation",
                        "expected_hashes": ["sha256:pytorch-command"],
                    }
                ),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertEqual(
                json.loads(verify.stdout),
                {
                    "success": True,
                    "verified_hashes": ["sha256:pytorch-command"],
                },
            )

            state = json.loads((tmp / "pytorch-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["target_runtime"], "pytorch-reference")
            self.assertEqual(state["registered_hashes"], ["sha256:pytorch-command"])

    def test_reference_pytorch_runtime_exports_reverse_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module = _reload_module(tmp / "pytorch-state.json", tmp / "pytorch-probe.json")
            module.runtime_hook(_inject_request("sha256:pytorch-export"))
            module.runtime_hook({"action": "verify_continuation", "block_hashes": ["sha256:pytorch-export"]})

            result = module.runtime_hook({"action": "export_reverse_runtime_state"})

            self.assertTrue(result["success"])
            state = result["reverse_runtime_state"]
            self.assertEqual(state["status"], "target_runtime_state_exported")
            self.assertEqual(state["target_runtime"], "pytorch-reference")
            self.assertEqual(state["registered_hashes"], ["sha256:pytorch-export"])
            self.assertTrue(state["proof_hash"].startswith("sha256:"))

    def test_reference_pytorch_runtime_rejects_mismatched_key_value_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module = _reload_module(tmp / "pytorch-state.json", tmp / "pytorch-probe.json")
            request = _inject_request()
            request["tensors"][1]["shape"] = [1, 2, 3]
            request["tensors"][1]["data"] = request["tensors"][1]["data"][:6]

            with self.assertRaisesRegex(module.AdapterError, "key/value shapes differ"):
                module.runtime_hook(request)


if __name__ == "__main__":
    unittest.main()

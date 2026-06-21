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
MODULE_NAME = "adapters.llamacpp_runtime_bridge"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fake_tool(path: Path, name: str) -> Path:
    tool = path / name
    tool.write_text("#!/bin/sh\necho 'version: fake-llama.cpp (test)'\n", encoding="utf-8")
    tool.chmod(0o755)
    return tool


def _reload_module(state_file: Path, probe_file: Path, cli: Path, server: Path):
    env = {
        "PERMEANT_LLAMA_CPP_RUNTIME_STATE_FILE": str(state_file),
        "PERMEANT_LLAMA_CPP_RUNTIME_PROBE_FILE": str(probe_file),
        "PERMEANT_LLAMA_CPP_CLI": str(cli),
        "PERMEANT_LLAMA_CPP_SERVER": str(server),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        return importlib.import_module(MODULE_NAME)


def _inject_request(block_hash="sha256:llamacpp-reference"):
    return {
        "action": "inject_block",
        "block_hash": block_hash,
        "tensors": [
            {
                "name": "layer.0.key",
                "shape": [2, 1, 2],
                "data": [0.0, 1.0, 10.0, 11.0],
            },
            {
                "name": "layer.0.value",
                "shape": [2, 1, 2],
                "data": [100.0, 101.0, 110.0, 111.0],
            },
        ],
    }


class LlamaCppRuntimeAdapterTests(unittest.TestCase):
    def test_llamacpp_adapter_accepts_state_and_records_tool_capabilities(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module = _reload_module(
                tmp / "llamacpp-state.json",
                tmp / "llamacpp-probe.json",
                _fake_tool(tmp, "llama-cli"),
                _fake_tool(tmp, "llama-server"),
            )

            result = module.runtime_hook(_inject_request())

            self.assertTrue(result["success"])
            accepted = result["accepted_state"]
            self.assertEqual(accepted["target_runtime"], "llama.cpp")
            self.assertEqual(accepted["adapter_mode"], "accepted-state")
            self.assertEqual(accepted["decode_claim"], "none-without-live-kv-import-hook")
            self.assertTrue(accepted["capabilities"]["cli"]["available"])
            self.assertFalse(accepted["capabilities"]["kv_import_supported_by_default_adapter"])
            self.assertEqual(accepted["layers"][0]["shape"], [2, 1, 2])

            verify = module.runtime_hook({"action": "verify_continuation", "expected_hashes": ["sha256:llamacpp-reference"]})
            self.assertTrue(verify["success"])
            self.assertEqual(verify["decode_status"], "not_attempted_without_live_kv_import_hook")

    def test_llamacpp_command_injector_persists_hashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(ADAPTERS) + os.pathsep + env.get("PYTHONPATH", "")
            env["PERMEANT_LLAMA_CPP_RUNTIME_STATE_FILE"] = str(tmp / "llamacpp-state.json")
            env["PERMEANT_LLAMA_CPP_CLI"] = str(_fake_tool(tmp, "llama-cli"))
            env["PERMEANT_LLAMA_CPP_SERVER"] = str(_fake_tool(tmp, "llama-server"))

            inject = subprocess.run(
                [PYTHON, str(ADAPTERS / "llamacpp_injector.py")],
                input=json.dumps(_inject_request("sha256:llamacpp-command")),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(inject.returncode, 0, inject.stderr)
            self.assertTrue(json.loads(inject.stdout)["success"])

            verify = subprocess.run(
                [PYTHON, str(ADAPTERS / "llamacpp_injector.py")],
                input=json.dumps({"action": "verify_continuation", "expected_hashes": ["sha256:llamacpp-command"]}),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            payload = json.loads(verify.stdout)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["verified_hashes"], ["sha256:llamacpp-command"])

    def test_llamacpp_reverse_export_reports_no_decode_claim_without_live_hook(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            module = _reload_module(
                tmp / "llamacpp-state.json",
                tmp / "llamacpp-probe.json",
                _fake_tool(tmp, "llama-cli"),
                _fake_tool(tmp, "llama-server"),
            )
            module.runtime_hook(_inject_request("sha256:llamacpp-export"))

            result = module.runtime_hook({"action": "export_reverse_runtime_state"})

            self.assertTrue(result["success"])
            state = result["reverse_runtime_state"]
            self.assertEqual(state["target_runtime"], "llama.cpp")
            self.assertEqual(state["registered_hashes"], ["sha256:llamacpp-export"])
            self.assertEqual(state["decode_claim"], "none-without-live-kv-import-hook")
            self.assertTrue(state["proof_hash"].startswith("sha256:"))

    def test_llamacpp_live_hook_can_report_runtime_binding_and_continuation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            hook = tmp / "live_hook.py"
            hook.write_text(
                "\n".join(
                    [
                        "def hook(payload, request=None, original=None):",
                        "    if 'verify' in payload:",
                        "        return {'success': True, 'continuation': {'token_ids': [1, 2, 3]}}",
                        "    return {'success': True, 'runtime_state_bound': True}",
                    ]
                ),
                encoding="utf-8",
            )
            env = {
                "PERMEANT_LLAMA_CPP_RUNTIME_HOOK": f"{hook}:hook",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                module = _reload_module(
                    tmp / "llamacpp-state.json",
                    tmp / "llamacpp-probe.json",
                    _fake_tool(tmp, "llama-cli"),
                    _fake_tool(tmp, "llama-server"),
                )
                inject = module.runtime_hook(_inject_request("sha256:llamacpp-live"))
                self.assertEqual(inject["accepted_state"]["adapter_mode"], "live-hook")
                self.assertTrue(inject["accepted_state"]["live_hook_result"]["runtime_state_bound"])

                verify = module.runtime_hook({"action": "verify_continuation", "block_hashes": ["sha256:llamacpp-live"]})
                self.assertEqual(verify["decode_status"], "live_hook_continuation_reported")
                self.assertEqual(verify["live_hook_result"]["continuation"]["token_ids"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()

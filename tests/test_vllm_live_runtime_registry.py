import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_NAME = "adapters.vllm_live_runtime_registry"
FIXTURE_MODULE = "tests.fixtures.vllm_live_runtime_fixture"


def _reload_module():
    if MODULE_NAME in sys.modules:
        del sys.modules[MODULE_NAME]
    return importlib.import_module(MODULE_NAME)


def test_runtime_hook_registers_and_verifies_with_runtime_methods(tmp_path, monkeypatch):
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_TARGET", f"{FIXTURE_MODULE}:get_recording_runtime")
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_STATE_FILE", str(tmp_path / "state.json"))
    module = _reload_module()

    inject_payload = {"hash": "sha256:test-a", "layers": [{"layer_index": 0}]}
    verify_payload = {"block_hashes": ["sha256:test-a"]}

    assert module.runtime_hook(inject_payload) == {"success": True}
    assert module.runtime_hook(verify_payload) == {"success": True}
    assert "sha256:test-a" in (tmp_path / "state.json").read_text()


def test_runtime_hook_falls_back_to_state_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_TARGET", f"{FIXTURE_MODULE}:get_register_only_runtime")
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_VERIFY_METHOD", "missing_verify_method")
    module = _reload_module()

    assert module.runtime_hook({"hash": "sha256:test-b", "layers": [{"layer_index": 0}]}) == {"success": True}
    assert module.runtime_hook({"block_hashes": ["sha256:test-b"]}) == {"success": True}
    assert module.runtime_hook({"block_hashes": ["sha256:missing"]}) == {
        "success": False,
        "missing_hashes": ["sha256:missing"],
    }


def test_runtime_hook_writes_directly_into_vllm_style_kv_cache(tmp_path, monkeypatch):
    fixture = importlib.import_module(FIXTURE_MODULE)
    fixture.reset_tensor_backed_runtime()

    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_TARGET", f"{FIXTURE_MODULE}:get_tensor_backed_runtime")
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_REGISTER_METHOD", "missing_register_method")
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_VERIFY_METHOD", "missing_verify_method")
    module = _reload_module()

    payload = fixture.build_tensor_backed_payload("sha256:test-c")
    assert module.runtime_hook(payload) == {"success": True, "written_layers": ["model.layers.0"]}
    assert module.runtime_hook({"block_hashes": ["sha256:test-c"]}) == {"success": True}
    assert fixture.snapshot_tensor_backed_runtime() == {
        "registered_hashes": ["sha256:test-c"],
        "key_first_token": 0.0,
        "key_last_token": 123.0,
        "value_first_token": 1000.0,
        "value_last_token": 1132.0,
    }

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_NAME = "adapters.vllm_live_runtime_registry"
FIXTURE_MODULE = "tests.fixtures.vllm_live_runtime_fixture"


def _reload_module():
    if MODULE_NAME in sys.modules:
        del sys.modules[MODULE_NAME]
    return importlib.import_module(MODULE_NAME)


@pytest.mark.parametrize("layout", ["contiguous", "strided", "cross_row", "expanded", "scalar", "empty"])
def test_tensor_preview_copies_only_requested_values(monkeypatch, layout):
    torch = pytest.importorskip("torch")
    registry = _reload_module()
    base = torch.arange(24).reshape(2, 3, 4)
    cache = {
        "contiguous": base,
        "strided": base.transpose(0, 1),
        "cross_row": base.transpose(0, 2),
        "expanded": base[0, 0, :1].expand(2, 12),
        "scalar": base[1, 0, 0],
        "empty": base[:, :0],
    }[layout]
    limit = 3
    expected = cache.reshape(-1)[:limit].tolist()
    transfers = []
    cpu = torch.Tensor.cpu

    def count_transfer(tensor):
        transfers.append(tensor.numel())
        return cpu(tensor)

    monkeypatch.setattr(torch.Tensor, "cpu", count_transfer)
    assert registry._preview_flat_values(cache, limit) == expected
    assert transfers == ([len(expected)] if expected else [])


@pytest.mark.parametrize("tile,head_first", [(4, False), (4, True), (2, False), (2, True)])
def test_batched_torch_matches_scalar_on_strided_cache(monkeypatch, tile, head_first):
    torch = pytest.importorskip("torch")
    registry = _reload_module()
    blocks, heads, dims, tokens = 2, 3, 5, 4
    size = blocks * heads * dims * tokens
    layer = {
        "key_tensor": {"shape": [blocks, heads, dims, tokens], "data": [n / 31 for n in range(size)]},
        "value_tensor": {"shape": [blocks, heads, tokens, dims], "data": [-n / 29 for n in range(size)]},
    }
    ids = [4, 1] if tile == tokens else [4, 1, 5, 2]
    dims_after_kv = (heads, tile, dims) if head_first else (tile, heads, dims)
    scalar = torch.full((2, 6, *dims_after_kv), -100, dtype=torch.float16).transpose(0, 1)
    batched = torch.full_like(scalar, -100)
    monkeypatch.setenv("PERMEANT_VLLM_BATCH_KV_WRITES", "0")
    assert registry._write_combined_cache(scalar, layer, ids) == "scalar"
    monkeypatch.setenv("PERMEANT_VLLM_BATCH_KV_WRITES", "1")
    monkeypatch.setenv("PERMEANT_RECOVERY_CHECKPOINT_SHA", "a" * 64)
    assert registry._write_combined_cache(batched, layer, ids) == "batched_torch"
    assert torch.equal(scalar, batched)


def test_full_restore_rejects_reordered_registrations_before_decode(monkeypatch):
    monkeypatch.setenv("PERMEANT_RECOVERY_CHECKPOINT_SHA", "a" * 64)
    target = importlib.import_module("adapters.vllm_real_runtime_target")
    runtime = target.RealVllmRuntime(None, {}, {}, {})
    runtime.recovery_slots = {"second": (4, [8, 9]), "first": (4, [4, 5])}
    runtime.registered_hashes = set(runtime.recovery_slots)

    result = runtime.verify_permeant_hashes({"block_hashes": ["first", "second"]})
    assert result["success"] is False
    assert "ordered logical blocks" in result["error"]


@pytest.mark.parametrize("cache_lookup_matches", [False, True])
def test_full_restore_seeds_in_logical_order_and_checks_resolved_slots(monkeypatch, cache_lookup_matches):
    monkeypatch.setenv("PERMEANT_RECOVERY_CHECKPOINT_SHA", "a" * 64)
    target = importlib.import_module("adapters.vllm_real_runtime_target")
    token_ids = list(range(8))
    monkeypatch.setattr(target, "_source_continuation_reference", lambda: {"prompt_token_ids": token_ids})
    monkeypatch.setitem(sys.modules, "vllm", SimpleNamespace(SamplingParams=lambda **_: None))
    monkeypatch.setitem(
        sys.modules, "vllm.v1.request",
        SimpleNamespace(Request=lambda **_: SimpleNamespace(block_hashes=list(range(4)))),
    )
    slots = [7, 4, 11, 2]
    seeded = []
    pool = SimpleNamespace(
        blocks=list(range(12)),
        cache_full_blocks=lambda **args: seeded.extend(args["blocks"]),
    )
    lookup = slots[:3] if cache_lookup_matches else [7, 11, 4]
    manager = SimpleNamespace(
        block_pool=pool,
        kv_cache_config=SimpleNamespace(kv_cache_groups=[object()]),
        get_computed_blocks=lambda request: (SimpleNamespace(get_block_ids=lambda: (lookup,)), 6),
    )
    scheduler = SimpleNamespace(kv_cache_manager=manager, block_size=2)
    core = SimpleNamespace(scheduler=scheduler)
    llm = SimpleNamespace(
        llm_engine=SimpleNamespace(engine_core=SimpleNamespace(engine_core=core)),
        tokenizer=SimpleNamespace(encode=lambda _: token_ids),
    )
    runtime = target.RealVllmRuntime(llm, {}, {}, {})
    runtime.baseline_cache_reset = True
    runtime.recovery_slots = {"first": (4, slots[:2]), "second": (4, slots[2:])}

    proof = target._seed_vllm_prefix_cache(runtime, "prompt")
    assert seeded == slots
    assert proof["success"] is cache_lookup_matches
    if cache_lookup_matches:
        assert proof["verified_reusable_block_ids"] == slots[:3]
        assert proof["reusable_prefix_tokens"] == 6


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


def test_runtime_hook_exports_reverse_runtime_state(monkeypatch):
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_TARGET", f"{FIXTURE_MODULE}:get_recording_runtime")
    module = _reload_module()

    result = module.runtime_hook({"action": "export_reverse_runtime_state"})

    assert result["success"] is True
    assert result["reverse_runtime_state"]["status"] == "target_runtime_state_exported"
    assert result["reverse_runtime_state"]["generated_token_ids"] == [101, 102]


def test_runtime_hook_reports_missing_reverse_runtime_export(monkeypatch):
    monkeypatch.setenv("PERMEANT_VLLM_RUNTIME_TARGET", f"{FIXTURE_MODULE}:get_register_only_runtime")
    module = _reload_module()

    assert module.runtime_hook({"action": "export_reverse_runtime_state"}) == {
        "success": False,
        "error": "runtime does not expose export_reverse_runtime_state",
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
    result = module.runtime_hook(payload)
    assert result["success"] is True
    assert result["written_layers"] == ["model.layers.0"]
    assert result["target_block_allocation"]["mode"] == "sequential_fallback"
    assert result["written_layer_summaries"][0]["slot_probe"]["all_samples_match"] is True
    assert module.runtime_hook({"block_hashes": ["sha256:test-c"]}) == {"success": True}
    assert fixture.snapshot_tensor_backed_runtime() == {
        "registered_hashes": ["sha256:test-c"],
        "key_first_token": 0.0,
        "key_last_token": 123.0,
        "value_first_token": 1000.0,
        "value_last_token": 1132.0,
    }

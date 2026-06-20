from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "plan-transfer-codecs.py"
SPEC = importlib.util.spec_from_file_location("plan_transfer_codecs", MODULE_PATH)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def test_selects_qatq_when_experimental_codec_is_runner_supported():
    plan = planner.build_plan(
        sequence_lengths=[32768],
        source_codecs=["raw", "fp8", "turboquant", "qatq"],
        target_codecs=["raw", "fp8", "turboquant", "qatq"],
        preference_order=["qatq", "turboquant", "fp8", "raw"],
        n_layers=24,
        n_kv_heads=2,
        head_dim=64,
        network_bandwidth_bps=25_000_000_000.0,
        protocol_overhead_secs=0.15,
        require_runner_supported=True,
    )

    point = plan["points"][0]
    assert plan["schema_version"] == "permeantos-transfer-codec-plan-v0"
    assert point["selected_codec"] == "qatq"
    assert point["selected_manifest_transfer_quantization"] == "qatq"
    assert point["requires_fidelity_evidence"] is True
    qatq = next(candidate for candidate in point["candidates"] if candidate["codec"] == "qatq")
    assert qatq["capability_supported"] is True
    assert qatq["runner_supported"] is True
    assert qatq["executable"] is True
    assert qatq["runner_env"] == {
        "PERMEANT_SEQ_LEN": "32768",
        "PERMEANT_TRANSFER_QUANTIZATION": "qatq",
    }


def test_falls_back_to_raw_when_preferred_codec_is_not_mutually_supported():
    plan = planner.build_plan(
        sequence_lengths=[8192],
        source_codecs=["raw", "fp8"],
        target_codecs=["raw"],
        preference_order=["fp8", "raw"],
        n_layers=24,
        n_kv_heads=2,
        head_dim=64,
        network_bandwidth_bps=10_000_000_000.0,
        protocol_overhead_secs=0.15,
        require_runner_supported=True,
    )

    point = plan["points"][0]
    assert point["selected_codec"] == "raw"
    assert point["fallback_action"] == "fallback_raw_transfer"
    assert point["selected_manifest_transfer_quantization"] == "none"
    assert point["requires_fidelity_evidence"] is False
    fp8 = next(candidate for candidate in point["candidates"] if candidate["codec"] == "fp8")
    assert fp8["runner_env"] is None
    raw = next(candidate for candidate in point["candidates"] if candidate["codec"] == "raw")
    assert raw["runner_env"] == {
        "PERMEANT_SEQ_LEN": "8192",
        "PERMEANT_TRANSFER_QUANTIZATION": "none",
    }


def test_falls_back_to_re_prefill_when_no_transfer_codec_is_mutual():
    plan = planner.build_plan(
        sequence_lengths=[4096],
        source_codecs=["fp8"],
        target_codecs=["raw"],
        preference_order=["fp8"],
        n_layers=24,
        n_kv_heads=2,
        head_dim=64,
        network_bandwidth_bps=10_000_000_000.0,
        protocol_overhead_secs=0.15,
        require_runner_supported=True,
    )

    point = plan["points"][0]
    assert point["selected_codec"] is None
    assert point["fallback_action"] == "fallback_re_prefill"


def test_can_explicitly_plan_unimplemented_turboquant_candidate():
    plan = planner.build_plan(
        sequence_lengths=[32768],
        source_codecs=["raw", "turboquant"],
        target_codecs=["raw", "turboquant"],
        preference_order=["turboquant", "raw"],
        n_layers=24,
        n_kv_heads=2,
        head_dim=64,
        network_bandwidth_bps=25_000_000_000.0,
        protocol_overhead_secs=0.15,
        require_runner_supported=False,
    )

    point = plan["points"][0]
    assert point["selected_codec"] == "turboquant"
    assert point["requires_fidelity_evidence"] is True
    selected = point["candidates"][0]
    assert selected["executable"] is True
    assert selected["runner_env"] is None
    assert selected["loss_semantics"] == "lossy_experimental_candidate"


def test_cli_style_json_and_markdown_are_serializable():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        markdown = root / "codec-plan.md"
        plan = planner.build_plan(
            sequence_lengths=planner.parse_int_list("4096,8192"),
            source_codecs=planner.parse_codec_list("raw,fp8"),
            target_codecs=planner.parse_codec_list("none,fp8"),
            preference_order=planner.parse_codec_list("qatq,turboquant,fp8,raw"),
            n_layers=24,
            n_kv_heads=2,
            head_dim=64,
            network_bandwidth_bps=25_000_000_000.0,
            protocol_overhead_secs=0.15,
            require_runner_supported=True,
        )
        markdown.write_text(planner.markdown_table(plan))
        payload = json.loads(json.dumps(plan))

        assert payload["points"][0]["selected_codec"] == "fp8"
        assert "| 4096 | fp8 |" in markdown.read_text()

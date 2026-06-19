from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "adapters" / "analyze_real_runtime_fidelity.py"
SPEC = importlib.util.spec_from_file_location("analyze_real_runtime_fidelity", MODULE_PATH)
assert SPEC and SPEC.loader
analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyzer)


def _manifest(agent_graph: dict | None = None) -> dict:
    manifest = {
        "run_id": "migration-test",
        "success": True,
    }
    if agent_graph is not None:
        manifest["agent_graph"] = agent_graph
    return manifest


def _agent_graph() -> dict:
    return {
        "manifest_path": "/tmp/agent-graph/manifest.json",
        "graph_path": "graph.json",
        "graph_hash": "sha256:" + "a" * 64,
        "prompt_byte_hash": "sha256:" + "b" * 64,
        "prompt_token_hash": "sha256:" + "c" * 64,
        "tokenizer_hash": "sha256:" + "d" * 64,
        "kv_hash": "sha256:" + "e" * 64,
        "artifacts": [
            {
                "path": "reports/result.json",
                "sha256": "sha256:" + "f" * 64,
                "size_bytes": 42,
            }
        ],
    }


def _probe(prompt_matches: bool = True, hash_success: bool = True) -> dict:
    return {
        "events": [
            {
                "event": "verify_permeant_hashes",
                "success": hash_success,
                "source_comparison": {
                    "prompt_matches": prompt_matches,
                    "matches": prompt_matches,
                    "shared_prefix_token_count": 3 if prompt_matches else 1,
                    "expected_token_count": 3,
                    "actual_token_count": 3,
                },
            },
            {
                "event": "register_permeant_block",
                "written_layers": [0, 1, 2, 3],
            },
            {
                "event": "decode_attachment_snapshot",
                "stage": "generate_continuation:after_generate",
                "prompt_tokenization": {"token_count": 3},
            },
            {
                "event": "migrated_decode_attachment_attempt",
                "attempt": {
                    "supported": True,
                    "prefix_cache_seed": {
                        "success": True,
                        "seeded_block_count": 1,
                    },
                },
            },
        ]
    }


def test_alignment_reports_prompt_graph_and_kv_together():
    summary = analyzer._summarize(_manifest(_agent_graph()), _probe())
    alignment = summary["alignment"]

    assert alignment["overall_status"] == "aligned"
    assert alignment["prompt"]["status"] == "aligned"
    assert alignment["prompt"]["source_prompt_matches_target"] is True
    assert alignment["prompt"]["graph_prompt_token_hash"] == "sha256:" + "c" * 64
    assert alignment["graph"]["status"] == "aligned"
    assert alignment["graph"]["graph_hash"] == "sha256:" + "a" * 64
    assert alignment["graph"]["artifact_hashes"] == {
        "reports/result.json": "sha256:" + "f" * 64
    }
    assert alignment["kv"]["status"] == "aligned"
    assert alignment["kv"]["hash_validation_success"] is True
    assert alignment["kv"]["graph_kv_hash"] == "sha256:" + "e" * 64
    assert alignment["kv"]["written_layer_count"] == 4


def test_alignment_marks_graph_unavailable_without_agent_graph_manifest():
    summary = analyzer._summarize(_manifest(), _probe())
    alignment = summary["alignment"]

    assert alignment["overall_status"] == "partial"
    assert alignment["prompt"]["status"] == "aligned"
    assert alignment["graph"]["status"] == "unavailable"
    assert alignment["kv"]["status"] == "aligned"


def test_alignment_marks_divergence_when_prompt_or_kv_mismatch():
    summary = analyzer._summarize(
        _manifest(_agent_graph()),
        _probe(prompt_matches=False, hash_success=False),
    )
    alignment = summary["alignment"]

    assert alignment["overall_status"] == "diverged"
    assert alignment["prompt"]["status"] == "diverged"
    assert alignment["kv"]["status"] == "diverged"

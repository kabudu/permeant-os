from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "analyze-fidelity-horizons.py"
SPEC = importlib.util.spec_from_file_location("analyze_fidelity_horizons", MODULE_PATH)
assert SPEC and SPEC.loader
horizons = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(horizons)


def continuation(token_ids: list[int], prompt: str = "prompt") -> dict:
    return {
        "prompt": prompt,
        "text": "generated",
        "token_ids": token_ids,
        "token_count": len(token_ids),
        "max_tokens": len(token_ids),
    }


def test_reports_exact_multi_horizon_matches():
    summary = horizons.summarize(
        source=continuation([1, 2, 3, 4, 5, 6, 7, 8]),
        post_migration=continuation([1, 2, 3, 4, 5, 6, 7, 8]),
        baseline=continuation([1, 2, 3, 4, 5, 6, 7, 8]),
        horizons=[4, 8],
    )

    assert summary["schema_version"] == "permeantos-fidelity-horizon-suite-v0"
    assert summary["max_complete_exact_horizon"] == 8
    assert [item["name"] for item in summary["comparisons"]] == [
        "source_vs_post_migration",
        "baseline_vs_post_migration",
    ]
    for comparison in summary["comparisons"]:
        assert comparison["max_exact_horizon"] == 8
        assert comparison["first_failed_horizon"] is None
        assert [item["status"] for item in comparison["horizons"]] == ["exact", "exact"]


def test_reports_divergence_at_the_first_failed_horizon():
    summary = horizons.summarize(
        source=continuation([1, 2, 3, 4, 5, 6]),
        post_migration=continuation([1, 2, 3, 9, 5, 6]),
        baseline=None,
        horizons=[3, 4, 6],
    )

    comparison = summary["comparisons"][0]
    assert comparison["first_mismatch_index"] == 3
    assert comparison["max_exact_horizon"] == 3
    assert comparison["first_failed_horizon"] == 4
    assert [item["status"] for item in comparison["horizons"]] == [
        "exact",
        "diverged",
        "diverged",
    ]


def test_reports_insufficient_tokens_for_unavailable_horizon():
    summary = horizons.summarize(
        source=continuation([1, 2, 3, 4, 5, 6]),
        post_migration=continuation([1, 2, 3, 4]),
        baseline=None,
        horizons=[4, 6],
    )

    comparison = summary["comparisons"][0]
    assert comparison["max_exact_horizon"] == 4
    assert comparison["first_failed_horizon"] == 6
    assert comparison["horizons"][1]["status"] == "insufficient_tokens"
    assert comparison["horizons"][1]["actual_has_horizon"] is False


def test_empty_token_records_do_not_create_exact_aggregate_horizon():
    summary = horizons.summarize(
        source=continuation([]),
        post_migration=continuation([]),
        baseline=None,
        horizons=[4],
    )

    assert summary["max_complete_exact_horizon"] == 0
    assert summary["comparisons"][0]["available"] is False
    assert summary["comparisons"][0]["horizons"][0]["status"] == "insufficient_tokens"


def test_probe_events_can_supply_post_and_baseline_continuations():
    probe = {
        "events": [
            {"event": "generate_continuation", **continuation([9])},
            {"event": "baseline_continuation", **continuation([1, 2, 3, 4])},
            {"event": "generate_continuation", **continuation([1, 2, 3, 4])},
        ]
    }

    assert horizons.probe_event(probe, "generate_continuation")["token_ids"] == [1, 2, 3, 4]
    summary = horizons.summarize(
        source=continuation([1, 2, 3, 4]),
        post_migration=horizons.probe_event(probe, "generate_continuation"),
        baseline=horizons.probe_event(probe, "baseline_continuation"),
        horizons=[4],
    )

    assert summary["max_complete_exact_horizon"] == 4


def test_cli_writes_markdown_report_from_probe():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        source = root / "source.json"
        probe = root / "probe.json"
        markdown = root / "summary.md"
        source.write_text(json.dumps(continuation([1, 2, 3, 4])) + "\n")
        probe.write_text(
            json.dumps(
                {
                    "events": [
                        {"event": "generate_continuation", **continuation([1, 2, 3, 4])},
                    ]
                }
            )
            + "\n"
        )

        args = horizons.parse_horizons("2,4")
        summary = horizons.summarize(
            source=horizons.load_json(source),
            post_migration=horizons.probe_event(horizons.load_json(probe), "generate_continuation"),
            baseline=None,
            horizons=args,
        )
        markdown.write_text(horizons.markdown_table(summary))

        assert "source_vs_post_migration" in markdown.read_text()
        assert "| source_vs_post_migration | 4 | exact |" in markdown.read_text()

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "aws-real-runtime-e2e.sh"


def test_run_refreshes_source_continuation_before_aws_provisioning():
    script = RUNNER.read_text()
    run_start = script.index("run_cmd() {")
    run_body = script[run_start : script.index("\n}", run_start)]

    assert "refresh_source_continuation" in script
    assert "validate_source_continuation_file" in script
    assert run_body.index("refresh_source_continuation") < run_body.index("discover_network")
    assert run_body.index("refresh_source_continuation") < run_body.index("provision")
    assert run_body.index("refresh_source_continuation") < run_body.index("start_target")


def test_source_extract_url_preserves_explicit_extract_endpoint():
    script = RUNNER.read_text()
    assert 'if [[ "$base" == */extract ]]; then' in script
    assert "printf '%s/extract\\n' \"$base\"" in script


def test_run_passes_agent_graph_manifest_to_migration_when_set():
    script = RUNNER.read_text()
    run_migration_start = script.index("run_migration() {")
    run_migration_body = script[run_migration_start : script.index("\n}", run_migration_start)]

    assert 'PERMEANT_AGENT_GRAPH_MANIFEST="${PERMEANT_AGENT_GRAPH_MANIFEST:-}"' in script
    assert "source:agent_graph_manifest" in script
    assert '--agent-graph-manifest "$PERMEANT_AGENT_GRAPH_MANIFEST"' in run_migration_body


def test_slot_probe_summary_accepts_quantized_sample_delta_fields():
    script = RUNNER.read_text()

    assert 'sample.get("key_max_abs_diff", sample.get("key_delta"))' in script
    assert 'sample.get("value_max_abs_diff", sample.get("value_delta"))' in script

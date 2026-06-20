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

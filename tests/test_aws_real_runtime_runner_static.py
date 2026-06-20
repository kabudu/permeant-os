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


def test_reverse_runtime_import_uses_target_export_api():
    script = RUNNER.read_text()
    reverse_start = script.index("run_reverse_runtime_import() {")
    reverse_body = script[reverse_start : script.index("\nrun_agent_activity_resume() {", reverse_start)]

    assert "PERMEANT_REVERSE_RUNTIME_IMPORT" in script
    assert "/export_reverse_runtime_state" in reverse_body
    assert "reverse_runtime_state" in reverse_body
    assert "source_reverse_import_url" in reverse_body


def test_production_wss_is_default_migration_transport():
    script = RUNNER.read_text()

    assert 'PERMEANT_MIGRATION_TRANSPORT="${PERMEANT_MIGRATION_TRANSPORT:-production-wss}"' in script
    assert 'PERMEANT_PRODUCTION_TRANSPORT_PORT="${PERMEANT_PRODUCTION_TRANSPORT_PORT:-29443}"' in script
    assert "production_transport_enabled()" in script


def test_production_transport_generates_and_copies_mtls_certs():
    script = RUNNER.read_text()
    cert_start = script.index("generate_production_transport_certs() {")
    cert_body = script[cert_start : script.index("\nwrite_remote_scripts() {", cert_start)]
    copy_start = script.index("copy_production_transport_certs_to_target() {")
    copy_body = script[copy_start : script.index("\nstart_target() {", copy_start)]

    assert "openssl req -x509" in cert_body
    assert "extendedKeyUsage=serverAuth" in cert_body
    assert "extendedKeyUsage=clientAuth" in cert_body
    assert "subjectAltName=DNS:permeant-target" in cert_body
    assert "server.key" in copy_body
    assert "client.key" not in copy_body


def test_production_transport_proxy_replaces_ssh_tunnel_when_enabled():
    script = RUNNER.read_text()
    start_start = script.index("start_tunnel() {")
    start_body = script[start_start : script.index("\nstop_tunnel() {", start_start)]
    run_start = script.index("run_cmd() {")
    run_body = script[run_start : script.index("\n}", run_start)]

    assert "production_transport_proxy.py\" client" in start_body
    assert "--remote-port \"$PERMEANT_PRODUCTION_TRANSPORT_PORT\"" in start_body
    assert "ssh -N" in start_body
    assert "generate_production_transport_certs" in run_body
    assert "copy_production_transport_certs_to_target" in run_body
    assert run_body.index("generate_production_transport_certs") < run_body.index("start_target")
    assert run_body.index("copy_production_transport_certs_to_target") < run_body.index("start_target")


def test_target_starts_production_wss_proxy():
    script = RUNNER.read_text()
    remote_start = script.index('cat > "$REMOTE_START_SCRIPT" <<REMOTE_START')
    remote_body = script[remote_start : script.index("\nREMOTE_START", remote_start)]

    assert "production_transport_proxy.py server" in remote_body
    assert "--target-port 29099" in remote_body
    assert "--cafile '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/ca.crt'" in remote_body

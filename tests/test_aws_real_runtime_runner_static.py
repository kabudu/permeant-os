from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "aws-real-runtime-e2e.sh"


def shell_function(name):
    script = RUNNER.read_text()
    start = script.index(f"{name}() {{")
    return script[start : script.index("\n}", start) + 2]


@pytest.mark.parametrize(
    "case,expected_phases",
    [
        ("success", ["fence_verified", "stale_source_write_rejected", "checkpoint_downloaded", "checkpoint_verified"]),
        ("unfenced", ["fence_verified"]),
        ("bad_digest", ["fence_verified", "stale_source_write_rejected", "checkpoint_downloaded"]),
        ("missing", ["fence_verified", "stale_source_write_rejected"]),
    ],
)
@pytest.mark.parametrize("codec", ["none", "zstd"])
def test_recovery_trigger_keeps_fence_and_digest_gates(tmp_path, case, expected_phases, codec):
    trusted = b"trusted checkpoint\n" * 128
    corrupt = b"corrupt checkpoint\n" * 128
    (tmp_path / "trusted.json").write_bytes(trusted)
    (tmp_path / "checkpoint.capture.json").write_bytes(corrupt)
    artifact = b""
    if codec == "zstd":
        if not shutil.which("zstd"):
            pytest.skip("Zstd CLI is needed for compressed checkpoint tests")
        artifact = subprocess.run(
            ["zstd", "-q", "-3", "-c"], input=corrupt if case == "bad_digest" else trusted,
            capture_output=True, check=True, timeout=10,
        ).stdout
        (tmp_path / "trusted.zst").write_bytes(artifact)
    functions = "\n".join(shell_function(name) for name in (
        "record_recovery_phase", "assert_recovery_write_denied", "restore_trusted_checkpoint", "trigger_trusted_recovery",
    ))
    setup = """
        die() { echo "$*" >&2; exit 1; }
        recovery_clock_sample() { printf '1 2 3\\n'; }
        recovery_gateway() {
            read -r request
            if [[ "$1" == fence ]]; then
                printf '{"epoch":2}\\n'
            elif [[ "$CASE" == unfenced ]]; then
                printf '{"status":"completed"}\\n'
            else
                printf '{"status":"lease_rejected","epoch":2}\\n'
            fi
        }
        json_get() {
            python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$@"
        }
        scp_from_target() {
            if [[ "$CASE" == missing ]]; then
                touch "$2" # A failed transfer may leave a partial file.
                return 1
            elif [[ "$1" == *.zst ]]; then
                cp "$RUN_DIR/trusted.zst" "$2"
            elif [[ "$CASE" == bad_digest ]]; then
                cp "$RUN_DIR/checkpoint.capture.json" "$2"
            else
                cp "$RUN_DIR/trusted.json" "$2"
            fi
        }
        SOURCE_WRITE_LEASE=source-fixture
    """
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", f"{setup}\n{functions}\ntrigger_trusted_recovery"],
        env={
            **os.environ,
            "RUN_DIR": str(tmp_path),
            "CASE": case,
            "ROOT_DIR": str(ROOT),
            "PERMEANT_RECOVERY_CHECKPOINT_CODEC": codec,
            "CHECKPOINT_SHA": hashlib.sha256(trusted).hexdigest(),
            "CHECKPOINT_PLAINTEXT_BYTES": str(len(trusted)),
            "CHECKPOINT_ARTIFACT_BYTES": str(len(artifact)),
            "CHECKPOINT_ARTIFACT_SHA": hashlib.sha256(artifact).hexdigest(),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    marks = [line.split("\t") for line in (tmp_path / "recovery-phases.tsv").read_text().splitlines()]
    assert [name for name, _ in marks] == ["alert", *expected_phases]
    times = [int(value) for _, value in marks]
    assert times == sorted(times)
    assert result.returncode == (0 if case == "success" else 1), result.stderr
    restored = tmp_path / "checkpoint.restore.json"
    if case == "success":
        assert restored.read_bytes() == trusted
    else:
        assert not restored.exists()
    assert not (tmp_path / "checkpoint.restore.json.download").exists()


@pytest.mark.parametrize("case", ["expired", "expired_at_verify", "success"])
def test_cleanup_requires_successful_aws_verification(tmp_path, case):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "cleanup_verified_at": "stale-marker", "root_volume_id": "vol-fixture", "primary_eni_id": "eni-fixture",
    }))
    pem = tmp_path / "temporary.pem"
    pem.write_text("fixture only")
    functions = "\n".join(shell_function(name) for name in ("json_get", "json_set", "cleanup_cmd"))
    setup = """
        load_state() { RUN_ID=fixture; AWS_REGION=us-east-1; KEY_NAME=key-fixture; RUN_DIR=''; PRODUCTION_TRANSPORT_CERT_DIR=''; }
        stop_tunnel() { :; }
        stop_recovery_ssh_master() { :; }
        instance_id() { echo i-fixture; }
        security_group_id() { echo sg-fixture; }
        log() { echo "$*"; }
        die() { echo "$*" >&2; exit 1; }
        aws() {
            printf '%s\\n' "$2" >> "$COMMAND_LOG"
            case "$2" in
                describe-instances)
                    if [[ "$CASE" == expired ]]; then return 255; fi
                    echo running;;
                terminate-instances|wait) :;;
                describe-security-groups)
                    if [[ ! -e "$COMMAND_LOG.group" ]]; then echo 1
                    elif [[ "$CASE" == expired_at_verify ]]; then return 255
                    else echo 0; fi;;
                delete-security-group) touch "$COMMAND_LOG.group";;
                describe-key-pairs)
                    if [[ -e "$COMMAND_LOG.key" ]]; then echo 0; else echo 1; fi;;
                delete-key-pair) touch "$COMMAND_LOG.key";;
                describe-volumes|describe-network-interfaces) echo 0;;
                *) return 1;;
            esac
        }
    """
    commands = tmp_path / "commands"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", f'{setup}\n{functions}\ncleanup_cmd "$STATE_FILE" || exit 9'],
        env={
            **os.environ, "STATE_FILE": str(state), "PEM_FILE": str(pem),
            "COMMAND_LOG": str(commands), "CASE": case,
        },
        capture_output=True, text=True, timeout=10,
    )
    if case == "success":
        assert result.returncode == 0, result.stderr
        assert json.loads(state.read_text())["cleanup_verified_at"] != "stale-marker"
        assert not pem.exists()
        assert commands.read_text().splitlines() == [
            "describe-instances", "terminate-instances", "wait",
            "describe-security-groups", "delete-security-group", "describe-security-groups",
            "describe-key-pairs", "delete-key-pair", "describe-key-pairs",
            "describe-volumes", "describe-network-interfaces",
        ]
    else:
        assert result.returncode == 9
        assert "cleanup_verified_at" not in json.loads(state.read_text())
        assert pem.exists()
        assert "cleanup complete" not in result.stdout
        if case == "expired":
            assert commands.read_text().splitlines() == ["describe-instances"]


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

    assert "openssl req -new" in cert_body
    assert "openssl x509 -req" in cert_body
    assert "-signkey \"$PRODUCTION_TRANSPORT_CERT_DIR/ca.key\"" in cert_body
    assert "basicConstraints=critical,CA:TRUE" in cert_body
    assert "keyUsage=critical,keyCertSign,cRLSign" in cert_body
    assert "extendedKeyUsage=serverAuth" in cert_body
    assert "extendedKeyUsage=clientAuth" in cert_body
    assert "keyUsage=critical,digitalSignature,keyEncipherment" in cert_body
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


def test_target_cargo_build_disables_http2_multiplexing_and_retries():
    script = RUNNER.read_text()
    setup_start = script.index('cat > "$REMOTE_SETUP_SCRIPT" <<\'REMOTE_SETUP\'')
    setup_body = script[setup_start : script.index("\nREMOTE_SETUP", setup_start)]

    assert "export CARGO_HTTP_MULTIPLEXING=false" in setup_body
    assert "for attempt in 1 2 3; do" in setup_body
    assert 'if cargo build --locked ${1:+"$1"}; then' in setup_body


def test_run_installs_cleanup_trap_before_provisioning():
    script = RUNNER.read_text()
    run_start = script.index("run_cmd() {")
    run_body = script[run_start : script.index("\n}", run_start)]

    trap = next(line for line in run_body.splitlines() if line.strip().startswith("trap "))
    assert '[[ -n "$(public_ip)" ]]; then collect_artifacts; fi ) || true' in trap
    assert 'cleanup_cmd "$STATE_FILE" || true' in trap
    assert run_body.index(trap) < run_body.index("provision")
    assert run_body.index(trap) < run_body.index("generate_production_transport_certs")


@pytest.mark.parametrize("probe", ["present", "empty", "missing"])
def test_required_fidelity_collection_does_not_collect_diagnostics(tmp_path, probe):
    functions = "\n".join(shell_function(name) for name in (
        "collect_fidelity_probe", "collect_target_diagnostics", "collect_artifacts",
    ))
    setup = """
        log() { :; }
        scp_from_target() {
            printf '%s\\n' "$1" >> "$TRANSFERS"
            if [[ "$1" == /tmp/permeant-vllm-runtime-probe.json ]]; then
                case "$PROBE" in
                    present) printf '{"events":[]}\\n' > "$2";;
                    empty) : > "$2";;
                    missing) return 1;;
                esac
            fi
        }
    """
    transfers = tmp_path / "transfers"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", f"{setup}\n{functions}\ncollect_fidelity_probe"],
        env={
            **os.environ, "TRANSFERS": str(transfers), "PROBE": probe,
            "TARGET_PROBE_LOCAL": str(tmp_path / "probe.json"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (0 if probe == "present" else 1), result.stderr
    assert transfers.read_text().splitlines() == ["/tmp/permeant-vllm-runtime-probe.json"]


def test_deferred_diagnostics_follow_fidelity_and_exactly_once_task_gates():
    run_body = shell_function("run_cmd")
    checkpoint = run_body.index("trigger_trusted_recovery")
    migration = run_body.index("\n  run_migration")
    probe = run_body.index("\n    collect_fidelity_probe")
    compression = run_body.index("\n  enforce_qatq_live_compression_gate")
    fidelity = run_body.index("record_recovery_phase fidelity_verified")
    task = run_body.index("record_recovery_phase task_commit_observed")
    replay = run_body.index("record_recovery_phase task_replay_rejected")
    diagnostics = run_body.index("\n      collect_target_diagnostics")
    assert checkpoint < migration < probe < compression < fidelity < task < replay < diagnostics
    assert "record_recovery_phase diagnostics_collection_finished" in run_body[diagnostics:]

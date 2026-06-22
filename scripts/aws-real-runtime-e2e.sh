#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/aws-real-runtime-e2e.sh run
  scripts/aws-real-runtime-e2e.sh preflight
  scripts/aws-real-runtime-e2e.sh status [STATE_FILE]
  scripts/aws-real-runtime-e2e.sh cleanup [STATE_FILE]

Environment overrides:
  AWS_REGION                         default: us-east-1
  AWS_AZ                             default: us-east-1d
  AWS_INSTANCE_TYPE                  default: g4dn.xlarge
  AWS_AMI_ID                         default: ami-01011b868ec560823
  PERMEANT_VALIDATION_PROFILE        default: qwen2.5-0.5b-mlx-vllm
  PERMEANT_MODEL                     default: Qwen/Qwen2.5-0.5B-Instruct
  PERMEANT_MODEL_FAMILY              optional; required for custom profile
  PERMEANT_SOURCE_RUNTIME            default: mlx
  PERMEANT_TARGET_RUNTIME            default: vllm
  PERMEANT_SEQ_LEN                   default: 2016
  PERMEANT_VLLM_MAX_MODEL_LEN        default: 2048
  PERMEANT_TRANSFER_QUANTIZATION     default: none (none, fp8, qatq)
  PERMEANT_QATQ_STANDALONE_PATH      default: ../qatq when qatq transfer is used
  PERMEANT_CONTINUATION_MAX_TOKENS   default: 16
  PERMEANT_FIDELITY_HORIZONS         default: 16,32,64,128
  PERMEANT_SOURCE_URL                default: http://127.0.0.1:29101
  PERMEANT_SOURCE_CONTINUATION_FILE  default: /tmp/permeant-source-continuation.json
  PERMEANT_AGENT_GRAPH_MANIFEST      optional local Agent Memory Graph manifest
  PERMEANT_AGENT_ACTIVITY_RESUME     default: 0; run Agent Memory Graph resume proof on target
  PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH default: 0; approve gated local publish proof
  PERMEANT_AGENT_ACTIVITY_RETURN_HOME default: 0; verify AWS-updated graph and continue on origin
  PERMEANT_REVERSE_RUNTIME_IMPORT    default: 0; import vLLM target decode boundary back into MLX origin
  PERMEANT_MIGRATION_TRANSPORT       default: production-wss (production-wss, ssh-tunnel)
  PERMEANT_PRODUCTION_TRANSPORT_PORT default: 29443
  PERMEANT_LOCAL_TUNNEL_PORT         default: 39099
  PERMEANT_STATE_DIR                 default: .permeant-e2e/aws
  PERMEANT_PREFLIGHT_SKIP_AWS        default: 0
  PERMEANT_PREFLIGHT_SKIP_BUILD      default: 0
  PERMEANT_PREFLIGHT_SKIP_SOURCE     default: 0

The runner is state-file driven. If anything fails after provisioning, run:
  scripts/aws-real-runtime-e2e.sh cleanup .permeant-e2e/aws/<run-id>/state.json
USAGE
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMAND="${1:-}"

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_AZ="${AWS_AZ:-us-east-1d}"
AWS_INSTANCE_TYPE="${AWS_INSTANCE_TYPE:-g4dn.xlarge}"
AWS_AMI_ID="${AWS_AMI_ID:-ami-01011b868ec560823}"
PERMEANT_VALIDATION_PROFILE="${PERMEANT_VALIDATION_PROFILE:-qwen2.5-0.5b-mlx-vllm}"
PERMEANT_MODEL="${PERMEANT_MODEL:-Qwen/Qwen2.5-0.5B-Instruct}"
PERMEANT_MODEL_FAMILY="${PERMEANT_MODEL_FAMILY:-}"
PERMEANT_SOURCE_RUNTIME="${PERMEANT_SOURCE_RUNTIME:-mlx}"
PERMEANT_TARGET_RUNTIME="${PERMEANT_TARGET_RUNTIME:-vllm}"
PERMEANT_SEQ_LEN="${PERMEANT_SEQ_LEN:-2016}"
PERMEANT_VLLM_MAX_MODEL_LEN="${PERMEANT_VLLM_MAX_MODEL_LEN:-2048}"
PERMEANT_TRANSFER_QUANTIZATION="${PERMEANT_TRANSFER_QUANTIZATION:-none}"
PERMEANT_QATQ_STANDALONE_PATH="${PERMEANT_QATQ_STANDALONE_PATH:-$ROOT_DIR/../qatq}"
PERMEANT_CONTINUATION_MAX_TOKENS="${PERMEANT_CONTINUATION_MAX_TOKENS:-16}"
PERMEANT_FIDELITY_HORIZONS="${PERMEANT_FIDELITY_HORIZONS:-16,32,64,128}"
PERMEANT_SOURCE_URL="${PERMEANT_SOURCE_URL:-http://127.0.0.1:29101}"
PERMEANT_SOURCE_CONTINUATION_FILE="${PERMEANT_SOURCE_CONTINUATION_FILE:-/tmp/permeant-source-continuation.json}"
PERMEANT_AGENT_GRAPH_MANIFEST="${PERMEANT_AGENT_GRAPH_MANIFEST:-}"
PERMEANT_AGENT_ACTIVITY_RESUME="${PERMEANT_AGENT_ACTIVITY_RESUME:-0}"
PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH="${PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH:-0}"
PERMEANT_AGENT_ACTIVITY_RETURN_HOME="${PERMEANT_AGENT_ACTIVITY_RETURN_HOME:-0}"
PERMEANT_REVERSE_RUNTIME_IMPORT="${PERMEANT_REVERSE_RUNTIME_IMPORT:-0}"
PERMEANT_MIGRATION_TRANSPORT="${PERMEANT_MIGRATION_TRANSPORT:-production-wss}"
PERMEANT_PRODUCTION_TRANSPORT_PORT="${PERMEANT_PRODUCTION_TRANSPORT_PORT:-29443}"
PERMEANT_LOCAL_TUNNEL_PORT="${PERMEANT_LOCAL_TUNNEL_PORT:-39099}"
PERMEANT_STATE_DIR="${PERMEANT_STATE_DIR:-$ROOT_DIR/.permeant-e2e/aws}"
PERMEANT_PREFLIGHT_SKIP_AWS="${PERMEANT_PREFLIGHT_SKIP_AWS:-0}"
PERMEANT_PREFLIGHT_SKIP_BUILD="${PERMEANT_PREFLIGHT_SKIP_BUILD:-0}"
PERMEANT_PREFLIGHT_SKIP_SOURCE="${PERMEANT_PREFLIGHT_SKIP_SOURCE:-0}"

STATE_FILE=""
RUN_DIR=""
RUN_ID=""
PREFIX=""
KEY_NAME=""
PEM_FILE=""
KNOWN_HOSTS_FILE=""
REMOTE_SETUP_SCRIPT=""
REMOTE_START_SCRIPT=""
TARGET_PROBE_LOCAL=""
TARGET_LOG_DIR=""
TUNNEL_PID_FILE=""
PRODUCTION_TRANSPORT_CERT_DIR=""
TARGET_PRODUCTION_TRANSPORT_CERT_DIR="/home/ubuntu/permeant-transport-certs"
TARGET_AGENT_GRAPH_PACKAGE="/home/ubuntu/permeant-agent-graph-package"
TARGET_AGENT_ACTIVITY_WORKSPACE="/tmp/permeant-agent-activity-workspace"
TARGET_AGENT_ACTIVITY_REPORT_LOCAL=""
TARGET_AGENT_ACTIVITY_GRAPH_LOCAL=""
TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL=""
ORIGIN_ROUNDTRIP_WORKSPACE=""
ORIGIN_ROUNDTRIP_REPORT_LOCAL=""
ORIGIN_ROUNDTRIP_GRAPH_LOCAL=""
TARGET_REVERSE_RUNTIME_STATE_LOCAL=""
ORIGIN_REVERSE_IMPORT_REPORT_LOCAL=""

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

check_status() {
  local status="$1"
  local name="$2"
  local message="$3"
  printf '%s\t%s\t%s\n' "$status" "$name" "$message"
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

production_transport_enabled() {
  [[ "$PERMEANT_MIGRATION_TRANSPORT" == "production-wss" ]]
}

json_get() {
  local file="$1"
  local key="$2"
  python3 - "$file" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
print(data.get(key, ""))
PY
}

json_set() {
  local file="$1"
  local key="$2"
  local value="$3"
  python3 - "$file" "$key" "$value" <<'PY'
import json, sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
data[key] = value
with open(path, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\n")
PY
}

source_extract_url() {
  local base="${PERMEANT_SOURCE_URL%/}"
  if [[ "$base" == */extract ]]; then
    printf '%s\n' "$base"
  else
    printf '%s/extract\n' "$base"
  fi
}

source_reverse_import_url() {
  local base="${PERMEANT_SOURCE_URL%/}"
  if [[ "$base" == */extract ]]; then
    base="${base%/extract}"
  fi
  printf '%s/import-reverse-state\n' "$base"
}

validate_source_continuation_file() {
  python3 - "$PERMEANT_SOURCE_CONTINUATION_FILE" "$PERMEANT_SEQ_LEN" "$PERMEANT_CONTINUATION_MAX_TOKENS" "$PERMEANT_VLLM_MAX_MODEL_LEN" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
required_tokens = int(sys.argv[2])
continuation_tokens = int(sys.argv[3])
max_model_len = int(sys.argv[4])
try:
    payload = json.loads(path.read_text())
except FileNotFoundError:
    raise SystemExit(f"missing source continuation file: {path}")
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid source continuation JSON at {path}: {exc}")

prompt = payload.get("prompt")
prompt_token_count = payload.get("prompt_token_count")
prompt_token_ids = payload.get("prompt_token_ids")
if not isinstance(prompt, str) or not prompt:
    raise SystemExit("source continuation file does not contain a non-empty prompt")
if not isinstance(prompt_token_count, int):
    raise SystemExit("source continuation file does not contain integer prompt_token_count")
if prompt_token_count < required_tokens:
    raise SystemExit(
        f"source continuation prompt_token_count {prompt_token_count} is below required seq_len {required_tokens}"
    )
if prompt_token_count + continuation_tokens > max_model_len:
    raise SystemExit(
        "source continuation prompt leaves no target decode headroom: "
        f"prompt_token_count {prompt_token_count} + continuation {continuation_tokens} > "
        f"vLLM max model length {max_model_len}"
    )
if not isinstance(prompt_token_ids, list) or len(prompt_token_ids) < required_tokens:
    raise SystemExit(
        f"source continuation prompt_token_ids length is below required seq_len {required_tokens}"
    )
print(f"source continuation ready: prompt_token_count={prompt_token_count}")
PY
}

refresh_source_continuation() {
  log "refreshing source continuation from live exporter"
  curl -fsS \
    --max-time 900 \
    -H 'Content-Type: application/json' \
    --data "{\"seq_len\":$PERMEANT_SEQ_LEN}" \
    "$(source_extract_url)" >/dev/null
  validate_source_continuation_file
}

load_state() {
  STATE_FILE="${1:-$STATE_FILE}"
  [[ -f "$STATE_FILE" ]] || die "state file not found: $STATE_FILE"
  RUN_ID="$(json_get "$STATE_FILE" run_id)"
  PREFIX="$(json_get "$STATE_FILE" prefix)"
  KEY_NAME="$(json_get "$STATE_FILE" key_name)"
  PEM_FILE="$(json_get "$STATE_FILE" pem_file)"
  KNOWN_HOSTS_FILE="$(json_get "$STATE_FILE" known_hosts_file)"
  RUN_DIR="$(json_get "$STATE_FILE" run_dir)"
  TARGET_PROBE_LOCAL="$(json_get "$STATE_FILE" target_probe_local)"
  TUNNEL_PID_FILE="$RUN_DIR/tunnel.pid"
  TARGET_LOG_DIR="$RUN_DIR/target-logs"
  PRODUCTION_TRANSPORT_CERT_DIR="$(json_get "$STATE_FILE" production_transport_cert_dir)"
  TARGET_AGENT_ACTIVITY_REPORT_LOCAL="$(json_get "$STATE_FILE" target_agent_activity_report_local)"
  TARGET_AGENT_ACTIVITY_GRAPH_LOCAL="$(json_get "$STATE_FILE" target_agent_activity_graph_local)"
  TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL="$(json_get "$STATE_FILE" target_agent_activity_artifact_local)"
  ORIGIN_ROUNDTRIP_WORKSPACE="$(json_get "$STATE_FILE" origin_roundtrip_workspace)"
  ORIGIN_ROUNDTRIP_REPORT_LOCAL="$(json_get "$STATE_FILE" origin_roundtrip_report_local)"
  ORIGIN_ROUNDTRIP_GRAPH_LOCAL="$(json_get "$STATE_FILE" origin_roundtrip_graph_local)"
  TARGET_REVERSE_RUNTIME_STATE_LOCAL="$(json_get "$STATE_FILE" target_reverse_runtime_state_local)"
  ORIGIN_REVERSE_IMPORT_REPORT_LOCAL="$(json_get "$STATE_FILE" origin_reverse_import_report_local)"
}

instance_id() {
  json_get "$STATE_FILE" instance_id
}

security_group_id() {
  json_get "$STATE_FILE" security_group_id
}

public_ip() {
  local recorded
  recorded="$(json_get "$STATE_FILE" public_ip)"
  if [[ -n "$recorded" ]]; then
    printf '%s\n' "$recorded"
    return
  fi
  local id
  id="$(instance_id)"
  [[ -n "$id" ]] || return 0
  aws ec2 describe-instances \
    --region "$AWS_REGION" \
    --instance-ids "$id" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text 2>/dev/null | sed 's/^None$//'
}

ssh_target() {
  local ip
  ip="$(public_ip)"
  [[ -n "$ip" ]] || die "public IP not available"
  ssh \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -i "$PEM_FILE" \
    "ubuntu@$ip" "$@"
}

scp_to_target() {
  local src="$1"
  local dst="$2"
  local ip
  ip="$(public_ip)"
  [[ -n "$ip" ]] || die "public IP not available"
  scp \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -i "$PEM_FILE" \
    "$src" "ubuntu@$ip:$dst"
}

scp_from_target() {
  local src="$1"
  local dst="$2"
  local ip
  ip="$(public_ip)"
  [[ -n "$ip" ]] || die "public IP not available"
  scp \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -i "$PEM_FILE" \
    "ubuntu@$ip:$src" "$dst"
}

create_state() {
  RUN_ID="${RUN_ID:-$(date -u '+%Y%m%d-%H%M%S')}"
  PREFIX="permeantos-real-e2e-$RUN_ID"
  RUN_DIR="$PERMEANT_STATE_DIR/$RUN_ID"
  mkdir -p "$RUN_DIR"
  STATE_FILE="$RUN_DIR/state.json"
  KEY_NAME="$PREFIX-key"
  PEM_FILE="$RUN_DIR/$KEY_NAME.pem"
  KNOWN_HOSTS_FILE="$RUN_DIR/known_hosts"
  TARGET_PROBE_LOCAL="$RUN_DIR/vllm-runtime-probe.json"
  TARGET_LOG_DIR="$RUN_DIR/target-logs"
  TUNNEL_PID_FILE="$RUN_DIR/tunnel.pid"
  PRODUCTION_TRANSPORT_CERT_DIR="$RUN_DIR/production-transport-certs"
  TARGET_AGENT_ACTIVITY_REPORT_LOCAL="$RUN_DIR/agent-activity-resume-report.json"
  TARGET_AGENT_ACTIVITY_GRAPH_LOCAL="$RUN_DIR/agent-activity-resumed-graph.json"
  TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL="$RUN_DIR/agent-activity-publish-announcement.md"
  ORIGIN_ROUNDTRIP_WORKSPACE="$RUN_DIR/origin-roundtrip-workspace"
  ORIGIN_ROUNDTRIP_REPORT_LOCAL="$ORIGIN_ROUNDTRIP_WORKSPACE/reports/roundtrip/roundtrip-report.json"
  ORIGIN_ROUNDTRIP_GRAPH_LOCAL="$ORIGIN_ROUNDTRIP_WORKSPACE/reports/roundtrip/returned-home-graph.json"
  TARGET_REVERSE_RUNTIME_STATE_LOCAL="$RUN_DIR/vllm-reverse-runtime-state.json"
  ORIGIN_REVERSE_IMPORT_REPORT_LOCAL="$RUN_DIR/mlx-reverse-import-report.json"
  mkdir -p "$TARGET_LOG_DIR"

  python3 - "$STATE_FILE" <<PY
import json
data = {
  "run_id": "$RUN_ID",
  "prefix": "$PREFIX",
  "region": "$AWS_REGION",
  "az": "$AWS_AZ",
  "instance_type": "$AWS_INSTANCE_TYPE",
  "ami_id": "$AWS_AMI_ID",
  "validation_profile": "$PERMEANT_VALIDATION_PROFILE",
  "model": "$PERMEANT_MODEL",
  "model_family": "$PERMEANT_MODEL_FAMILY",
  "source_runtime": "$PERMEANT_SOURCE_RUNTIME",
  "target_runtime": "$PERMEANT_TARGET_RUNTIME",
  "seq_len": "$PERMEANT_SEQ_LEN",
  "vllm_max_model_len": "$PERMEANT_VLLM_MAX_MODEL_LEN",
  "transfer_quantization": "$PERMEANT_TRANSFER_QUANTIZATION",
  "qatq_standalone_path": "$PERMEANT_QATQ_STANDALONE_PATH",
  "model_layer_count": "${PERMEANT_MODEL_LAYER_COUNT:-}",
  "model_q_heads": "${PERMEANT_MODEL_Q_HEADS:-}",
  "model_kv_heads": "${PERMEANT_MODEL_KV_HEADS:-}",
  "model_head_dim": "${PERMEANT_MODEL_HEAD_DIM:-}",
  "model_hidden_size": "${PERMEANT_MODEL_HIDDEN_SIZE:-}",
  "model_block_size": "${PERMEANT_MODEL_BLOCK_SIZE:-}",
  "continuation_max_tokens": "$PERMEANT_CONTINUATION_MAX_TOKENS",
  "fidelity_horizons": "$PERMEANT_FIDELITY_HORIZONS",
  "source_url": "$PERMEANT_SOURCE_URL",
  "source_continuation_file": "$PERMEANT_SOURCE_CONTINUATION_FILE",
  "agent_graph_manifest": "$PERMEANT_AGENT_GRAPH_MANIFEST",
  "agent_activity_resume": "$PERMEANT_AGENT_ACTIVITY_RESUME",
  "agent_activity_approve_publish": "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH",
  "agent_activity_return_home": "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME",
  "reverse_runtime_import": "$PERMEANT_REVERSE_RUNTIME_IMPORT",
  "migration_transport": "$PERMEANT_MIGRATION_TRANSPORT",
  "production_transport_port": "$PERMEANT_PRODUCTION_TRANSPORT_PORT",
  "production_transport_cert_dir": "$PRODUCTION_TRANSPORT_CERT_DIR",
  "local_tunnel_port": "$PERMEANT_LOCAL_TUNNEL_PORT",
  "run_dir": "$RUN_DIR",
  "key_name": "$KEY_NAME",
  "pem_file": "$PEM_FILE",
  "known_hosts_file": "$KNOWN_HOSTS_FILE",
  "target_probe_local": "$TARGET_PROBE_LOCAL",
  "target_agent_activity_report_local": "$TARGET_AGENT_ACTIVITY_REPORT_LOCAL",
  "target_agent_activity_graph_local": "$TARGET_AGENT_ACTIVITY_GRAPH_LOCAL",
  "target_agent_activity_artifact_local": "$TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL",
  "origin_roundtrip_workspace": "$ORIGIN_ROUNDTRIP_WORKSPACE",
  "origin_roundtrip_report_local": "$ORIGIN_ROUNDTRIP_REPORT_LOCAL",
  "origin_roundtrip_graph_local": "$ORIGIN_ROUNDTRIP_GRAPH_LOCAL",
  "target_reverse_runtime_state_local": "$TARGET_REVERSE_RUNTIME_STATE_LOCAL",
  "origin_reverse_import_report_local": "$ORIGIN_REVERSE_IMPORT_REPORT_LOCAL"
}
with open("$STATE_FILE", "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\\n")
PY
}

validate_numeric_config() {
  [[ "$PERMEANT_SEQ_LEN" =~ ^[0-9]+$ ]] || return 1
  [[ "$PERMEANT_VLLM_MAX_MODEL_LEN" =~ ^[0-9]+$ ]] || return 1
  [[ "$PERMEANT_CONTINUATION_MAX_TOKENS" =~ ^[0-9]+$ ]] || return 1
  [[ "$PERMEANT_LOCAL_TUNNEL_PORT" =~ ^[0-9]+$ ]] || return 1
  [[ "$PERMEANT_PRODUCTION_TRANSPORT_PORT" =~ ^[0-9]+$ ]] || return 1
  (( PERMEANT_SEQ_LEN > 0 )) || return 1
  (( PERMEANT_VLLM_MAX_MODEL_LEN > PERMEANT_SEQ_LEN )) || return 1
  (( PERMEANT_SEQ_LEN + PERMEANT_CONTINUATION_MAX_TOKENS <= PERMEANT_VLLM_MAX_MODEL_LEN )) || return 1
  (( PERMEANT_CONTINUATION_MAX_TOKENS > 0 )) || return 1
  (( PERMEANT_LOCAL_TUNNEL_PORT > 0 && PERMEANT_LOCAL_TUNNEL_PORT <= 65535 )) || return 1
  (( PERMEANT_PRODUCTION_TRANSPORT_PORT > 0 && PERMEANT_PRODUCTION_TRANSPORT_PORT <= 65535 )) || return 1
}

validation_profile_expected() {
  case "$PERMEANT_VALIDATION_PROFILE" in
    qwen2.5-0.5b-mlx-vllm)
      printf '%s\t%s\t%s\t%s\n' "Qwen/Qwen2.5-0.5B-Instruct" "qwen2.5" "mlx" "vllm"
      ;;
    qwen2.5-1.5b-mlx-vllm)
      printf '%s\t%s\t%s\t%s\n' "Qwen/Qwen2.5-1.5B-Instruct" "qwen2.5" "mlx" "vllm"
      ;;
    qwen2.5-0.5b-long-horizon-aws)
      printf '%s\t%s\t%s\t%s\n' "Qwen/Qwen2.5-0.5B-Instruct" "qwen2.5" "mlx" "vllm"
      ;;
    tinyllama-1.1b-chat-mlx-vllm)
      printf '%s\t%s\t%s\t%s\n' "TinyLlama/TinyLlama-1.1B-Chat-v1.0" "llama" "mlx" "vllm"
      ;;
    gemma-2-2b-it-mlx-vllm)
      printf '%s\t%s\t%s\t%s\n' "google/gemma-2-2b-it" "gemma2" "mlx" "vllm"
      ;;
    phi-3.5-mini-mlx-vllm)
      printf '%s\t%s\t%s\t%s\n' "microsoft/Phi-3.5-mini-instruct" "phi3.5" "mlx" "vllm"
      ;;
    custom)
      if [[ -n "$PERMEANT_MODEL" && -n "$PERMEANT_MODEL_FAMILY" && -n "$PERMEANT_SOURCE_RUNTIME" && -n "$PERMEANT_TARGET_RUNTIME" ]]; then
        printf '%s\t%s\t%s\t%s\n' "$PERMEANT_MODEL" "$PERMEANT_MODEL_FAMILY" "$PERMEANT_SOURCE_RUNTIME" "$PERMEANT_TARGET_RUNTIME"
      else
        return 1
      fi
      ;;
    *)
      return 2
      ;;
  esac
}

validation_profile_cache_spec() {
  case "$PERMEANT_VALIDATION_PROFILE" in
    qwen2.5-0.5b-mlx-vllm|qwen2.5-0.5b-long-horizon-aws)
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "24" "14" "2" "64" "896" "256"
      ;;
    qwen2.5-1.5b-mlx-vllm)
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "28" "12" "2" "128" "1536" "256"
      ;;
    tinyllama-1.1b-chat-mlx-vllm)
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "22" "32" "4" "64" "2048" "256"
      ;;
    gemma-2-2b-it-mlx-vllm)
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "26" "8" "4" "256" "2304" "256"
      ;;
    phi-3.5-mini-mlx-vllm)
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "32" "32" "32" "96" "3072" "256"
      ;;
    custom)
      return 1
      ;;
    *)
      return 2
      ;;
  esac
}

apply_validation_profile_cache_spec() {
  local profile_spec profile_status layer_count q_heads kv_heads head_dim hidden_size block_size
  profile_spec="$(validation_profile_cache_spec 2>/dev/null)" && profile_status=0 || profile_status=$?
  if [[ "$profile_status" != "0" ]]; then
    return 0
  fi
  IFS=$'\t' read -r layer_count q_heads kv_heads head_dim hidden_size block_size <<< "$profile_spec"
  export PERMEANT_MODEL_LAYER_COUNT="${PERMEANT_MODEL_LAYER_COUNT:-$layer_count}"
  export PERMEANT_MODEL_Q_HEADS="${PERMEANT_MODEL_Q_HEADS:-$q_heads}"
  export PERMEANT_MODEL_KV_HEADS="${PERMEANT_MODEL_KV_HEADS:-$kv_heads}"
  export PERMEANT_MODEL_HEAD_DIM="${PERMEANT_MODEL_HEAD_DIM:-$head_dim}"
  export PERMEANT_MODEL_HIDDEN_SIZE="${PERMEANT_MODEL_HIDDEN_SIZE:-$hidden_size}"
  export PERMEANT_MODEL_BLOCK_SIZE="${PERMEANT_MODEL_BLOCK_SIZE:-$block_size}"
}

write_preflight_report() {
  local report_file="$1"
  local checks_file="$2"
  python3 - "$report_file" "$STATE_FILE" "$checks_file" <<'PY'
import json
import sys
from pathlib import Path

report_path, state_path, checks_path = sys.argv[1], sys.argv[2], sys.argv[3]
checks = []
for raw in Path(checks_path).read_text().splitlines():
    status, name, message = raw.split("\t", 2)
    checks.append({"status": status, "name": name, "message": message})
failed = [check for check in checks if check["status"] == "fail"]
skipped = [check for check in checks if check["status"] == "skip"]
state = json.loads(Path(state_path).read_text())
report = {
    "schema_version": "permeantos-aws-e2e-preflight-v0",
    "ok": not failed,
    "failed_count": len(failed),
    "skipped_count": len(skipped),
    "checks": checks,
    "state_file": state_path,
    "run_id": state.get("run_id"),
    "region": state.get("region"),
    "az": state.get("az"),
    "instance_type": state.get("instance_type"),
    "ami_id": state.get("ami_id"),
    "validation_profile": state.get("validation_profile"),
    "model": state.get("model"),
    "model_family": state.get("model_family"),
    "source_runtime": state.get("source_runtime"),
    "target_runtime": state.get("target_runtime"),
    "seq_len": state.get("seq_len"),
    "vllm_max_model_len": state.get("vllm_max_model_len"),
    "transfer_quantization": state.get("transfer_quantization"),
}
Path(report_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, indent=2, sort_keys=True))
PY
}

preflight_cmd() {
  create_state
  rm -f "$PERMEANT_STATE_DIR/latest"
  ln -s "$RUN_DIR" "$PERMEANT_STATE_DIR/latest"
  local checks_file report_file
  checks_file="$RUN_DIR/preflight-checks.tsv"
  report_file="$RUN_DIR/preflight-report.json"
  : > "$checks_file"

  local required_commands=(curl git python3 scp ssh ssh-keyscan)
  if [[ "$PERMEANT_PREFLIGHT_SKIP_AWS" != "1" ]]; then
    required_commands+=(aws)
  fi
  for command_name in "${required_commands[@]}"; do
    if command -v "$command_name" >/dev/null 2>&1; then
      check_status pass "command:$command_name" "found" >> "$checks_file"
    else
      check_status fail "command:$command_name" "missing required command" >> "$checks_file"
    fi
  done

  if validate_numeric_config; then
    check_status pass "configuration:numeric" "sequence length, context window, continuation tokens, and tunnel ports leave room for validation continuation" >> "$checks_file"
  else
    check_status fail "configuration:numeric" "invalid numeric configuration or vLLM max model length cannot fit migrated sequence plus continuation tokens" >> "$checks_file"
  fi

  local expected_profile expected_model expected_family expected_source expected_target profile_status
  expected_profile="$(validation_profile_expected 2>/dev/null)" && profile_status=0 || profile_status=$?
  if [[ "$profile_status" == "0" ]]; then
    IFS=$'\t' read -r expected_model expected_family expected_source expected_target <<< "$expected_profile"
    if [[ "$PERMEANT_MODEL" != "$expected_model" ]]; then
      check_status fail "configuration:validation_profile" "$PERMEANT_VALIDATION_PROFILE expects PERMEANT_MODEL=$expected_model, got $PERMEANT_MODEL" >> "$checks_file"
    elif [[ "$PERMEANT_SOURCE_RUNTIME" != "$expected_source" || "$PERMEANT_TARGET_RUNTIME" != "$expected_target" ]]; then
      check_status fail "configuration:validation_profile" "$PERMEANT_VALIDATION_PROFILE expects $expected_source->$expected_target, got $PERMEANT_SOURCE_RUNTIME->$PERMEANT_TARGET_RUNTIME" >> "$checks_file"
    elif [[ "$PERMEANT_VALIDATION_PROFILE" == "custom" && "$PERMEANT_MODEL_FAMILY" != "$expected_family" ]]; then
      check_status fail "configuration:validation_profile" "custom profile requires explicit PERMEANT_MODEL_FAMILY" >> "$checks_file"
    else
      check_status pass "configuration:validation_profile" "$PERMEANT_VALIDATION_PROFILE covers $expected_family on $expected_source->$expected_target" >> "$checks_file"
    fi
  elif [[ "$profile_status" == "1" ]]; then
    check_status fail "configuration:validation_profile" "custom profile requires PERMEANT_MODEL, PERMEANT_MODEL_FAMILY, PERMEANT_SOURCE_RUNTIME, and PERMEANT_TARGET_RUNTIME" >> "$checks_file"
  else
    check_status fail "configuration:validation_profile" "unknown PERMEANT_VALIDATION_PROFILE: $PERMEANT_VALIDATION_PROFILE" >> "$checks_file"
  fi

  if [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "none" || "$PERMEANT_TRANSFER_QUANTIZATION" == "fp8" || "$PERMEANT_TRANSFER_QUANTIZATION" == "qatq" ]]; then
    check_status pass "configuration:transfer_quantization" "$PERMEANT_TRANSFER_QUANTIZATION is supported by the current runner" >> "$checks_file"
  else
    check_status fail "configuration:transfer_quantization" "unsupported PERMEANT_TRANSFER_QUANTIZATION: $PERMEANT_TRANSFER_QUANTIZATION" >> "$checks_file"
  fi
  if [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "qatq" ]]; then
    if [[ -f "$PERMEANT_QATQ_STANDALONE_PATH/Cargo.toml" ]]; then
      check_status pass "local:qatq_standalone" "standalone QATQ crate found at $PERMEANT_QATQ_STANDALONE_PATH" >> "$checks_file"
    else
      check_status fail "local:qatq_standalone" "standalone QATQ crate missing at $PERMEANT_QATQ_STANDALONE_PATH" >> "$checks_file"
    fi
  fi

  if [[ "$PERMEANT_AGENT_ACTIVITY_RESUME" == "0" || "$PERMEANT_AGENT_ACTIVITY_RESUME" == "1" ]]; then
    check_status pass "configuration:agent_activity_resume" "$PERMEANT_AGENT_ACTIVITY_RESUME" >> "$checks_file"
  else
    check_status fail "configuration:agent_activity_resume" "PERMEANT_AGENT_ACTIVITY_RESUME must be 0 or 1" >> "$checks_file"
  fi

  if [[ "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH" == "0" || "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH" == "1" ]]; then
    check_status pass "configuration:agent_activity_approve_publish" "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH" >> "$checks_file"
  else
    check_status fail "configuration:agent_activity_approve_publish" "PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH must be 0 or 1" >> "$checks_file"
  fi

  if [[ "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "0" || "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "1" ]]; then
    check_status pass "configuration:agent_activity_return_home" "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" >> "$checks_file"
  else
    check_status fail "configuration:agent_activity_return_home" "PERMEANT_AGENT_ACTIVITY_RETURN_HOME must be 0 or 1" >> "$checks_file"
  fi

  if [[ "$PERMEANT_REVERSE_RUNTIME_IMPORT" == "0" || "$PERMEANT_REVERSE_RUNTIME_IMPORT" == "1" ]]; then
    check_status pass "configuration:reverse_runtime_import" "$PERMEANT_REVERSE_RUNTIME_IMPORT" >> "$checks_file"
  else
    check_status fail "configuration:reverse_runtime_import" "PERMEANT_REVERSE_RUNTIME_IMPORT must be 0 or 1" >> "$checks_file"
  fi

  if [[ "$PERMEANT_MIGRATION_TRANSPORT" == "production-wss" || "$PERMEANT_MIGRATION_TRANSPORT" == "ssh-tunnel" ]]; then
    check_status pass "configuration:migration_transport" "$PERMEANT_MIGRATION_TRANSPORT" >> "$checks_file"
  else
    check_status fail "configuration:migration_transport" "PERMEANT_MIGRATION_TRANSPORT must be production-wss or ssh-tunnel" >> "$checks_file"
  fi

  if production_transport_enabled; then
    if command -v openssl >/dev/null 2>&1; then
      check_status pass "command:openssl" "found" >> "$checks_file"
    else
      check_status fail "command:openssl" "production-wss transport requires openssl for ephemeral mTLS certs" >> "$checks_file"
    fi
  else
    check_status skip "command:openssl" "PERMEANT_MIGRATION_TRANSPORT=$PERMEANT_MIGRATION_TRANSPORT" >> "$checks_file"
  fi

  if [[ "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "1" && "$PERMEANT_AGENT_ACTIVITY_RESUME" != "1" ]]; then
    check_status fail "configuration:agent_activity_return_home_requires_resume" "return-home proof requires PERMEANT_AGENT_ACTIVITY_RESUME=1" >> "$checks_file"
  elif [[ "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "1" ]]; then
    check_status pass "configuration:agent_activity_return_home_requires_resume" "target resume is enabled" >> "$checks_file"
  else
    check_status skip "configuration:agent_activity_return_home_requires_resume" "PERMEANT_AGENT_ACTIVITY_RETURN_HOME=0" >> "$checks_file"
  fi

  if [[ "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "1" && "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH" != "1" ]]; then
    check_status fail "configuration:agent_activity_return_home_requires_publish" "return-home proof requires PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH=1 so a target artifact exists" >> "$checks_file"
  elif [[ "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "1" ]]; then
    check_status pass "configuration:agent_activity_return_home_requires_publish" "target publish artifact will be produced" >> "$checks_file"
  else
    check_status skip "configuration:agent_activity_return_home_requires_publish" "PERMEANT_AGENT_ACTIVITY_RETURN_HOME=0" >> "$checks_file"
  fi

  if [[ "$PERMEANT_PREFLIGHT_SKIP_BUILD" == "1" ]]; then
    check_status skip "local:permeant_cli" "skipped by PERMEANT_PREFLIGHT_SKIP_BUILD=1" >> "$checks_file"
  elif [[ -x "$ROOT_DIR/target/debug/permeant-cli" ]]; then
    check_status pass "local:permeant_cli" "target/debug/permeant-cli exists" >> "$checks_file"
  else
    check_status fail "local:permeant_cli" "missing local target/debug/permeant-cli; run cargo build before E2E" >> "$checks_file"
  fi

  if [[ "$PERMEANT_PREFLIGHT_SKIP_SOURCE" == "1" ]]; then
    check_status skip "source:continuation_file" "skipped by PERMEANT_PREFLIGHT_SKIP_SOURCE=1" >> "$checks_file"
    check_status skip "source:mlx_exporter" "skipped by PERMEANT_PREFLIGHT_SKIP_SOURCE=1" >> "$checks_file"
  else
    if [[ -f "$PERMEANT_SOURCE_CONTINUATION_FILE" ]]; then
      check_status pass "source:continuation_file" "$PERMEANT_SOURCE_CONTINUATION_FILE exists" >> "$checks_file"
    else
      check_status fail "source:continuation_file" "missing source continuation file: $PERMEANT_SOURCE_CONTINUATION_FILE" >> "$checks_file"
    fi
    if curl -fsS --max-time 2 "$PERMEANT_SOURCE_URL" >/dev/null 2>&1; then
      check_status pass "source:mlx_exporter" "$PERMEANT_SOURCE_URL is reachable" >> "$checks_file"
    else
      check_status fail "source:mlx_exporter" "$PERMEANT_SOURCE_URL is not reachable" >> "$checks_file"
    fi
  fi

  if [[ -z "$PERMEANT_AGENT_GRAPH_MANIFEST" ]]; then
    check_status skip "source:agent_graph_manifest" "PERMEANT_AGENT_GRAPH_MANIFEST is not set" >> "$checks_file"
  elif [[ -f "$PERMEANT_AGENT_GRAPH_MANIFEST" ]]; then
    check_status pass "source:agent_graph_manifest" "$PERMEANT_AGENT_GRAPH_MANIFEST exists" >> "$checks_file"
  else
    check_status fail "source:agent_graph_manifest" "missing Agent Memory Graph manifest: $PERMEANT_AGENT_GRAPH_MANIFEST" >> "$checks_file"
  fi

  if [[ "$PERMEANT_AGENT_ACTIVITY_RESUME" == "1" ]]; then
    if [[ -z "$PERMEANT_AGENT_GRAPH_MANIFEST" ]]; then
      check_status fail "source:agent_activity_package" "agent activity resume requires PERMEANT_AGENT_GRAPH_MANIFEST" >> "$checks_file"
    else
      local graph_package_dir
      graph_package_dir="$(cd "$(dirname "$PERMEANT_AGENT_GRAPH_MANIFEST")" 2>/dev/null && pwd || true)"
      if [[ -f "$graph_package_dir/manifest.json" && -f "$graph_package_dir/graph.json" ]]; then
        check_status pass "source:agent_activity_package" "$graph_package_dir contains manifest.json and graph.json" >> "$checks_file"
      else
        check_status fail "source:agent_activity_package" "Agent Memory Graph package must contain manifest.json and graph.json" >> "$checks_file"
      fi
    fi
  else
    check_status skip "source:agent_activity_package" "PERMEANT_AGENT_ACTIVITY_RESUME=0" >> "$checks_file"
  fi

  if [[ "$PERMEANT_PREFLIGHT_SKIP_AWS" == "1" ]]; then
    check_status skip "aws:identity" "skipped by PERMEANT_PREFLIGHT_SKIP_AWS=1" >> "$checks_file"
    check_status skip "aws:network" "skipped by PERMEANT_PREFLIGHT_SKIP_AWS=1" >> "$checks_file"
    check_status skip "aws:ami" "skipped by PERMEANT_PREFLIGHT_SKIP_AWS=1" >> "$checks_file"
  else
    if aws sts get-caller-identity --region "$AWS_REGION" >/dev/null 2>&1; then
      check_status pass "aws:identity" "AWS caller identity is available" >> "$checks_file"
    else
      check_status fail "aws:identity" "AWS caller identity is not available" >> "$checks_file"
    fi
    if aws ec2 describe-subnets --region "$AWS_REGION" --filters "Name=availability-zone,Values=$AWS_AZ" "Name=default-for-az,Values=true" --query 'Subnets[0].SubnetId' --output text >/dev/null 2>&1; then
      check_status pass "aws:network" "default subnet lookup succeeded for $AWS_AZ" >> "$checks_file"
    else
      check_status fail "aws:network" "default subnet lookup failed for $AWS_AZ" >> "$checks_file"
    fi
    if aws ec2 describe-images --region "$AWS_REGION" --image-ids "$AWS_AMI_ID" >/dev/null 2>&1; then
      check_status pass "aws:ami" "$AWS_AMI_ID is visible in $AWS_REGION" >> "$checks_file"
    else
      check_status fail "aws:ami" "$AWS_AMI_ID is not visible in $AWS_REGION" >> "$checks_file"
    fi
  fi

  write_preflight_report "$report_file" "$checks_file"
  json_set "$STATE_FILE" preflight_report "$report_file"
  log "preflight report: $report_file"
  python3 - "$report_file" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
raise SystemExit(0 if report["ok"] else 1)
PY
}

discover_network() {
  local vpc_id subnet_id my_ip
  my_ip="$(curl -sS https://checkip.amazonaws.com | tr -d '[:space:]')"
  [[ -n "$my_ip" ]] || die "could not discover current public IP"
  vpc_id="$(aws ec2 describe-vpcs --region "$AWS_REGION" --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
  subnet_id="$(aws ec2 describe-subnets --region "$AWS_REGION" --filters "Name=availability-zone,Values=$AWS_AZ" "Name=default-for-az,Values=true" --query 'Subnets[0].SubnetId' --output text)"
  [[ "$vpc_id" != "None" && -n "$vpc_id" ]] || die "default VPC not found in $AWS_REGION"
  [[ "$subnet_id" != "None" && -n "$subnet_id" ]] || die "default subnet not found in $AWS_AZ"
  json_set "$STATE_FILE" my_ip "$my_ip"
  json_set "$STATE_FILE" vpc_id "$vpc_id"
  json_set "$STATE_FILE" subnet_id "$subnet_id"
}

provision() {
  log "creating key pair, security group, and EC2 instance"
  local vpc_id subnet_id my_ip sg_id instance
  vpc_id="$(json_get "$STATE_FILE" vpc_id)"
  subnet_id="$(json_get "$STATE_FILE" subnet_id)"
  my_ip="$(json_get "$STATE_FILE" my_ip)"

  aws ec2 create-key-pair \
    --region "$AWS_REGION" \
    --key-name "$KEY_NAME" \
    --query 'KeyMaterial' \
    --output text > "$PEM_FILE"
  chmod 600 "$PEM_FILE"

  sg_id="$(aws ec2 create-security-group \
    --region "$AWS_REGION" \
    --group-name "$PREFIX-sg" \
    --description "$PREFIX temporary SSH access" \
    --vpc-id "$vpc_id" \
    --query GroupId \
    --output text)"
  json_set "$STATE_FILE" security_group_id "$sg_id"

  aws ec2 authorize-security-group-ingress \
    --region "$AWS_REGION" \
    --group-id "$sg_id" \
    --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$my_ip/32,Description=permeant-e2e-ssh}]" >/dev/null

  if production_transport_enabled; then
    aws ec2 authorize-security-group-ingress \
      --region "$AWS_REGION" \
      --group-id "$sg_id" \
      --ip-permissions "IpProtocol=tcp,FromPort=$PERMEANT_PRODUCTION_TRANSPORT_PORT,ToPort=$PERMEANT_PRODUCTION_TRANSPORT_PORT,IpRanges=[{CidrIp=$my_ip/32,Description=permeant-e2e-production-wss}]" >/dev/null
  fi

  instance="$(aws ec2 run-instances \
    --region "$AWS_REGION" \
    --image-id "$AWS_AMI_ID" \
    --instance-type "$AWS_INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$sg_id" \
    --subnet-id "$subnet_id" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":80,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$PREFIX-vm},{Key=Project,Value=permeant-os},{Key=RunId,Value=$RUN_ID}]" \
    --query 'Instances[0].InstanceId' \
    --output text)"
  json_set "$STATE_FILE" instance_id "$instance"

  aws ec2 wait instance-running --region "$AWS_REGION" --instance-ids "$instance"
  local ip
  ip="$(aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$instance" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
  json_set "$STATE_FILE" public_ip "$ip"

  log "waiting for SSH on $ip"
  : > "$KNOWN_HOSTS_FILE"
  for _ in $(seq 1 60); do
    if ssh-keyscan -T 5 "$ip" >> "$KNOWN_HOSTS_FILE" 2>/dev/null; then
      if ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" -i "$PEM_FILE" "ubuntu@$ip" 'echo connected' >/dev/null 2>&1; then
        return
      fi
    fi
    sleep 5
  done
  die "SSH did not become ready"
}

generate_production_transport_certs() {
  production_transport_enabled || return 0
  need openssl
  local ip
  ip="$(public_ip)"
  log "generating ephemeral production transport mTLS certificates"
  mkdir -p "$PRODUCTION_TRANSPORT_CERT_DIR"
  chmod 700 "$PRODUCTION_TRANSPORT_CERT_DIR"

  openssl genrsa -out "$PRODUCTION_TRANSPORT_CERT_DIR/ca.key" 2048 >/dev/null 2>&1
  {
    printf '[v3_ca]\n'
    printf 'basicConstraints=critical,CA:TRUE\n'
    printf 'keyUsage=critical,keyCertSign,cRLSign\n'
    printf 'subjectKeyIdentifier=hash\n'
  } > "$PRODUCTION_TRANSPORT_CERT_DIR/ca.ext"
  openssl req -new \
    -key "$PRODUCTION_TRANSPORT_CERT_DIR/ca.key" \
    -subj "/CN=permeant-e2e-ca-$RUN_ID" \
    -out "$PRODUCTION_TRANSPORT_CERT_DIR/ca.csr" >/dev/null 2>&1
  openssl x509 -req \
    -in "$PRODUCTION_TRANSPORT_CERT_DIR/ca.csr" \
    -signkey "$PRODUCTION_TRANSPORT_CERT_DIR/ca.key" \
    -sha256 \
    -days 1 \
    -extensions v3_ca \
    -extfile "$PRODUCTION_TRANSPORT_CERT_DIR/ca.ext" \
    -out "$PRODUCTION_TRANSPORT_CERT_DIR/ca.crt" >/dev/null 2>&1

  openssl genrsa -out "$PRODUCTION_TRANSPORT_CERT_DIR/server.key" 2048 >/dev/null 2>&1
  openssl req -new \
    -key "$PRODUCTION_TRANSPORT_CERT_DIR/server.key" \
    -subj "/CN=permeant-target" \
    -out "$PRODUCTION_TRANSPORT_CERT_DIR/server.csr" >/dev/null 2>&1
  {
    printf 'subjectAltName=DNS:permeant-target,IP:%s\n' "$ip"
    printf 'basicConstraints=critical,CA:FALSE\n'
    printf 'keyUsage=critical,digitalSignature,keyEncipherment\n'
    printf 'extendedKeyUsage=serverAuth\n'
  } > "$PRODUCTION_TRANSPORT_CERT_DIR/server.ext"
  openssl x509 -req \
    -in "$PRODUCTION_TRANSPORT_CERT_DIR/server.csr" \
    -CA "$PRODUCTION_TRANSPORT_CERT_DIR/ca.crt" \
    -CAkey "$PRODUCTION_TRANSPORT_CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$PRODUCTION_TRANSPORT_CERT_DIR/server.crt" \
    -days 1 \
    -sha256 \
    -extfile "$PRODUCTION_TRANSPORT_CERT_DIR/server.ext" >/dev/null 2>&1

  openssl genrsa -out "$PRODUCTION_TRANSPORT_CERT_DIR/client.key" 2048 >/dev/null 2>&1
  openssl req -new \
    -key "$PRODUCTION_TRANSPORT_CERT_DIR/client.key" \
    -subj "/CN=permeant-source" \
    -out "$PRODUCTION_TRANSPORT_CERT_DIR/client.csr" >/dev/null 2>&1
  {
    printf 'basicConstraints=critical,CA:FALSE\n'
    printf 'keyUsage=critical,digitalSignature,keyEncipherment\n'
    printf 'extendedKeyUsage=clientAuth\n'
  } > "$PRODUCTION_TRANSPORT_CERT_DIR/client.ext"
  openssl x509 -req \
    -in "$PRODUCTION_TRANSPORT_CERT_DIR/client.csr" \
    -CA "$PRODUCTION_TRANSPORT_CERT_DIR/ca.crt" \
    -CAkey "$PRODUCTION_TRANSPORT_CERT_DIR/ca.key" \
    -CAcreateserial \
    -out "$PRODUCTION_TRANSPORT_CERT_DIR/client.crt" \
    -days 1 \
    -sha256 \
    -extfile "$PRODUCTION_TRANSPORT_CERT_DIR/client.ext" >/dev/null 2>&1
  chmod 600 "$PRODUCTION_TRANSPORT_CERT_DIR"/*.key
  json_set "$STATE_FILE" production_transport_cert_dir "$PRODUCTION_TRANSPORT_CERT_DIR"
}

write_remote_scripts() {
  REMOTE_SETUP_SCRIPT="$RUN_DIR/remote-setup.sh"
  REMOTE_START_SCRIPT="$RUN_DIR/remote-start.sh"

  cat > "$REMOTE_SETUP_SCRIPT" <<'REMOTE_SETUP'
#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
wait_for_apt_locks() {
  local waited=0
  local locks=(
    /var/lib/dpkg/lock
    /var/lib/dpkg/lock-frontend
    /var/lib/apt/lists/lock
    /var/cache/apt/archives/lock
  )
  while sudo fuser "${locks[@]}" >/dev/null 2>&1; do
    if (( waited >= 600 )); then
      echo "timed out waiting for apt/dpkg lock holders" >&2
      sudo fuser -v "${locks[@]}" >&2 || true
      return 1
    fi
    echo "waiting for apt/dpkg lock holders to finish (${waited}s)"
    sleep 10
    waited=$((waited + 10))
  done
}
wait_for_apt_locks
sudo apt-get update
wait_for_apt_locks
sudo apt-get install -y python3.10-venv
if ! command -v cargo >/dev/null 2>&1; then
  curl https://sh.rustup.rs -sSf | sh -s -- -y
fi
export PATH=/home/ubuntu/.cargo/bin:$PATH
export CARGO_HTTP_MULTIPLEXING=false
cd /home/ubuntu/permeant-os
for attempt in 1 2 3; do
  if cargo build; then
    break
  fi
  if [[ "$attempt" == "3" ]]; then
    exit 1
  fi
  sleep "$((attempt * 10))"
done
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip setuptools wheel
pip install ninja
pip install vllm==0.23.0
python - <<'PY'
import vllm
print(vllm.__version__)
PY
REMOTE_SETUP

  cat > "$REMOTE_START_SCRIPT" <<REMOTE_START
#!/usr/bin/env bash
set -euo pipefail
mkdir -p /tmp/permeant-vllm-state /tmp/permeant-logs
pkill -f vllm_runtime_receiver.py || true
pkill -f 'permeant-cli daemon --addr 127.0.0.1:29099' || true
export PATH=/home/ubuntu/permeant-os/.venv/bin:/home/ubuntu/.cargo/bin:\$PATH
export VLLM_ENABLE_V1_MULTIPROCESSING=0
export PERMEANT_VLLM_CONSUMER_HOOK=/home/ubuntu/permeant-os/adapters/vllm_real_runtime_consumer.py:consume
export PERMEANT_VLLM_RUNTIME_TARGET=/home/ubuntu/permeant-os/adapters/vllm_real_runtime_target.py:get_runtime
export PERMEANT_VLLM_MODEL='$PERMEANT_MODEL'
export PERMEANT_VLLM_MAX_MODEL_LEN='$PERMEANT_VLLM_MAX_MODEL_LEN'
export PERMEANT_VLLM_CONTINUATION_PROMPT='PermeantOS continuation probe'
export PERMEANT_VLLM_CONTINUATION_PROMPT_FROM_SOURCE=1
export PERMEANT_VLLM_CONTINUATION_MAX_TOKENS='$PERMEANT_CONTINUATION_MAX_TOKENS'
export PERMEANT_VLLM_CAPTURE_BASELINE=1
export PERMEANT_SOURCE_CONTINUATION_FILE=/home/ubuntu/permeant-source-continuation.json
export PERMEANT_VLLM_RUNTIME_STATE_FILE=/tmp/permeant-vllm-runtime-state.json
export PERMEANT_VLLM_RUNTIME_PROBE_FILE=/tmp/permeant-vllm-runtime-probe.json
export PERMEANT_VLLM_REVERSE_EXPORT_FILE=/tmp/permeant-vllm-reverse-runtime-state.json
export PERMEANT_VLLM_SLOT_SAMPLE_LIMIT=4
nohup /home/ubuntu/permeant-os/.venv/bin/python /home/ubuntu/permeant-os/adapters/vllm_runtime_receiver.py --host 127.0.0.1 --port 29100 --state-dir /tmp/permeant-vllm-state >/tmp/permeant-logs/receiver.log 2>&1 &
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD='/home/ubuntu/permeant-os/.venv/bin/python /home/ubuntu/permeant-os/adapters/vllm_injector.py'
export PERMEANT_INJECTOR_HOOK=/home/ubuntu/permeant-os/adapters/vllm_hook_template.py:injector_hook
export PERMEANT_VLLM_RUNTIME_HOOK=/home/ubuntu/permeant-os/adapters/vllm_http_runtime_hook.py:runtime_hook
export PERMEANT_VLLM_RUNTIME_URL=http://127.0.0.1:29100
nohup /home/ubuntu/permeant-os/target/debug/permeant-cli daemon --addr 127.0.0.1:29099 >/tmp/permeant-logs/daemon.log 2>&1 &
if [[ '$PERMEANT_MIGRATION_TRANSPORT' == 'production-wss' ]]; then
  nohup /home/ubuntu/permeant-os/.venv/bin/python /home/ubuntu/permeant-os/adapters/production_transport_proxy.py server \
    --listen-host 0.0.0.0 \
    --listen-port '$PERMEANT_PRODUCTION_TRANSPORT_PORT' \
    --target-host 127.0.0.1 \
    --target-port 29099 \
    --certfile '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/server.crt' \
    --keyfile '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/server.key' \
    --cafile '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/ca.crt' \
    >/tmp/permeant-logs/production-transport-server.log 2>&1 &
fi
sleep 5
tail -40 /tmp/permeant-logs/receiver.log || true
tail -40 /tmp/permeant-logs/daemon.log || true
tail -40 /tmp/permeant-logs/production-transport-server.log || true
REMOTE_START

  chmod +x "$REMOTE_SETUP_SCRIPT" "$REMOTE_START_SCRIPT"
}

copy_repo_and_setup() {
  log "copying committed repository snapshot to target"
  ssh_target 'rm -rf /home/ubuntu/permeant-os /home/ubuntu/qatq && mkdir -p /home/ubuntu/permeant-os'
  git -C "$ROOT_DIR" archive --format=tar HEAD | ssh_target 'tar -xf - -C /home/ubuntu/permeant-os'
  if [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "qatq" ]]; then
    [[ -f "$PERMEANT_QATQ_STANDALONE_PATH/Cargo.toml" ]] || die "standalone QATQ crate missing at $PERMEANT_QATQ_STANDALONE_PATH"
    log "copying standalone QATQ crate snapshot to target"
    ssh_target 'mkdir -p /home/ubuntu/qatq'
    git -C "$PERMEANT_QATQ_STANDALONE_PATH" archive --format=tar HEAD | ssh_target 'tar -xf - -C /home/ubuntu/qatq'
  fi
  scp_to_target "$REMOTE_SETUP_SCRIPT" /home/ubuntu/permeant-remote-setup.sh
  log "running target setup"
  ssh_target 'bash /home/ubuntu/permeant-remote-setup.sh'
}

copy_agent_graph_package_to_target() {
  [[ "$PERMEANT_AGENT_ACTIVITY_RESUME" == "1" ]] || return 0
  [[ -n "$PERMEANT_AGENT_GRAPH_MANIFEST" ]] || die "PERMEANT_AGENT_ACTIVITY_RESUME=1 requires PERMEANT_AGENT_GRAPH_MANIFEST"
  local package_dir
  package_dir="$(cd "$(dirname "$PERMEANT_AGENT_GRAPH_MANIFEST")" && pwd)"
  [[ -f "$package_dir/manifest.json" && -f "$package_dir/graph.json" ]] || die "invalid Agent Memory Graph package: $package_dir"
  log "copying Agent Memory Graph package to target"
  tar -C "$package_dir" -cf - . | ssh_target "rm -rf '$TARGET_AGENT_GRAPH_PACKAGE' && mkdir -p '$TARGET_AGENT_GRAPH_PACKAGE' && tar -xf - -C '$TARGET_AGENT_GRAPH_PACKAGE'"
  json_set "$STATE_FILE" target_agent_graph_package "$TARGET_AGENT_GRAPH_PACKAGE"
}

copy_production_transport_certs_to_target() {
  production_transport_enabled || return 0
  [[ -d "$PRODUCTION_TRANSPORT_CERT_DIR" ]] || die "missing production transport cert dir: $PRODUCTION_TRANSPORT_CERT_DIR"
  log "copying ephemeral production transport mTLS certificates to target"
  ssh_target "rm -rf '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR' && mkdir -p '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR' && chmod 700 '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR'"
  scp_to_target "$PRODUCTION_TRANSPORT_CERT_DIR/ca.crt" "$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/ca.crt"
  scp_to_target "$PRODUCTION_TRANSPORT_CERT_DIR/server.crt" "$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/server.crt"
  scp_to_target "$PRODUCTION_TRANSPORT_CERT_DIR/server.key" "$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/server.key"
  ssh_target "chmod 600 '$TARGET_PRODUCTION_TRANSPORT_CERT_DIR/server.key'"
}

start_target() {
  [[ -f "$PERMEANT_SOURCE_CONTINUATION_FILE" ]] || die "missing source continuation file: $PERMEANT_SOURCE_CONTINUATION_FILE"
  scp_to_target "$PERMEANT_SOURCE_CONTINUATION_FILE" /home/ubuntu/permeant-source-continuation.json
  scp_to_target "$REMOTE_START_SCRIPT" /home/ubuntu/permeant-remote-start.sh
  log "starting receiver and daemon"
  ssh_target 'bash /home/ubuntu/permeant-remote-start.sh'
}

start_tunnel() {
  local ip
  ip="$(public_ip)"
  if production_transport_enabled; then
    [[ -d "$PRODUCTION_TRANSPORT_CERT_DIR" ]] || die "missing production transport cert dir: $PRODUCTION_TRANSPORT_CERT_DIR"
    log "opening production WSS/mTLS transport on localhost:$PERMEANT_LOCAL_TUNNEL_PORT -> $ip:$PERMEANT_PRODUCTION_TRANSPORT_PORT"
    python3 "$ROOT_DIR/adapters/production_transport_proxy.py" client \
      --listen-host 127.0.0.1 \
      --listen-port "$PERMEANT_LOCAL_TUNNEL_PORT" \
      --remote-host "$ip" \
      --remote-port "$PERMEANT_PRODUCTION_TRANSPORT_PORT" \
      --server-name permeant-target \
      --certfile "$PRODUCTION_TRANSPORT_CERT_DIR/client.crt" \
      --keyfile "$PRODUCTION_TRANSPORT_CERT_DIR/client.key" \
      --cafile "$PRODUCTION_TRANSPORT_CERT_DIR/ca.crt" \
      > "$RUN_DIR/production-transport-client.log" 2>&1 &
  else
    log "opening SSH tunnel on localhost:$PERMEANT_LOCAL_TUNNEL_PORT"
    ssh -N \
      -L "$PERMEANT_LOCAL_TUNNEL_PORT:127.0.0.1:29099" \
      -o ExitOnForwardFailure=yes \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
      -i "$PEM_FILE" \
      "ubuntu@$ip" &
  fi
  echo "$!" > "$TUNNEL_PID_FILE"
  sleep 3
  kill -0 "$(cat "$TUNNEL_PID_FILE")" 2>/dev/null || die "$PERMEANT_MIGRATION_TRANSPORT transport failed to start"
}

stop_tunnel() {
  if [[ -f "$TUNNEL_PID_FILE" ]]; then
    local pid
    pid="$(cat "$TUNNEL_PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
    fi
    rm -f "$TUNNEL_PID_FILE"
  fi
}

run_migration() {
  log "running migration"
  (
    cd "$ROOT_DIR"
    local quant_args=()
    if [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "fp8" ]]; then
      quant_args+=(--quant)
    elif [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "qatq" ]]; then
      quant_args+=(--transfer-codec qatq)
    elif [[ "$PERMEANT_TRANSFER_QUANTIZATION" != "none" ]]; then
      die "unsupported PERMEANT_TRANSFER_QUANTIZATION: $PERMEANT_TRANSFER_QUANTIZATION"
    fi
    export PERMEANT_EXTRACTOR_MODE=json_command
    export PERMEANT_EXTRACTOR_CMD="python3 $ROOT_DIR/adapters/mlx_extractor.py"
    export PERMEANT_EXTRACTOR_HOOK="$ROOT_DIR/adapters/mlx_http_cache_provider.py:get_live_cache"
    export PERMEANT_MLX_RUNTIME_URL="$PERMEANT_SOURCE_URL"
    export PERMEANT_MODEL_ARCHITECTURE="$PERMEANT_MODEL"
    export PERMEANT_MODEL_IDENTITY="$PERMEANT_MODEL"
    export PERMEANT_MODEL_LAYER_COUNT="${PERMEANT_MODEL_LAYER_COUNT:-}"
    export PERMEANT_MODEL_Q_HEADS="${PERMEANT_MODEL_Q_HEADS:-}"
    export PERMEANT_MODEL_KV_HEADS="${PERMEANT_MODEL_KV_HEADS:-}"
    export PERMEANT_MODEL_HEAD_DIM="${PERMEANT_MODEL_HEAD_DIM:-}"
    export PERMEANT_MODEL_HIDDEN_SIZE="${PERMEANT_MODEL_HIDDEN_SIZE:-}"
    export PERMEANT_MODEL_BLOCK_SIZE="${PERMEANT_MODEL_BLOCK_SIZE:-}"
    local migrate_cmd=(
      ./target/debug/permeant-cli
      sim-migrate
      --target-addr "127.0.0.1:$PERMEANT_LOCAL_TUNNEL_PORT"
      --seq-len "$PERMEANT_SEQ_LEN"
    )
    if (( ${#quant_args[@]} > 0 )); then
      migrate_cmd+=("${quant_args[@]}")
    fi
    if [[ -n "$PERMEANT_AGENT_GRAPH_MANIFEST" ]]; then
      migrate_cmd+=(--agent-graph-manifest "$PERMEANT_AGENT_GRAPH_MANIFEST")
    fi
    "${migrate_cmd[@]}" | tee "$RUN_DIR/migration.log"
  )
  local manifest
  manifest="$(sed -n 's/^Saved migration benchmark manifest: //p' "$RUN_DIR/migration.log" | tail -1)"
  [[ -n "$manifest" ]] || die "migration completed without reporting a manifest"
  json_set "$STATE_FILE" manifest "$manifest"
}

collect_artifacts() {
  log "collecting target artifacts"
  mkdir -p "$TARGET_LOG_DIR"
  scp_from_target /tmp/permeant-vllm-runtime-probe.json "$TARGET_PROBE_LOCAL" || true
  scp_from_target /tmp/permeant-vllm-reverse-runtime-state.json "$TARGET_REVERSE_RUNTIME_STATE_LOCAL" || true
  scp_from_target /tmp/permeant-logs/receiver.log "$TARGET_LOG_DIR/receiver.log" || true
  scp_from_target /tmp/permeant-logs/daemon.log "$TARGET_LOG_DIR/daemon.log" || true
  scp_from_target /tmp/permeant-logs/production-transport-server.log "$TARGET_LOG_DIR/production-transport-server.log" || true
}

analyze_artifacts() {
  local manifest
  manifest="$(json_get "$STATE_FILE" manifest)"
  [[ -n "$manifest" ]] || return 0
  [[ -f "$ROOT_DIR/$manifest" ]] || return 0
  [[ -f "$TARGET_PROBE_LOCAL" ]] || return 0
  log "analyzing fidelity"
  python3 "$ROOT_DIR/adapters/analyze_real_runtime_fidelity.py" \
    --manifest "$ROOT_DIR/$manifest" \
    --probe "$TARGET_PROBE_LOCAL" \
    --pretty | tee "$RUN_DIR/fidelity-analysis.json"
  if [[ -f "$PERMEANT_SOURCE_CONTINUATION_FILE" ]]; then
    python3 "$ROOT_DIR/scripts/analyze-fidelity-horizons.py" \
      --source "$PERMEANT_SOURCE_CONTINUATION_FILE" \
      --probe "$TARGET_PROBE_LOCAL" \
      --horizons "$PERMEANT_FIDELITY_HORIZONS" \
      --markdown-out "$RUN_DIR/fidelity-horizons.md" \
      --pretty | tee "$RUN_DIR/fidelity-horizons.json"
  else
    log "skipping fidelity horizon analysis; source continuation file not found: $PERMEANT_SOURCE_CONTINUATION_FILE"
  fi
  python3 - "$TARGET_PROBE_LOCAL" <<'PY' | tee "$RUN_DIR/slot-probe-summary.json"
import json, sys
from pathlib import Path
probe = json.loads(Path(sys.argv[1]).read_text())
reg = next(e for e in probe.get("events", []) if e.get("event") == "register_permeant_block")
summaries = reg.get("written_layer_summaries", [])
failures = []
max_key = 0.0
max_value = 0.0
for summary in summaries:
    slot_probe = summary.get("slot_probe") or {}
    if slot_probe.get("all_samples_match") is not True:
        failures.append({"layer_index": summary.get("layer_index"), "slot_probe": slot_probe})
    for sample in slot_probe.get("samples", []) or []:
        key_delta = sample.get("key_max_abs_diff", sample.get("key_delta"))
        value_delta = sample.get("value_max_abs_diff", sample.get("value_delta"))
        if key_delta is not None:
            max_key = max(max_key, abs(float(key_delta)))
        if value_delta is not None:
            max_value = max(max_value, abs(float(value_delta)))
print(json.dumps({
    "layers": len(summaries),
    "all_layers_slot_probe_match": not failures,
    "slot_probe_failure_count": len(failures),
    "max_key_abs_diff": max_key,
    "max_value_abs_diff": max_value,
    "first_failure": failures[0] if failures else None,
}, indent=2))
PY
}

enforce_qatq_live_compression_gate() {
  [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "qatq" ]] || return 0
  local manifest
  manifest="$(json_get "$STATE_FILE" manifest)"
  [[ -n "$manifest" ]] || die "QATQ live compression gate cannot run without a migration manifest"
  [[ -f "$ROOT_DIR/$manifest" ]] || die "QATQ live compression gate manifest not found: $ROOT_DIR/$manifest"
  log "enforcing QATQ live compression gate"
  python3 - "$ROOT_DIR/$manifest" "$RUN_DIR/qatq-live-compression-gate.json" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text())

raw = int(manifest.get("raw_f32le_baseline_bytes") or manifest.get("uncompressed_bytes") or 0)
transferred = int(manifest.get("transferred_bytes") or 0)
zstd_bytes = int(manifest.get("zstd_raw_f32le_bytes") or 0)
lz4_bytes = int(manifest.get("lz4_raw_f32le_bytes") or 0)
pass_through = int(manifest.get("qatq_pass_through_chunks") or 0)
compressed_chunks = int(manifest.get("qatq_compressed_chunks") or 0)
strategies = manifest.get("qatq_strategies") or {}

checks = {
    "migration_success": manifest.get("success") is True,
    "uses_qatq_exact": strategies.get("qatq-exact", 0) > 0,
    "no_qatq_pass_through": pass_through == 0,
    "qatq_lte_raw": transferred <= raw if raw else False,
    "qatq_lte_zstd": transferred <= zstd_bytes if zstd_bytes else False,
    "qatq_lte_lz4": transferred <= lz4_bytes if lz4_bytes else False,
}
passed = all(checks.values())
def ratio(value: int, denom: int) -> float | None:
    return (value / denom) if denom else None
report = {
    "schema_version": "permeantos-qatq-live-compression-gate-v0",
    "status": "pass" if passed else "fail",
    "manifest": str(manifest_path),
    "checks": checks,
    "raw_f32le_baseline_bytes": raw,
    "qatq_transferred_bytes": transferred,
    "zstd_raw_f32le_bytes": zstd_bytes,
    "lz4_raw_f32le_bytes": lz4_bytes,
    "qatq_ratio_vs_raw": ratio(transferred, raw),
    "zstd_ratio_vs_raw": ratio(zstd_bytes, raw),
    "lz4_ratio_vs_raw": ratio(lz4_bytes, raw),
    "qatq_compressed_chunks": compressed_chunks,
    "qatq_pass_through_chunks": pass_through,
    "qatq_strategies": strategies,
}
out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, indent=2, sort_keys=True))
if not passed:
    raise SystemExit("QATQ live compression gate failed")
PY
}

run_reverse_runtime_import() {
  [[ "$PERMEANT_REVERSE_RUNTIME_IMPORT" == "1" ]] || return 0
  log "exporting vLLM target decode boundary through reverse runtime API"
  ssh_target "curl -fsS -H 'Content-Type: application/json' --data '{}' http://127.0.0.1:29100/export_reverse_runtime_state" \
    | tee "$TARGET_REVERSE_RUNTIME_STATE_LOCAL"
  python3 - "$TARGET_REVERSE_RUNTIME_STATE_LOCAL" <<'PY'
import json, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
if payload.get("success") is not True:
    raise SystemExit(f"reverse runtime export API failed: {payload}")
state = payload.get("reverse_runtime_state")
if not isinstance(state, dict):
    raise SystemExit(f"reverse runtime export API did not return reverse_runtime_state: {payload}")
if state.get("status") != "target_runtime_state_exported":
    raise SystemExit(f"reverse runtime state has unexpected status: {state}")
if not state.get("generated_token_ids"):
    raise SystemExit(f"reverse runtime state contains no generated tokens: {state}")
print(json.dumps({
    "status": state.get("status"),
    "proof_hash": state.get("proof_hash"),
    "generated_token_count": state.get("generated_token_count"),
    "last_registered_hash": state.get("last_registered_hash"),
}, indent=2, sort_keys=True))
PY
  log "importing vLLM target decode boundary back into live MLX origin"
  curl -fsS \
    --max-time 900 \
    -H 'Content-Type: application/json' \
    --data-binary "@$TARGET_REVERSE_RUNTIME_STATE_LOCAL" \
    "$(source_reverse_import_url)" | tee "$ORIGIN_REVERSE_IMPORT_REPORT_LOCAL"
  json_set "$STATE_FILE" target_reverse_runtime_state_local "$TARGET_REVERSE_RUNTIME_STATE_LOCAL"
  json_set "$STATE_FILE" origin_reverse_import_report_local "$ORIGIN_REVERSE_IMPORT_REPORT_LOCAL"
  python3 - "$ORIGIN_REVERSE_IMPORT_REPORT_LOCAL" <<'PY'
import json, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text())
if report.get("status") != "reverse_runtime_imported" or report.get("reverse_runtime_imported") is not True:
    raise SystemExit(f"reverse runtime import did not continue: {report}")
continuation = report.get("origin_continuation") or {}
if not continuation.get("token_ids"):
    raise SystemExit(f"reverse runtime import produced no origin continuation tokens: {report}")
print(json.dumps({
    "status": report.get("status"),
    "reverse_runtime_imported": report.get("reverse_runtime_imported"),
    "target_proof_hash": report.get("target_proof_hash"),
    "origin_advanced_prompt_token_count": report.get("origin_advanced_prompt_token_count"),
    "origin_continuation_token_count": continuation.get("token_count"),
    "proof_hash": report.get("proof_hash"),
}, indent=2, sort_keys=True))
PY
}

run_agent_activity_resume() {
  [[ "$PERMEANT_AGENT_ACTIVITY_RESUME" == "1" ]] || return 0
  log "running Agent Memory Graph resume proof on target"
  local approve_arg=""
  if [[ "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH" == "1" ]]; then
    approve_arg="--approve-publish"
  fi
  ssh_target "cd /home/ubuntu/permeant-os && python3 examples/agent-memory-graph/local_agent.py resume --input '$TARGET_AGENT_GRAPH_PACKAGE' --workspace '$TARGET_AGENT_ACTIVITY_WORKSPACE' $approve_arg" \
    | tee "$RUN_DIR/agent-activity-resume.stdout.json"
  json_set "$STATE_FILE" target_agent_activity_workspace "$TARGET_AGENT_ACTIVITY_WORKSPACE"
  scp_from_target "$TARGET_AGENT_ACTIVITY_WORKSPACE/reports/resume/resume-report.json" "$TARGET_AGENT_ACTIVITY_REPORT_LOCAL"
  scp_from_target "$TARGET_AGENT_ACTIVITY_WORKSPACE/reports/resume/resumed-graph.json" "$TARGET_AGENT_ACTIVITY_GRAPH_LOCAL"
  json_set "$STATE_FILE" target_agent_activity_report_local "$TARGET_AGENT_ACTIVITY_REPORT_LOCAL"
  json_set "$STATE_FILE" target_agent_activity_graph_local "$TARGET_AGENT_ACTIVITY_GRAPH_LOCAL"
  if [[ "$PERMEANT_AGENT_ACTIVITY_APPROVE_PUBLISH" == "1" ]]; then
    scp_from_target "$TARGET_AGENT_ACTIVITY_WORKSPACE/reports/publish/announcement.md" "$TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL"
    json_set "$STATE_FILE" target_agent_activity_artifact_local "$TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL"
  fi
  python3 - "$TARGET_AGENT_ACTIVITY_REPORT_LOCAL" <<'PY'
import json, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text())
if report.get("status") != "continued" or report.get("activity_continued") is not True:
    raise SystemExit(f"agent activity resume did not continue: {report}")
print(json.dumps({
    "status": report.get("status"),
    "activity_continued": report.get("activity_continued"),
    "pre_resume_graph_hash": report.get("pre_resume_graph_hash"),
    "post_resume_graph_hash": report.get("post_resume_graph_hash"),
    "proof_hash": report.get("proof_hash"),
    "executed_tools": [entry.get("node_id") for entry in report.get("executed_tools", [])],
    "written_artifacts": report.get("written_artifacts", []),
}, indent=2, sort_keys=True))
PY
}

run_agent_activity_return_home() {
  [[ "$PERMEANT_AGENT_ACTIVITY_RETURN_HOME" == "1" ]] || return 0
  log "running origin return-home proof against AWS-updated Agent Memory Graph"
  local package_dir
  package_dir="$(cd "$(dirname "$PERMEANT_AGENT_GRAPH_MANIFEST")" && pwd)"
  local target_artifact_args=()
  if [[ -f "$TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL" ]]; then
    target_artifact_args=(--target-artifact "$TARGET_AGENT_ACTIVITY_ARTIFACT_LOCAL")
  fi
  python3 "$ROOT_DIR/examples/agent-memory-graph/local_agent.py" return-home \
    --original-package "$package_dir" \
    --target-resumed-graph "$TARGET_AGENT_ACTIVITY_GRAPH_LOCAL" \
    --target-resume-report "$TARGET_AGENT_ACTIVITY_REPORT_LOCAL" \
    "${target_artifact_args[@]}" \
    --workspace "$ORIGIN_ROUNDTRIP_WORKSPACE" \
    | tee "$RUN_DIR/origin-return-home.stdout.json"
  json_set "$STATE_FILE" origin_roundtrip_workspace "$ORIGIN_ROUNDTRIP_WORKSPACE"
  json_set "$STATE_FILE" origin_roundtrip_report_local "$ORIGIN_ROUNDTRIP_REPORT_LOCAL"
  json_set "$STATE_FILE" origin_roundtrip_graph_local "$ORIGIN_ROUNDTRIP_GRAPH_LOCAL"
  python3 - "$ORIGIN_ROUNDTRIP_REPORT_LOCAL" <<'PY'
import json, sys
from pathlib import Path
report = json.loads(Path(sys.argv[1]).read_text())
if report.get("status") != "round_trip_continued" or report.get("round_trip_continued") is not True:
    raise SystemExit(f"origin return-home proof did not continue: {report}")
print(json.dumps({
    "status": report.get("status"),
    "round_trip_continued": report.get("round_trip_continued"),
    "origin_pre_graph_hash": report.get("origin_pre_graph_hash"),
    "target_post_graph_hash": report.get("target_post_graph_hash"),
    "origin_post_graph_hash": report.get("origin_post_graph_hash"),
    "target_proof_hash": report.get("target_proof_hash"),
    "proof_hash": report.get("proof_hash"),
    "origin_written_artifacts": report.get("origin_written_artifacts", []),
}, indent=2, sort_keys=True))
PY
}

status_cmd() {
  load_state "${1:-$PERMEANT_STATE_DIR/latest/state.json}"
  local id sg ip state
  id="$(instance_id)"
  sg="$(security_group_id)"
  ip="$(public_ip)"
  state=""
  if [[ -n "$id" ]]; then
    state="$(aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$id" --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true)"
  fi
  cat <<STATUS
state_file: $STATE_FILE
run_id: $RUN_ID
instance_id: $id
instance_state: $state
security_group_id: $sg
public_ip: $ip
run_dir: $RUN_DIR
manifest: $(json_get "$STATE_FILE" manifest)
target_probe_local: $TARGET_PROBE_LOCAL
STATUS
}

cleanup_cmd() {
  load_state "${1:-$PERMEANT_STATE_DIR/latest/state.json}"
  log "cleanup starting for $RUN_ID"
  stop_tunnel
  local id sg key
  id="$(instance_id)"
  sg="$(security_group_id)"
  key="$KEY_NAME"
  if [[ -n "$id" ]]; then
    local current_state
    current_state="$(aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$id" --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true)"
    if [[ "$current_state" != "terminated" && "$current_state" != "" ]]; then
      log "terminating instance $id"
      aws ec2 terminate-instances --region "$AWS_REGION" --instance-ids "$id" >/dev/null || true
      aws ec2 wait instance-terminated --region "$AWS_REGION" --instance-ids "$id" || true
    fi
  fi
  if [[ -n "$sg" ]]; then
    log "deleting security group $sg"
    aws ec2 delete-security-group --region "$AWS_REGION" --group-id "$sg" 2>/dev/null || true
  fi
  if [[ -n "$key" ]]; then
    log "deleting key pair $key"
    aws ec2 delete-key-pair --region "$AWS_REGION" --key-name "$key" 2>/dev/null || true
  fi
  rm -f "$PEM_FILE"
  log "verifying cleanup"
  if [[ -n "$sg" ]]; then
    aws ec2 describe-security-groups --region "$AWS_REGION" --group-ids "$sg" >/dev/null 2>&1 && die "security group still exists: $sg" || true
  fi
  if [[ -n "$key" ]]; then
    aws ec2 describe-key-pairs --region "$AWS_REGION" --key-names "$key" >/dev/null 2>&1 && die "key pair still exists: $key" || true
  fi
  json_set "$STATE_FILE" cleanup_verified_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  log "cleanup complete"
}

run_cmd() {
  need aws
  need curl
  need git
  need python3
  need scp
  need ssh
  need ssh-keyscan
  [[ -x "$ROOT_DIR/target/debug/permeant-cli" ]] || die "missing local target/debug/permeant-cli; build locally before running"

  create_state
  rm -f "$PERMEANT_STATE_DIR/latest"
  ln -s "$RUN_DIR" "$PERMEANT_STATE_DIR/latest"
  log "state file: $STATE_FILE"
  refresh_source_continuation
  discover_network
  write_remote_scripts
  trap 'collect_artifacts || true; cleanup_cmd "$STATE_FILE" || true' EXIT
  provision
  generate_production_transport_certs
  copy_repo_and_setup
  copy_production_transport_certs_to_target
  copy_agent_graph_package_to_target
  start_target
  start_tunnel
  run_migration
  collect_artifacts
  analyze_artifacts
  enforce_qatq_live_compression_gate
  run_reverse_runtime_import
  run_agent_activity_resume
  run_agent_activity_return_home
  cleanup_cmd "$STATE_FILE"
  trap - EXIT
  log "run complete: $RUN_DIR"
}

case "$COMMAND" in
  preflight)
    apply_validation_profile_cache_spec
    preflight_cmd
    ;;
  run)
    apply_validation_profile_cache_spec
    run_cmd
    ;;
  status)
    need aws
    status_cmd "${2:-}"
    ;;
  cleanup)
    need aws
    cleanup_cmd "${2:-}"
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

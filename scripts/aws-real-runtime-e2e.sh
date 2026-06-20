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
  PERMEANT_MODEL                     default: Qwen/Qwen2.5-0.5B-Instruct
  PERMEANT_SEQ_LEN                   default: 2016
  PERMEANT_VLLM_MAX_MODEL_LEN        default: 2048
  PERMEANT_TRANSFER_QUANTIZATION     default: none
  PERMEANT_CONTINUATION_MAX_TOKENS   default: 16
  PERMEANT_FIDELITY_HORIZONS         default: 16,32,64,128
  PERMEANT_SOURCE_URL                default: http://127.0.0.1:29101
  PERMEANT_SOURCE_CONTINUATION_FILE  default: /tmp/permeant-source-continuation.json
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
PERMEANT_MODEL="${PERMEANT_MODEL:-Qwen/Qwen2.5-0.5B-Instruct}"
PERMEANT_SEQ_LEN="${PERMEANT_SEQ_LEN:-2016}"
PERMEANT_VLLM_MAX_MODEL_LEN="${PERMEANT_VLLM_MAX_MODEL_LEN:-2048}"
PERMEANT_TRANSFER_QUANTIZATION="${PERMEANT_TRANSFER_QUANTIZATION:-none}"
PERMEANT_CONTINUATION_MAX_TOKENS="${PERMEANT_CONTINUATION_MAX_TOKENS:-16}"
PERMEANT_FIDELITY_HORIZONS="${PERMEANT_FIDELITY_HORIZONS:-16,32,64,128}"
PERMEANT_SOURCE_URL="${PERMEANT_SOURCE_URL:-http://127.0.0.1:29101}"
PERMEANT_SOURCE_CONTINUATION_FILE="${PERMEANT_SOURCE_CONTINUATION_FILE:-/tmp/permeant-source-continuation.json}"
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
  "model": "$PERMEANT_MODEL",
  "seq_len": "$PERMEANT_SEQ_LEN",
  "vllm_max_model_len": "$PERMEANT_VLLM_MAX_MODEL_LEN",
  "transfer_quantization": "$PERMEANT_TRANSFER_QUANTIZATION",
  "continuation_max_tokens": "$PERMEANT_CONTINUATION_MAX_TOKENS",
  "fidelity_horizons": "$PERMEANT_FIDELITY_HORIZONS",
  "source_url": "$PERMEANT_SOURCE_URL",
  "source_continuation_file": "$PERMEANT_SOURCE_CONTINUATION_FILE",
  "local_tunnel_port": "$PERMEANT_LOCAL_TUNNEL_PORT",
  "run_dir": "$RUN_DIR",
  "key_name": "$KEY_NAME",
  "pem_file": "$PEM_FILE",
  "known_hosts_file": "$KNOWN_HOSTS_FILE",
  "target_probe_local": "$TARGET_PROBE_LOCAL"
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
  (( PERMEANT_SEQ_LEN > 0 )) || return 1
  (( PERMEANT_VLLM_MAX_MODEL_LEN > PERMEANT_SEQ_LEN )) || return 1
  (( PERMEANT_CONTINUATION_MAX_TOKENS > 0 )) || return 1
  (( PERMEANT_LOCAL_TUNNEL_PORT > 0 && PERMEANT_LOCAL_TUNNEL_PORT <= 65535 )) || return 1
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
    check_status pass "configuration:numeric" "sequence length, context window, continuation tokens, and tunnel port are valid" >> "$checks_file"
  else
    check_status fail "configuration:numeric" "invalid numeric configuration or vLLM max model length does not exceed migrated sequence length" >> "$checks_file"
  fi

  if [[ "$PERMEANT_TRANSFER_QUANTIZATION" == "none" || "$PERMEANT_TRANSFER_QUANTIZATION" == "fp8" ]]; then
    check_status pass "configuration:transfer_quantization" "$PERMEANT_TRANSFER_QUANTIZATION is supported by the current runner" >> "$checks_file"
  else
    check_status fail "configuration:transfer_quantization" "unsupported PERMEANT_TRANSFER_QUANTIZATION: $PERMEANT_TRANSFER_QUANTIZATION" >> "$checks_file"
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

write_remote_scripts() {
  REMOTE_SETUP_SCRIPT="$RUN_DIR/remote-setup.sh"
  REMOTE_START_SCRIPT="$RUN_DIR/remote-start.sh"

  cat > "$REMOTE_SETUP_SCRIPT" <<'REMOTE_SETUP'
#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update
sudo apt-get install -y python3.10-venv
if ! command -v cargo >/dev/null 2>&1; then
  curl https://sh.rustup.rs -sSf | sh -s -- -y
fi
export PATH=/home/ubuntu/.cargo/bin:$PATH
cd /home/ubuntu/permeant-os
cargo build
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
export PERMEANT_VLLM_SLOT_SAMPLE_LIMIT=4
nohup /home/ubuntu/permeant-os/.venv/bin/python /home/ubuntu/permeant-os/adapters/vllm_runtime_receiver.py --host 127.0.0.1 --port 29100 --state-dir /tmp/permeant-vllm-state >/tmp/permeant-logs/receiver.log 2>&1 &
export PERMEANT_INJECTOR_MODE=json_command
export PERMEANT_INJECTOR_CMD='/home/ubuntu/permeant-os/.venv/bin/python /home/ubuntu/permeant-os/adapters/vllm_injector.py'
export PERMEANT_INJECTOR_HOOK=/home/ubuntu/permeant-os/adapters/vllm_hook_template.py:injector_hook
export PERMEANT_VLLM_RUNTIME_HOOK=/home/ubuntu/permeant-os/adapters/vllm_http_runtime_hook.py:runtime_hook
export PERMEANT_VLLM_RUNTIME_URL=http://127.0.0.1:29100
nohup /home/ubuntu/permeant-os/target/debug/permeant-cli daemon --addr 127.0.0.1:29099 >/tmp/permeant-logs/daemon.log 2>&1 &
sleep 5
tail -40 /tmp/permeant-logs/receiver.log || true
tail -40 /tmp/permeant-logs/daemon.log || true
REMOTE_START

  chmod +x "$REMOTE_SETUP_SCRIPT" "$REMOTE_START_SCRIPT"
}

copy_repo_and_setup() {
  log "copying committed repository snapshot to target"
  ssh_target 'rm -rf /home/ubuntu/permeant-os && mkdir -p /home/ubuntu/permeant-os'
  git -C "$ROOT_DIR" archive --format=tar HEAD | ssh_target 'tar -xf - -C /home/ubuntu/permeant-os'
  scp_to_target "$REMOTE_SETUP_SCRIPT" /home/ubuntu/permeant-remote-setup.sh
  log "running target setup"
  ssh_target 'bash /home/ubuntu/permeant-remote-setup.sh'
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
  log "opening SSH tunnel on localhost:$PERMEANT_LOCAL_TUNNEL_PORT"
  ssh -N \
    -L "$PERMEANT_LOCAL_TUNNEL_PORT:127.0.0.1:29099" \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -i "$PEM_FILE" \
    "ubuntu@$ip" &
  echo "$!" > "$TUNNEL_PID_FILE"
  sleep 3
  kill -0 "$(cat "$TUNNEL_PID_FILE")" 2>/dev/null || die "SSH tunnel failed to start"
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
    elif [[ "$PERMEANT_TRANSFER_QUANTIZATION" != "none" ]]; then
      die "unsupported PERMEANT_TRANSFER_QUANTIZATION: $PERMEANT_TRANSFER_QUANTIZATION"
    fi
    export PERMEANT_EXTRACTOR_MODE=json_command
    export PERMEANT_EXTRACTOR_CMD="python3 $ROOT_DIR/adapters/mlx_extractor.py"
    export PERMEANT_EXTRACTOR_HOOK="$ROOT_DIR/adapters/mlx_http_cache_provider.py:get_live_cache"
    export PERMEANT_MLX_RUNTIME_URL="$PERMEANT_SOURCE_URL"
    export PERMEANT_MODEL_ARCHITECTURE="$PERMEANT_MODEL"
    export PERMEANT_MODEL_IDENTITY="$PERMEANT_MODEL"
    local migrate_cmd=(
      ./target/debug/permeant-cli
      sim-migrate
      --target-addr "127.0.0.1:$PERMEANT_LOCAL_TUNNEL_PORT"
      --seq-len "$PERMEANT_SEQ_LEN"
    )
    if (( ${#quant_args[@]} > 0 )); then
      migrate_cmd+=("${quant_args[@]}")
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
  scp_from_target /tmp/permeant-logs/receiver.log "$TARGET_LOG_DIR/receiver.log" || true
  scp_from_target /tmp/permeant-logs/daemon.log "$TARGET_LOG_DIR/daemon.log" || true
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
        if sample.get("key_max_abs_diff") is not None:
            max_key = max(max_key, float(sample["key_max_abs_diff"]))
        if sample.get("value_max_abs_diff") is not None:
            max_value = max(max_value, float(sample["value_max_abs_diff"]))
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
  discover_network
  write_remote_scripts
  provision
  trap 'collect_artifacts || true; cleanup_cmd "$STATE_FILE" || true' EXIT
  copy_repo_and_setup
  start_target
  start_tunnel
  run_migration
  collect_artifacts
  analyze_artifacts
  cleanup_cmd "$STATE_FILE"
  trap - EXIT
  log "run complete: $RUN_DIR"
}

case "$COMMAND" in
  preflight)
    preflight_cmd
    ;;
  run)
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

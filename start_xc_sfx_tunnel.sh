#!/usr/bin/env bash
set -euo pipefail

# Keep Dasheng's PPU service private on xc and expose it to the local
# audiobook process through a small SSH forward, mirroring the TTS setup.
remote_alias="${ALEXANDRIA_XC_SFX_SSH_ALIAS:-xc}"
remote_root="${ALEXANDRIA_XC_SFX_REMOTE_ROOT:-/mnt/workspace/xinchao.gou/Dasheng-AudioGen}"
remote_port="${ALEXANDRIA_XC_SFX_REMOTE_PORT:-8100}"
local_port="${ALEXANDRIA_XC_SFX_LOCAL_PORT:-18100}"
auto_start="${ALEXANDRIA_XC_SFX_AUTO_START:-1}"
background="${ALEXANDRIA_XC_SFX_BACKGROUND:-0}"
startup_timeout="${ALEXANDRIA_XC_SFX_STARTUP_TIMEOUT:-600}"
poll_seconds="${ALEXANDRIA_XC_SFX_POLL_SECONDS:-3}"
ssh_timeout="${ALEXANDRIA_XC_SFX_SSH_CONNECT_TIMEOUT:-15}"
remote_start_command="${ALEXANDRIA_XC_SFX_REMOTE_START_COMMAND:-./run_sfx_server.sh}"

die() {
  echo "error: $*" >&2
  exit 1
}

validate_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "invalid port: $value"
  (( 10#$value >= 1 && 10#$value <= 65535 )) || die "invalid port: $value"
}

validate_positive_integer() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "invalid integer: $value"
  (( value >= 1 )) || die "value must be positive: $value"
}

validate_port "$remote_port"
validate_port "$local_port"
validate_positive_integer "$startup_timeout"
validate_positive_integer "$poll_seconds"
validate_positive_integer "$ssh_timeout"

health_ok() {
  curl --noproxy '*' -fsS --max-time 5 \
    "http://127.0.0.1:${local_port}/healthz" 2>/dev/null \
    | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'
}

ssh_base=(
  ssh -T
  -o BatchMode=yes
  -o ConnectTimeout="$ssh_timeout"
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
)

remote_health_ok() {
  "${ssh_base[@]}" "$remote_alias" \
    "curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:${remote_port}/healthz" \
    2>/dev/null | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'
}

remote_start() {
  local root_quoted
  printf -v root_quoted '%q' "$remote_root"
  "${ssh_base[@]}" "$remote_alias" "cd -- ${root_quoted} && ${remote_start_command}"
}

wait_remote_health() {
  local started_at="$SECONDS"
  while ! remote_health_ok; do
    if (( SECONDS - started_at >= startup_timeout )); then
      die "remote Dasheng SFX service did not become healthy within ${startup_timeout}s"
    fi
    sleep "$poll_seconds"
  done
}

wait_local_health() {
  local started_at="$SECONDS"
  while ! health_ok; do
    if (( SECONDS - started_at >= startup_timeout )); then
      die "local Dasheng SFX tunnel did not become healthy within ${startup_timeout}s"
    fi
    sleep "$poll_seconds"
  done
}

if health_ok; then
  echo "Dasheng SFX: healthy local tunnel already exists"
  exit 0
fi

case "${auto_start,,}" in
  0|false|no|off)
    die "remote Dasheng SFX service is unavailable and auto-start is disabled"
    ;;
esac

if ! remote_health_ok; then
  echo "Dasheng SFX: starting remote service on $remote_alias"
  remote_start || die "could not start remote Dasheng SFX service"
  wait_remote_health
fi

ssh_args=(
  "${ssh_base[@]}"
  -N
  -L "127.0.0.1:${local_port}:127.0.0.1:${remote_port}"
)
case "${background,,}" in
  1|true|yes|on)
    ssh_args+=( -f "$remote_alias" )
    "${ssh_args[@]}" || die "could not create the Dasheng SFX SSH tunnel"
    wait_local_health
    echo "Dasheng SFX: local endpoint is healthy on 127.0.0.1:${local_port}"
    ;;
  *)
    echo "Dasheng SFX: keeping SSH tunnel in the foreground"
    ssh_args+=( "$remote_alias" )
    exec "${ssh_args[@]}"
    ;;
esac

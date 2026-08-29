#!/usr/bin/env bash
set -euo pipefail

# Idempotently ensure the xc TTS services and their local SSH tunnels.
remote_alias="${ALEXANDRIA_XC_TTS_SSH_ALIAS:-xc}"
remote_root="${ALEXANDRIA_XC_TTS_REMOTE_ROOT:-/mnt/workspace/xinchao.gou/TTS}"
remote_main_port="${ALEXANDRIA_XC_TTS_REMOTE_PORT:-8000}"
remote_gpu1_port="${ALEXANDRIA_XC_TTS_REMOTE_GPU1_PORT:-8001}"
local_port="${ALEXANDRIA_XC_TTS_LOCAL_PORT:-18000}"
gpu1_local_port="${ALEXANDRIA_XC_TTS_GPU1_LOCAL_PORT-18001}"
auto_start="${ALEXANDRIA_XC_TTS_AUTO_START:-1}"
background="${ALEXANDRIA_XC_TTS_BACKGROUND:-0}"
startup_timeout="${ALEXANDRIA_XC_TTS_STARTUP_TIMEOUT:-600}"
poll_seconds="${ALEXANDRIA_XC_TTS_POLL_SECONDS:-3}"
ssh_timeout="${ALEXANDRIA_XC_TTS_SSH_CONNECT_TIMEOUT:-15}"
remote_start_command="${ALEXANDRIA_XC_TTS_REMOTE_START_COMMAND:-./run_server.sh}"
remote_gpu1_start_command="${ALEXANDRIA_XC_TTS_REMOTE_GPU1_START_COMMAND:-./run_server_gpu1.sh}"

die() {
  echo "error: $*" >&2
  exit 1
}

validate_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "invalid port: $value"
  (( 10#$value >= 1 && 10#$value <= 65535 )) || die "invalid port: $value"
}

validate_seconds() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || die "invalid timeout value: $value"
  (( value >= 1 )) || die "timeout must be positive: $value"
}

validate_port "$remote_main_port"
validate_port "$local_port"
if [[ -n "$gpu1_local_port" ]]; then
  validate_port "$remote_gpu1_port"
  validate_port "$gpu1_local_port"
fi
validate_seconds "$startup_timeout"
validate_seconds "$poll_seconds"
validate_seconds "$ssh_timeout"

health_ok() {
  local port="$1"
  local response
  response="$(curl --noproxy '*' -fsS --max-time 5 \
    "http://127.0.0.1:${port}/health" 2>/dev/null)" || return 1
  grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' <<<"$response"
}

all_local_healthy() {
  health_ok "$local_port" || return 1
  if [[ -n "$gpu1_local_port" ]]; then
    health_ok "$gpu1_local_port" || return 1
  fi
}

port_is_listening() {
  local port="$1"
  ss -ltnH 2>/dev/null | awk -v needle=":${port}" '
    $4 == needle || (length($4) >= length(needle) &&
      substr($4, length($4) - length(needle) + 1) == needle) { found = 1 }
    END { exit(found ? 0 : 1) }
  '
}

ssh_base=(
  ssh -T
  -o BatchMode=yes
  -o ConnectTimeout="$ssh_timeout"
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
)
ssh_remote() {
  "${ssh_base[@]}" "$remote_alias" "$@"
}

remote_health_ok() {
  local port="$1"
  ssh_remote \
    "curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:${port}/health" \
    2>/dev/null | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'
}

remote_start() {
  local command="$1"
  local root_quoted
  printf -v root_quoted '%q' "$remote_root"
  echo "TTS: starting remote command on $remote_alias: $command"
  ssh_remote "cd -- ${root_quoted} && $command"
}

ensure_remote_started() {
  local port="$1"
  local command="$2"
  local label="$3"

  if remote_health_ok "$port"; then
    echo "TTS: remote $label service is healthy on $remote_alias:$port"
    return 0
  fi

  case "${auto_start,,}" in
    0|false|no|off)
      die "remote $label TTS service is unavailable and auto-start is disabled"
      ;;
  esac

  echo "TTS: remote $label service is down; starting it over SSH"
  remote_start "$command" || die "could not start remote $label TTS service"
}

wait_remote_health() {
  local port="$1"
  local label="$2"
  local started_at="$SECONDS"

  while ! remote_health_ok "$port"; do
    if (( SECONDS - started_at >= startup_timeout )); then
      die "remote $label TTS service did not become healthy within ${startup_timeout}s"
    fi
    sleep "$poll_seconds"
  done
  echo "TTS: remote $label service is healthy"
}

wait_local_health() {
  local started_at="$SECONDS"
  while ! all_local_healthy; do
    if (( SECONDS - started_at >= startup_timeout )); then
      die "local TTS tunnel did not become healthy within ${startup_timeout}s"
    fi
    sleep "$poll_seconds"
  done
  echo "TTS: local endpoints are healthy"
}

main_ready=0
gpu1_ready=0
if health_ok "$local_port"; then
  main_ready=1
fi
if [[ -n "$gpu1_local_port" ]] && health_ok "$gpu1_local_port"; then
  gpu1_ready=1
fi

if (( ! main_ready )); then
  ensure_remote_started "$remote_main_port" "$remote_start_command" "GPU0"
fi
if [[ -n "$gpu1_local_port" ]] && (( ! gpu1_ready )); then
  ensure_remote_started "$remote_gpu1_port" "$remote_gpu1_start_command" "GPU1"
fi

# Start both remote model servers before waiting, so their model loads overlap.
if (( ! main_ready )); then
  wait_remote_health "$remote_main_port" "GPU0"
fi
if [[ -n "$gpu1_local_port" ]] && (( ! gpu1_ready )); then
  wait_remote_health "$remote_gpu1_port" "GPU1"
fi

ssh_args=(
  "${ssh_base[@]}"
  -N
)
forward_count=0

if ! health_ok "$local_port"; then
  if port_is_listening "$local_port"; then
    die "local port $local_port is occupied but is not a healthy xc TTS endpoint"
  fi
  ssh_args+=( -L "127.0.0.1:${local_port}:127.0.0.1:${remote_main_port}" )
  forward_count=$((forward_count + 1))
fi

if [[ -n "$gpu1_local_port" ]] && ! health_ok "$gpu1_local_port"; then
  if port_is_listening "$gpu1_local_port"; then
    die "local port $gpu1_local_port is occupied but is not a healthy xc TTS endpoint"
  fi
  ssh_args+=( -L "127.0.0.1:${gpu1_local_port}:127.0.0.1:${remote_gpu1_port}" )
  forward_count=$((forward_count + 1))
fi

if (( forward_count == 0 )); then
  echo "TTS: healthy local tunnel already exists"
  exit 0
fi


case "$background" in
  1|true|yes|on)
    ssh_args+=( -f )
    ssh_args+=( "$remote_alias" )
    "${ssh_args[@]}" || die "could not create the xc TTS SSH tunnel"
    wait_local_health
    ;;
  *)
    echo "TTS: keeping SSH tunnel in the foreground"
    ssh_args+=( "$remote_alias" )
    exec "${ssh_args[@]}"
    ;;
esac

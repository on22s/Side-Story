#!/usr/bin/env bash
set -euo pipefail

# The xc TTS services listen on 127.0.0.1:8000/8001 on the remote host.
# Keep this process running while Alexandria renders audio.
local_port="${ALEXANDRIA_XC_TTS_LOCAL_PORT:-18000}"
# GPU1 forwarding is enabled by default; set the variable to an empty value
# to use only the cuda:0 endpoint.
gpu1_local_port="${ALEXANDRIA_XC_TTS_GPU1_LOCAL_PORT-18001}"
ssh_args=(
  -o ExitOnForwardFailure=yes
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -N
  -L "127.0.0.1:${local_port}:127.0.0.1:8000"
)
if [[ -n "$gpu1_local_port" ]]; then
  ssh_args+=( -L "127.0.0.1:${gpu1_local_port}:127.0.0.1:8001" )
fi
exec ssh "${ssh_args[@]}" xc

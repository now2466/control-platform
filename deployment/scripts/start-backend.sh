#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/../.." && pwd)"
backend_dir="${CONTROL_PLATFORM_BACKEND_DIR:-$root_dir/backend}"
python_bin="${CONTROL_PLATFORM_PYTHON:-$backend_dir/.venv/bin/python}"

if [[ ! -x "$python_bin" ]]; then
  printf 'backend Python not found: %s\nRun deployment/runbook.md dependency setup first.\n' "$python_bin" >&2
  exit 1
fi

mode="${CONTROL_PLATFORM_MODE:-mock}"
host="${CONTROL_PLATFORM_HOST:-127.0.0.1}"
port="${CONTROL_PLATFORM_PORT:-8081}"
origin="${CONTROL_PLATFORM_ALLOWED_ORIGIN:-http://localhost:5173}"
database="${CONTROL_PLATFORM_DATABASE:-${XDG_STATE_HOME:-$HOME/.local/state}/control-platform/control.db}"
secure="${CONTROL_PLATFORM_SECURE_COOKIES:-0}"
ros_config="${CONTROL_PLATFORM_ROS_CONFIG:-$root_dir/deployment/robots.ros.example.yaml}"

if [[ "$mode" != mock && "$mode" != ros ]]; then
  printf 'invalid CONTROL_PLATFORM_MODE=%s (expected mock or ros)\n' "$mode" >&2
  exit 2
fi
if [[ "$secure" != 0 && "$secure" != 1 ]]; then
  printf 'invalid CONTROL_PLATFORM_SECURE_COOKIES=%s (expected 0 or 1)\n' "$secure" >&2
  exit 2
fi

mkdir -p -- "$(dirname -- "$database")"
args=(
  -m pinky_control_center.main
  --mode "$mode"
  --host "$host"
  --port "$port"
  --allowed-origin "$origin"
  --database "$database"
)
if [[ "$secure" == 1 ]]; then
  args+=(--secure-cookies)
fi
if [[ "$mode" == ros ]]; then
  if [[ ! -f "$ros_config" ]]; then
    printf 'ROS config not found: %s\n' "$ros_config" >&2
    exit 4
  fi
  args+=(--config "$ros_config")
fi
exec "$python_bin" "${args[@]}"

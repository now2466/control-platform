#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/../.." && pwd)"
backend_python="${CONTROL_PLATFORM_PYTHON:-$root_dir/backend/.venv/bin/python}"

if [[ ! -x "$backend_python" ]]; then
  printf 'backend Python not found: %s\n' "$backend_python" >&2
  exit 1
fi

cd -- "$root_dir"
exec "$backend_python" -m pytest backend/tests/test_t14_acceptance.py -q

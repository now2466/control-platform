#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
env_file="${1:-$script_dir/../.env}"
exec python3 "$script_dir/validate-config.py" "$env_file"

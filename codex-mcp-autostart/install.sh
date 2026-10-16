#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { printf 'Missing dependency: python3\n' >&2; exit 1; }
exec python3 "$source_dir/install.py" "$@"

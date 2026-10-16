#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_dir="${GRAPHIFY_CODEX_HOME:-$HOME/.local/share/graphify-codex}"
command -v uv >/dev/null
mkdir -p "$install_dir"
UV_TOOL_DIR="$install_dir/tools" UV_TOOL_BIN_DIR="$install_dir/bin" \
  uv tool install --python 3.12 --with 'mcp==1.30.0' 'graphifyy[mcp,watch,sql]==0.9.91'
if [[ "$source_dir/launcher.py" != "$install_dir/launcher.py" ]]; then
  install -m 600 "$source_dir/launcher.py" "$install_dir/launcher.py"
fi
printf 'Installed adapter: %s/launcher.py\nPython: %s/tools/graphifyy/bin/python\n' "$install_dir" "$install_dir"

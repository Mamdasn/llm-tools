#!/usr/bin/env bash
# Shared entry point for Codex, a terminal, and systemd. Stdout in mcp mode
# belongs exclusively to JSON-RPC.
set -euo pipefail
runtime="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# != 2 || "$1" != graphiti ]]; then
  printf 'Usage: bash mcp.sh graphiti <start|status|mcp|serve>\n' >&2
  exit 2
fi
case "$2" in
  start) mode=(--ensure) ;;
  status) mode=(--check) ;;
  mcp) mode=() ;;
  serve) mode=(--supervise) ;;
  *) printf 'Unknown operation: %s\n' "$2" >&2; exit 2 ;;
esac
python="${GRAPHITI_MCP_PYTHON:-}"
if [[ -z "$python" && -f "$runtime/python-path" ]]; then
  IFS= read -r python < "$runtime/python-path"
fi
if [[ -z "$python" || ! -x "$python" ]]; then
  printf 'Graphiti runtime missing. Run the repository installer: bash install.sh graphiti\n' >&2
  exit 1
fi
if [[ "$2" == mcp ]]; then
  exec "$python" "$runtime/bridge.py" --settings "$runtime/settings.json"
fi
exec "$python" "$runtime/bridge.py" --settings "$runtime/settings.json" "${mode[@]}"

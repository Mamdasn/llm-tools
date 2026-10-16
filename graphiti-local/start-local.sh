#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
graphiti_root="${GRAPHITI_ROOT:-$HOME/local-memory/graphiti}"
config_path="${GRAPHITI_CONFIG:-$source_dir/config.example.yaml}"
database_container="${GRAPHITI_DB_CONTAINER:-graphiti-db}"
cd "$graphiti_root/mcp_server"

source "$source_dir/runtime.sh"
start_ollama
start_docker
docker start "$database_container" >&2
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL=http://localhost:11434/v1
export SEMAPHORE_LIMIT=1
exec .venv/bin/python main.py --config "$config_path" --transport http --host 127.0.0.1 --port 8765

#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
graphiti_root="${GRAPHITI_ROOT:-$HOME/local-memory/graphiti}"
config_path="${GRAPHITI_CONFIG:-$source_dir/config.example.yaml}"
database_container="${GRAPHITI_DB_CONTAINER:-graphiti-db}"
cd "$graphiti_root/mcp_server"

# The existing macOS deployment uses Ollama.app and Colima.
if [[ "$(uname -s)" == Darwin ]]; then
  open -a Ollama
fi
if ! docker info >/dev/null 2>&1; then
  colima start --cpu 4 --memory 4
fi
docker start "$database_container"
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL=http://localhost:11434/v1
export SMALL_MODEL_NAME=qwen3.5:9b
export SEMAPHORE_LIMIT=1
exec uv run --python 3.12 main.py --config "$config_path" --transport http

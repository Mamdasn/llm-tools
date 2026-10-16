#!/usr/bin/env bash
# Reusable runtime checks. No package installation or model downloads here.
start_ollama() {
  export OLLAMA_HOST=127.0.0.1:11434
  if ollama list >/dev/null 2>&1; then return; fi
  local log_dir="${XDG_STATE_HOME:-$HOME/.local/state}/llm-tools"
  mkdir -p "$log_dir"
  chmod 700 "$log_dir"
  (umask 077; nohup ollama serve >> "$log_dir/ollama.log" 2>&1 < /dev/null &)
  local attempt
  for attempt in {1..60}; do
    if ollama list >/dev/null 2>&1; then return; fi
    sleep 1
  done
  printf 'Ollama did not become ready; inspect %s/ollama.log\n' "$log_dir" >&2
  return 1
}

start_docker() {
  if docker info >/dev/null 2>&1; then return; fi
  if [[ "$(uname -s)" == Darwin ]] && command -v colima >/dev/null; then
    colima start --cpu 4 --memory 4 >&2
  elif [[ "$(uname -s)" == Linux ]] && command -v systemctl >/dev/null; then
    systemctl --user start docker.service || true
  fi
  if ! docker info >/dev/null 2>&1; then
    printf 'Docker is unavailable. Start your Docker daemon and check user access with docker info.\n' >&2
    return 1
  fi
}

#!/usr/bin/env bash
# Sourced by install.sh. Installation is explicit; normal MCP startup never
# downloads packages or models.

die() { printf '%s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

download() {
  curl --fail --show-error --location --proto '=https' --proto-redir '=https' --retry 3 "$1" -o "$2"
}

official_installer() (
  set -e
  installer_tmp="$(mktemp -d)"
  trap 'rm -rf "$installer_tmp"' EXIT
  download "$1" "$installer_tmp/install.sh"
  shift
  "$@" "$installer_tmp/install.sh"
)

ensure_brew() {
  if ! have brew; then
    official_installer https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh /bin/bash
    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
  fi
  have brew || die 'Homebrew installation did not complete.'
}

linux_packages() {
  if have apt-get; then
    sudo apt-get update
    sudo apt-get install -y "$@"
  elif have dnf; then
    sudo dnf install -y "$@"
  else
    die "Automatic package installation supports apt-get and dnf. Install these packages and rerun: $*"
  fi
}

ensure_base() {
  [[ "$(id -u)" != 0 ]] || die 'Run as your normal user, not sudo. Individual system packages may request sudo.'
  export PATH="$HOME/.local/bin:$HOME/bin:$PATH"
  case "$(uname -s)" in
    Darwin)
      export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"
      for dependency in curl git python3; do
        if ! have "$dependency"; then ensure_brew; brew install "$dependency"; fi
      done ;;
    Linux)
      for dependency in curl git python3; do
        if ! have "$dependency"; then linux_packages "$dependency"; fi
      done ;;
    *) die 'Supported platforms: macOS and Linux' ;;
  esac
}

ensure_uv() {
  if ! have uv; then
    UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 \
      official_installer https://astral.sh/uv/install.sh sh
  fi
  have uv || die 'uv installation did not complete.'
  uv python install 3.12
}

ensure_node() {
  if have node && have npm && node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22 || a===22 && b>=5 ? 0 : 1)'; then
    return
  fi
  # An isolated official Node distribution avoids replacing the user's Node.
  node_dir="${LLM_TOOLS_NODE_HOME:-$HOME/.local/share/llm-tools/node}"
  if [[ -x "$node_dir/bin/node" && -x "$node_dir/bin/npm" ]] && \
    "$node_dir/bin/node" -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22 || a===22 && b>=5 ? 0 : 1)'; then
    export PATH="$node_dir/bin:$PATH"
    return
  fi
  python3 "$source_dir/scripts/install-node.py" "$node_dir"
  export PATH="$node_dir/bin:$PATH"
}

ensure_context_mode() (
  set -e
  [[ ! -e "$context_dir" ]] || exit 0
  mkdir -p "$(dirname -- "$context_dir")"
  context_tmp="$(mktemp -d "$(dirname -- "$context_dir")/.context-mode.XXXXXX")"
  trap 'rm -rf "$context_tmp"' EXIT
  # npm verifies registry integrity. Install into staging and publish only once
  # native dependencies are ready; leave an existing package entirely alone.
  npm pack context-mode@1.0.169 --ignore-scripts --silent --pack-destination "$context_tmp"
  mkdir "$context_tmp/package"
  tar -xzf "$context_tmp/context-mode-1.0.169.tgz" -C "$context_tmp/package" --strip-components=1
  npm install --prefix "$context_tmp/package" --omit=dev --ignore-scripts --no-audit --no-fund
  # npm 12 requires explicit approval even for a named rebuild. Approve only
  # this installed version in our new staging package, never global policy.
  python3 - "$context_tmp/package" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
path = root / 'package.json'
package = json.loads(path.read_text())
version = json.loads((root / 'node_modules/better-sqlite3/package.json').read_text())['version']
package['allowScripts'] = {'better-sqlite3@' + version: True}
path.write_text(json.dumps(package, indent=2) + '\n')
PY
  if ! npm rebuild --prefix "$context_tmp/package" better-sqlite3; then
    if [[ "$(uname -s)" == Linux ]]; then
      if have apt-get; then linux_packages build-essential; else linux_packages gcc-c++ make; fi
    else
      xcode-select -p >/dev/null 2>&1 || die 'Install Apple Command Line Tools with xcode-select --install, then rerun.'
    fi
    npm rebuild --prefix "$context_tmp/package" better-sqlite3
  fi
  check_sqlite "$context_tmp/package"
  mv "$context_tmp/package" "$context_dir"
)

check_sqlite() {
  node -e 'const D=require(require("node:path").resolve(process.argv[1],"node_modules/better-sqlite3")); const db=new D(":memory:"); db.prepare("select 1").get(); db.close()' "$1"
}

ensure_ollama() {
  if ! have ollama && [[ -x /Applications/Ollama.app/Contents/Resources/ollama ]]; then
    export PATH="$PATH:/Applications/Ollama.app/Contents/Resources"
  fi
  if ! have ollama; then
    if [[ "$(uname -s)" == Darwin ]]; then
      ensure_brew; brew install ollama
    else
      official_installer https://ollama.com/install.sh sh
    fi
  fi
}

ensure_docker() {
  if [[ "$(uname -s)" == Darwin ]]; then
    if ! have docker; then ensure_brew; brew install docker; fi
    if ! docker info >/dev/null 2>&1 && ! have colima; then
      ensure_brew; brew install colima
    fi
  elif ! have docker; then
    # Docker's rootless installer creates its user service and CLI context.
    # Do not grant membership in the root-equivalent docker group.
    if ! have newuidmap || ! have newgidmap; then
      if have apt-get; then linux_packages uidmap dbus-user-session; else linux_packages shadow-utils slirp4netns; fi
    fi
    official_installer https://get.docker.com/rootless sh
    export PATH="$HOME/bin:$PATH"
  fi
  have docker || die 'Docker installation did not complete.'
}

ensure_graphiti_checkout() (
  set -e
  if [[ ! -e "$graphiti_root" ]]; then
    mkdir -p "$(dirname -- "$graphiti_root")"
    checkout_tmp="$(mktemp -d "$(dirname -- "$graphiti_root")/.graphiti.XXXXXX")"
    trap 'rm -rf "$checkout_tmp"' EXIT
    git clone --no-checkout https://github.com/getzep/graphiti.git "$checkout_tmp/repo"
    git -C "$checkout_tmp/repo" checkout --detach "${GRAPHITI_REVISION:-dd3fd6ca7671c90b299fe8e8867a9f8439eafbeb}"
    mv "$checkout_tmp/repo" "$graphiti_root"
  fi
  [[ -f "$graphiti_root/mcp_server/main.py" ]] || die "GRAPHITI_ROOT is not a Graphiti checkout: $graphiti_root"
  cd "$graphiti_root/mcp_server"
  uv sync --python 3.12 --locked
)

provision_graphiti_data() {
  # These helpers are also used by start-local.sh, but model/container creation
  # belongs exclusively to this installer.
  source "$source_dir/graphiti-local/runtime.sh"
  start_ollama
  start_docker
  database_container="${GRAPHITI_DB_CONTAINER:-graphiti-db}"
  if ! docker container inspect "$database_container" >/dev/null 2>&1; then
    docker run -d --name "$database_container" --restart unless-stopped \
      -p 127.0.0.1:6379:6379 -v "${GRAPHITI_DB_VOLUME:-graphiti-memory}:/data" \
      "${FALKORDB_IMAGE:-falkordb/falkordb:v4.22.1}"
  else
    docker start "$database_container" >/dev/null
  fi
  models_file="$(mktemp)"
  # Read the user's preserved configuration, not hardcoded replacement models.
  if ! "$graphiti_root/mcp_server/.venv/bin/python" - "${GRAPHITI_CONFIG:-$graphiti_dir/config.example.yaml}" > "$models_file" <<'PY'
import sys, yaml
with open(sys.argv[1]) as source:
    config = yaml.safe_load(source)
models = [config['llm']['model'], config['llm'].get('small_model'), config['embedder']['model']]
for model in dict.fromkeys(model for model in models if model):
    if not isinstance(model, str) or not model.strip() or '\n' in model or model.startswith('-'):
        raise ValueError('Invalid Ollama model in Graphiti configuration')
    print(model)
PY
  then rm -f "$models_file"; die 'Could not read models from Graphiti configuration.'; fi
  while IFS= read -r model; do
    if ! ollama show "$model" >/dev/null 2>&1; then
      if ! ollama pull "$model"; then rm -f "$models_file"; die "Model download failed: $model. Rerun to resume."; fi
    fi
  done < "$models_file"
  rm -f "$models_file"
}

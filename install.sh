#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
target="${1:---help}"
if [[ $# -gt 1 ]]; then
  printf 'Expected one target. Run: bash install.sh --help\n' >&2
  exit 1
fi
case "$target" in
  -h|--help)
    cat <<'HELP'
Usage: bash install.sh <graphify|context-mode|graphiti|autostart|playwright|all>

graphify      Install uv, Python, and the pinned Graphify runtime and adapter.
context-mode  Install Node, Context Mode 1.0.169, and the Codex overlay.
graphiti      Install Graphiti, Ollama, models, FalkorDB, and the startup bridge.
autostart     Alias for graphiti; includes the canonical Bash entry point.
playwright    Install Playwright CLI and its global Codex skill.
all           Install all four integrations and their dependencies.

Run as your normal user on macOS or Linux (apt/dnf for missing OS packages).
Downloads missing prerequisites; system packages may require sudo.
MCP targets write codex.toml snippets; Playwright installs a skill without an MCP server.
Does not edit your global Codex configuration.

Optional environment variables:
  GRAPHIFY_CODEX_HOME  Adapter destination (default: ~/.local/share/graphify-codex)
  CONTEXT_MODE_ROOT    Existing package (default: ~/.local/share/codex-context-mode/plugins/context-mode)
  GRAPHITI_ROOT       Existing checkout (default: ~/local-memory/graphiti)
  GRAPHITI_LOCAL_HOME  Launcher destination (default: ~/.local/share/graphiti-local)
  CODEX_HOME          Codex directory for Playwright skills (default: ~/.codex)
  CODEX_MCP_AUTOSTART_HOME  Autostart destination (default: ~/.local/share/codex-mcp-autostart)
  GRAPHITI_MCP_PYTHON   Existing Graphiti Python runtime (default: $GRAPHITI_ROOT/mcp_server/.venv/bin/python)
  GRAPHITI_START_SCRIPT  Existing launcher (default: $GRAPHITI_LOCAL_HOME/start-local.sh)

Graphiti downloads qwen3.5:9b and nomic-embed-text for new configurations.
Existing configurations and models are reused. Linux user units are generated;
macOS Codex invokes the same mcp.sh script. See codex-mcp-autostart/README.md.
HELP
    exit 0
    ;;
  graphify|context-mode|graphiti|autostart|playwright|all) ;;
  *) printf 'Unknown target: %s. Run: bash install.sh --help\n' "$target" >&2; exit 1 ;;
esac

source "$source_dir/scripts/dependencies.sh"
ensure_base
graphify_dir="${GRAPHIFY_CODEX_HOME:-$HOME/.local/share/graphify-codex}"
context_dir="${CONTEXT_MODE_ROOT:-$HOME/.local/share/codex-context-mode/plugins/context-mode}"
graphiti_root="${GRAPHITI_ROOT:-$HOME/local-memory/graphiti}"
graphiti_dir="${GRAPHITI_LOCAL_HOME:-$HOME/.local/share/graphiti-local}"

if [[ "$target" == autostart ]]; then target=graphiti; fi

# Provision only dependencies needed by the selected target.
if [[ "$target" == graphify || "$target" == graphiti || "$target" == all ]]; then
  ensure_uv
fi
if [[ "$target" == playwright || "$target" == all ]]; then
  ensure_node
fi
if [[ "$target" == context-mode || "$target" == all ]]; then
  ensure_node
  ensure_context_mode
  python3 - "$context_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
required = ["package.json", "server.bundle.mjs"] + [
    f"hooks/codex/{name}.mjs"
    for name in ["pretooluse", "posttooluse", "sessionstart", "precompact", "userpromptsubmit", "stop"]
]
if not all((root / name).is_file() for name in required):
    sys.exit("Set CONTEXT_MODE_ROOT to an installed Context Mode package with Codex hooks.")
if json.loads((root / "package.json").read_text())["version"] != "1.0.169":
    sys.exit("This overlay requires Context Mode 1.0.169; review compatibility before using another version.")
PY
  check_sqlite "$context_dir"
fi
if [[ "$target" == graphiti || "$target" == all ]]; then
  ensure_ollama
  ensure_docker
  ensure_graphiti_checkout
fi

if [[ "$target" == graphify || "$target" == all ]]; then
  GRAPHIFY_CODEX_HOME="$graphify_dir" bash "$source_dir/graphify-codex/install.sh"
  python3 - "$graphify_dir" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
config = '[mcp_servers.graphify]\ncommand = ' + json.dumps(str(root / "tools/graphifyy/bin/python"))
config += '\nargs = [' + json.dumps(str(root / "launcher.py")) + ']\nstartup_timeout_sec = 60.0\n'
(root / "codex.toml").write_text(config)
print(f"Codex configuration: {root / 'codex.toml'}")
PY
fi

if [[ "$target" == context-mode || "$target" == all ]]; then
  if [[ -e "$context_dir/.codex-plugin" ]]; then
    backup="$context_dir/.codex-plugin.backup.$(date +%Y%m%d%H%M%S).$$"
    cp -R "$context_dir/.codex-plugin" "$backup"
    printf 'Overlay backup: %s\n' "$backup"
  fi
  mkdir -p "$context_dir/.codex-plugin"
  cp "$source_dir/context-mode-codex/.codex-plugin/"* "$context_dir/.codex-plugin/"
  python3 - "$context_dir" "$(command -v node)" <<'PY'
import json
import shlex
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
node = str(Path(sys.argv[2]).absolute())
overlay = root / ".codex-plugin"
hooks = json.loads((overlay / "hooks.json").read_text())
for entries in hooks["hooks"].values():
    for entry in entries:
        for hook in entry["hooks"]:
            hook["command"] = hook["command"].replace('"node"', shlex.quote(node), 1)
(overlay / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n")
mcp = json.loads((overlay / "mcp.json").read_text())
mcp["mcpServers"]["context-mode"]["command"] = node
(overlay / "mcp.json").write_text(json.dumps(mcp, indent=2) + "\n")
config = '[mcp_servers.context-mode]\ncommand = ' + json.dumps(node)
config += '\nargs = ' + json.dumps([str(overlay / "run.mjs"), "server"]) + '\n'
(overlay / "codex.toml").write_text(config)
print(f"Codex configuration: {overlay / 'codex.toml'}")
print("Register the package as a Codex plugin for hooks and skills, OR use the standalone MCP snippet.")
PY
fi

if [[ "$target" == graphiti || "$target" == all ]]; then
  mkdir -p "$graphiti_dir"
  install -m 755 "$source_dir/graphiti-local/start-local.sh" "$graphiti_dir/start-local.sh"
  install -m 644 "$source_dir/graphiti-local/runtime.sh" "$graphiti_dir/runtime.sh"
  # Keep an existing user's configuration on repeated installs.
  if [[ ! -e "$graphiti_dir/config.example.yaml" ]]; then
    install -m 600 "$source_dir/graphiti-local/config.example.yaml" "$graphiti_dir/config.example.yaml"
  fi
  provision_graphiti_data
  GRAPHITI_ROOT="$graphiti_root" GRAPHITI_LOCAL_HOME="$graphiti_dir" \
    bash "$source_dir/codex-mcp-autostart/install.sh"
fi
if [[ "$target" == playwright || "$target" == all ]]; then
  bash "$source_dir/playwright-cli/install.sh"
fi
if [[ "$target" != playwright ]]; then
  printf '\nMerge the selected snippets into ~/.codex/config.toml, then reload Codex.\n'
fi

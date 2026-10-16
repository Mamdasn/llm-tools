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
Usage: bash install.sh <graphify|context-mode|graphiti|all>

graphify      Install the code-only adapter and pinned Python runtime (requires uv).
context-mode  Apply the Codex overlay to an existing Context Mode 1.0.169 package.
graphiti      Install local configuration and launcher for an existing Graphiti checkout.
all           Install all three integrations after checking their prerequisites.

Requires Bash, Python 3 and Git. Context Mode also requires Node 22.5+.
Writes codex.toml snippets; does not edit your global Codex configuration.

Optional environment variables:
  GRAPHIFY_CODEX_HOME  Adapter destination (default: ~/.local/share/graphify-codex)
  CONTEXT_MODE_ROOT    Existing package (default: ~/.local/share/codex-context-mode/plugins/context-mode)
  GRAPHITI_ROOT       Existing checkout (default: ~/local-memory/graphiti)
  GRAPHITI_LOCAL_HOME  Launcher destination (default: ~/.local/share/graphiti-local)
HELP
    exit 0
    ;;
  graphify|context-mode|graphiti|all) ;;
  *) printf 'Unknown target: %s. Run: bash install.sh --help\n' "$target" >&2; exit 1 ;;
esac

for dependency in python3 git; do
  command -v "$dependency" >/dev/null || { printf 'Missing dependency: %s\n' "$dependency" >&2; exit 1; }
done
graphify_dir="${GRAPHIFY_CODEX_HOME:-$HOME/.local/share/graphify-codex}"
context_dir="${CONTEXT_MODE_ROOT:-$HOME/.local/share/codex-context-mode/plugins/context-mode}"
graphiti_root="${GRAPHITI_ROOT:-$HOME/local-memory/graphiti}"
graphiti_dir="${GRAPHITI_LOCAL_HOME:-$HOME/.local/share/graphiti-local}"

# Check every selected target before installing any of them.
if [[ "$target" == graphify || "$target" == all ]]; then
  command -v uv >/dev/null || { printf 'Install uv first: https://docs.astral.sh/uv/\n' >&2; exit 1; }
fi
if [[ "$target" == context-mode || "$target" == all ]]; then
  command -v node >/dev/null || { printf 'Context Mode requires Node 22.5+.\n' >&2; exit 1; }
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 5)) process.exit(1);' || { printf 'Context Mode requires Node 22.5+.\n' >&2; exit 1; }
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
fi
if [[ "$target" == graphiti || "$target" == all ]]; then
  [[ -f "$graphiti_root/mcp_server/main.py" ]] || { printf 'Set GRAPHITI_ROOT to an existing Graphiti checkout.\n' >&2; exit 1; }
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
  install -m 644 "$source_dir/graphiti-local/codex.example.toml" "$graphiti_dir/codex.toml"
  # Keep an existing user's configuration on repeated installs.
  if [[ ! -e "$graphiti_dir/config.example.yaml" ]]; then
    install -m 600 "$source_dir/graphiti-local/config.example.yaml" "$graphiti_dir/config.example.yaml"
  fi
  printf 'Graphiti launcher: %s/start-local.sh\nCodex configuration: %s/codex.toml\n' "$graphiti_dir" "$graphiti_dir"
  printf 'Keep GRAPHITI_ROOT set when starting the launcher if using a custom checkout.\n'
fi
printf '\nMerge the selected snippets into ~/.codex/config.toml, then reload Codex.\n'

# MCP tools for Codex

Install local code navigation, searchable context, and persistent memory on macOS
or Linux. The installer downloads missing dependencies for the selected target.

```bash
git clone https://github.com/Mamdasn/llm-tools.git
cd llm-tools
bash install.sh all           # or graphify, context-mode, graphiti
```

Run as your normal user. System packages may request sudo; do not run the entire
installer with sudo. Linux package provisioning supports apt and dnf. macOS uses
Homebrew, installing it through its official installer when needed. An internet
connection and enough disk space for models, Python packages, and container images
are required. The first install can take several minutes.

| Target | Downloads / installs when needed |
| --- | --- |
| `graphify` | uv, Python 3.12, Graphify 0.9.91, MCP SDK 1.30.0, the code-only adapter |
| `context-mode` | Node 24 if Node 22.5+ is unavailable, Context Mode 1.0.169, native SQLite dependency, Codex overlay |
| `graphiti` | uv, Python 3.12, Graphiti checkout and locked dependencies, Ollama, **qwen3.5:9b**, **nomic-embed-text**, Docker, FalkorDB, startup bridge |
| `autostart` | Alias for `graphiti` |
| `all` | All of the above |

The installer prints `codex.toml` snippet paths. Merge the selected entries into
`~/.codex/config.toml`, then reload Codex. It does not edit your global config.
Existing Graphiti configuration, containers, volumes, and downloaded models are
reused. Missing models are pulled from the preserved YAML configuration, so a
custom model is not silently replaced with the default. Download failures stop
installation with a nonzero exit; rerun to resume. Concurrent installer runs are
not supported.

## Graphiti startup

One canonical Bash entry point is used by both Codex and Linux systemd:

```bash
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti start
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti status
```

On macOS, the generated Codex entry invokes `mcp.sh graphiti mcp`. It starts or
reuses Graphiti, waits for readiness, then bridges stdio MCP to HTTP. This runs
when Codex initializes that MCP connection, not merely when an idle app window
opens. No Swift app watcher or LaunchAgent is needed.

On Linux, the installer also writes user units:

```bash
systemctl --user daemon-reload
systemctl --user enable --now codex-mcp.target
systemctl --user status codex-graphiti.service
```

Use `systemctl --user start codex-mcp.target` for a one-time start without enabling
login startup. The target starts `codex-graphiti.service`, which invokes the same
Bash script. Graphify and Context Mode remain per-client stdio servers; Graphify
needs a repository context. Remote MCPs still require their own authentication.
See the [startup guide](codex-mcp-autostart/README.md) for configuration and removal.

Graphiti uses `http://127.0.0.1:8765/mcp/`, Ollama uses port 11434, and new FalkorDB
containers bind **127.0.0.1:6379** with a persistent `graphiti-memory` volume.
macOS installs Colima when no Docker engine is available. On Linux a missing
Docker installation is provisioned using Docker's rootless installer. A working
user systemd session and subordinate UID/GID ranges are required by that installer;
it reports prerequisite failures. An existing Docker installation is reused, and
must be accessible without sudo. The installer does not change group memberships
or replace existing Docker contexts/containers. Runtime startup never downloads
packages or models.

## Configuration

Run `bash install.sh --help` for target usage. Set variables before installation:

| Variable | Default / purpose |
| --- | --- |
| `GRAPHIFY_CODEX_HOME` | `~/.local/share/graphify-codex` |
| `CONTEXT_MODE_ROOT` | `~/.local/share/codex-context-mode/plugins/context-mode`; existing package or fresh destination |
| `LLM_TOOLS_NODE_HOME` | `~/.local/share/llm-tools/node`; isolated Node fallback |
| `GRAPHITI_ROOT` | `~/local-memory/graphiti`; existing checkout or fresh destination |
| `GRAPHITI_REVISION` | `dd3fd6ca7671c90b299fe8e8867a9f8439eafbeb`; only used for new checkouts |
| `GRAPHITI_LOCAL_HOME` | `~/.local/share/graphiti-local`; launcher and preserved YAML |
| `GRAPHITI_CONFIG` | `$GRAPHITI_LOCAL_HOME/config.example.yaml`; use existing custom YAML |
| `GRAPHITI_DB_CONTAINER` / `GRAPHITI_DB_VOLUME` | `graphiti-db` / `graphiti-memory`; volume used only for container creation |
| `FALKORDB_IMAGE` | `falkordb/falkordb:v4.22.1`; only used for new containers |
| `CODEX_MCP_AUTOSTART_HOME` | `~/.local/share/codex-mcp-autostart` |
| `GRAPHITI_START_SCRIPT` | `$GRAPHITI_LOCAL_HOME/start-local.sh`; alternate backend launcher |
| `GRAPHITI_MCP_PYTHON` | `$GRAPHITI_ROOT/mcp_server/.venv/bin/python` |

Existing Context Mode packages must match 1.0.169; incompatible versions fail
without being replaced. The installer backs up the existing `.codex-plugin/`
before applying the overlay. Register the package as a Codex plugin for hooks and
skills, or use its generated snippet for the MCP server alone. Enable only one
Context Mode MCP entry.

Graphify stores graphs in `~/.cache/graphify/<repo-name>-<path-hash>/`; each checkout
shares its watcher. Leave `cwd` unset so Codex selects the repository. Ask
`graphify_status` for indexing progress. Extraction is code-only and requires no
model/API key; Graphify's source filters may include untracked code.

## Dependencies and validation

Downloads use official [uv](https://docs.astral.sh/uv/getting-started/installation/),
[Ollama](https://docs.ollama.com/linux),
[Docker rootless](https://docs.docker.com/engine/security/rootless/),
[Homebrew](https://docs.brew.sh/Installation), Node distributions (with SHA-256
verification), and npm's Context Mode package (registry integrity verification).
Ollama model tags, package-manager packages, and installer scripts can change
upstream. Existing Graphiti checkouts are never reset or upgraded; `uv sync
--locked` installs their checked-in dependency lock. GPU drivers are not installed
by this repository; Ollama may use CPU when no supported GPU runtime is present.

Run regression tests using a Graphiti Python environment with MCP installed:

```bash
~/local-memory/graphiti/mcp_server/.venv/bin/python -B -m unittest discover -s codex-mcp-autostart/tests -v
```

Tests cover concurrent startup, HTTP protocol forwarding, closed stdin, install
rollback, platform-specific unit generation, dependency reuse, and failed pulls.
Dependency tests use temporary fake commands; they do not download large models
or test every distribution's system package manager.

## Upstream

[Graphify](https://github.com/Graphify-Labs/graphify) and
[Graphiti](https://github.com/getzep/graphiti) use Apache-2.0.
[Context Mode](https://github.com/mksglu/context-mode) uses Elastic-2.0.
Upstream runtimes, credentials, graph caches, and personal memories are not included.

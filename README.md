# MCP tools for Codex

Personal adapters for code navigation, searchable context, and persistent memory.

| Integration | What it adds |
| --- | --- |
| [Graphify](graphify-codex/) | Code graphs without an LLM; automatic indexing and updates |
| [Context Mode](context-mode-codex/) | Codex launcher, lifecycle hooks, and searchable session context |
| [Graphiti](graphiti-local/) | Local memory using Ollama and FalkorDB |

## Install

Requires **Bash, Python 3, and Git** on macOS or Linux.

```bash
git clone https://github.com/Mamdasn/llm-tools.git
cd llm-tools
bash install.sh graphify      # or context-mode, graphiti, all
```

The installer prints the path to each generated `codex.toml`. Merge the selected
entries into `~/.codex/config.toml`, then reload Codex. Existing Codex settings
are left untouched. Run `bash install.sh --help` for installation path overrides.

### Graphify

Install [uv](https://docs.astral.sh/uv/) first. The installer creates an isolated
runtime with Graphify **0.9.91** and MCP SDK **1.30.0**.

- Graphs live in `~/.cache/graphify/<repo-name>-<path-hash>/`.
- Each checkout gets its own cache; chats on the same checkout share one watcher.
- Indexes refresh while connected and when a new owner connects.
- Ask Codex to call `graphify_status` to check the initial build.

Leave `cwd` unset in the MCP configuration so the chat selects the repository.
Extraction is code-only and needs no model or API key. Source filtering is handled
by Graphify, so graphs may include untracked code.

### Context Mode

Requires **Node 22.5+** and an installed **Context Mode 1.0.169** package.

```bash
CONTEXT_MODE_ROOT=/path/to/context-mode bash install.sh context-mode
```

The installer backs up the existing `.codex-plugin/`, applies the overlay, and
resolves Node's path. Register that package as a Codex plugin for hooks and skills,
or use the generated snippet for the MCP server alone. Enable only one MCP entry.

### Graphiti

Requires an existing [Graphiti checkout](https://github.com/getzep/graphiti), uv,
Ollama with **qwen3.5:9b** and **nomic-embed-text**, and a FalkorDB container named
`graphiti-db` on localhost:6379. On macOS the launcher uses Ollama.app and starts
Colima if Docker is unavailable. On Linux, start Ollama and Docker beforehand.

```bash
bash install.sh graphiti
bash ~/.local/share/graphiti-local/start-local.sh
```

The checkout defaults to `~/local-memory/graphiti`; set `GRAPHITI_ROOT` for another
location when installing and launching. Graphiti serves MCP at
`http://127.0.0.1:8765/mcp/`. Set `GRAPHITI_CONFIG` to use your own YAML file, and
`GRAPHITI_DB_CONTAINER` to use another container name. Reinstallation preserves
the installed configuration. Database creation and model downloads are separate.

## Upstream

[Graphify](https://github.com/Graphify-Labs/graphify) and
[Graphiti](https://github.com/getzep/graphiti) use Apache-2.0.
[Context Mode](https://github.com/mksglu/context-mode) uses Elastic-2.0.
Upstream runtimes, credentials, graph caches, and personal memories are not
included in this repository.

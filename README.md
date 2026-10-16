# Personal MCP integrations

Local adapters and deployment configuration used with Codex. Upstream servers,
installed dependencies, credentials, repository graphs, and personal memories
are not stored here. The examples require replacing absolute-path placeholders.

| Integration | Custom behavior | Upstream |
| --- | --- | --- |
| [Graphify](graphify-codex/) | Code-only graph creation, external per-checkout caches, shared watchers, checkout-bound query tools and status | [Graphify Labs](https://github.com/Graphify-Labs/graphify) |
| [Context Mode](context-mode-codex/) | Codex launcher, plugin metadata, lifecycle hook wiring and project-directory detection | [Context Mode](https://github.com/mksglu/context-mode) |
| [Graphiti](graphiti-local/) | Local Ollama/FalkorDB configuration and startup script | [Graphiti](https://github.com/getzep/graphiti) |

Granola uses its official hosted MCP endpoint and needs no source adapter here.
Codex's bundled Node REPL, browser, computer-use and app tools are managed by Codex.

## Graphify

Requires macOS or Linux, Git and [uv](https://docs.astral.sh/uv/).

```sh
bash graphify-codex/install.sh
```

The installer uses `~/.local/share/graphify-codex` by default; override with
`GRAPHIFY_CODEX_HOME`. It pins `graphifyy[mcp,watch,sql]==0.9.91` and `mcp==1.30.0`.
Graphify's server uses the MCP 1.x API; MCP 2.x is incompatible with this version.
It installs an isolated runtime rather than replacing another Graphify install.

Merge [codex.example.toml](graphify-codex/codex.example.toml) into
`~/.codex/config.toml`, using the paths printed by the installer. Keep `cwd`
unset. Reload Codex's MCP connection or start a new repository chat.

The adapter starts Graphify's existing MCP server and exposes seven local graph
query tools plus `graphify_status`. On connection, one owner per checkout runs
`graphify extract --code-only` and then `graphify watch`. Other chats share the
graph and can take ownership when the owner exits normally. Graphs and logs live
in `~/.cache/graphify/<repo-name>-<path-hash>/`; worktrees have separate caches.
Normal shutdown stops the owner's subprocesses. A forced kill may require manual
cleanup. Updates happen while connected; a new owner refreshes the graph.

Initial indexing is asynchronous: check `graphify_status` before querying.
Outside a Git checkout only status is available. `--repo /absolute/path` binds
the adapter explicitly; `--cache-path` prints the selected cache directory.
Indexing uses code parsing without an LLM, and child processes receive no provider
credentials from the parent environment. Graphs can include untracked source
files, subject to Graphify's filtering. Verify graph results against source.

## Context Mode

This directory is an **overlay**, not a standalone Context Mode distribution.
It targets the existing Context Mode **1.0.169** package with Node **22.5+**.
The upstream package supplies `server.bundle.mjs`, `hooks/codex/`, dependencies,
and skills. Install upstream separately according to its documentation, then
copy this directory's `.codex-plugin/` into that package's root.

The launcher preserves the chat working directory, sets the Codex platform, and
dispatches server and lifecycle-hook entrypoints. Hook commands expect `node` on
PATH; replace it with your Node executable's absolute path if the desktop app
cannot resolve it. `CODEX_BIN_DIR` optionally adds the directory containing Codex
to the launcher's PATH without a machine-specific application path.

Register the resulting package through your local Codex plugin marketplace for
the hooks and skills. The overlay includes its plugin MCP entry. Alternatively,
use [codex.example.toml](context-mode-codex/codex.example.toml) for the server
alone. Do not enable both MCP entries for the same server. This repository does
not modify your Codex marketplace or install upstream automatically.

Context Mode is licensed **Elastic-2.0**, not a permissive open-source license.
Its runtime and dependencies are not vendored here. The plugin metadata retains
the upstream author and license attribution.

## Graphiti

This packages the configuration of an existing local Graphiti deployment. It
does not create a database, download models, or change Graphiti's upstream code.
The inspected upstream checkout was commit
`dd3fd6ca7671c90b299fe8e8867a9f8439eafbeb` (MCP version 1.1.1).

Prerequisites:

- A Graphiti checkout at `~/local-memory/graphiti`, or set `GRAPHITI_ROOT`.
- uv, Docker, and an existing FalkorDB container named `graphiti-db` exposing port
  6379 locally. Override its name with `GRAPHITI_DB_CONTAINER`.
- Ollama on localhost:11434, with `qwen3.5:9b` and `nomic-embed-text` available.
- On macOS, Ollama.app; Colima is used if Docker is not running.

```sh
bash graphiti-local/start-local.sh
```

The script starts the existing database container and runs Graphiti on
`127.0.0.1:8765`. Merge [codex.example.toml](graphiti-local/codex.example.toml)
into your Codex configuration. The example uses group `personal`, a 768-dimension
embedder, and one extraction operation at a time. Unlike Graphify's code-only
index, Graphiti uses the local LLM and embedding model.

Set `GRAPHITI_CONFIG` to an absolute path to override the bundled example.
Store personal changes in ignored `config.local.yaml`. The value `ollama` in
the API-key fields is a local compatibility placeholder, not a credential.
Graphiti is Apache-2.0; database and model licenses are separate from this adapter.

## Verification

The original Graphify installation was exercised through MCP for initial builds,
queries, live edits, deletions, cache isolation, watcher sharing and ownership
transfer. Packaging checks cover syntax, configuration parsing and launcher smoke
tests. These checks do not provision a fresh Graphiti database or install a new
Context Mode plugin into Codex.

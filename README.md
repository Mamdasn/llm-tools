# LLM tools

Local browser automation, code navigation, searchable context, and persistent
memory for Codex on macOS and Linux.

## Contents and usage

| Integration | Interface | Use it for | Example request in Codex |
| --- | --- | --- | --- |
| [Playwright](#playwright) | CLI + skill | Navigate pages and test browser flows | “Use Playwright CLI to test this page.” |
| [Graphify](#graphify) | MCP | Explore code structure and dependencies | “Use Graphify to find callers of this function.” |
| [Context Mode](#context-mode) | MCP + skills + hooks | Process large outputs and search captured history | “Search Context Mode for our earlier decision.” |
| [Graphiti](#graphiti) | MCP | Remember preferences and decisions across chats | “Remember this preference in the personal group.” |

## Install

```bash
git clone https://github.com/Mamdasn/llm-tools.git
cd llm-tools
bash install.sh all
```

Or select `playwright`, `graphify`, `context-mode`, or `graphiti`. Run as your
normal user; missing system packages may request sudo. Internet access is required.
Graphiti also downloads local models and container images.

For MCP integrations, merge the printed `codex.toml` snippets into
`~/.codex/config.toml`, then reload Codex. The installer does not edit that file.
Playwright installs its skill directly; no MCP configuration is needed.

### Playwright

Installs CLI **0.1.22** and its skill into `$CODEX_HOME/skills/playwright-cli`
(default: `~/.codex/skills/playwright-cli`), backing up an existing skill.
Available on the next Codex turn. With Chrome installed:

```bash
playwright-cli open https://example.com --browser=chrome --headed
playwright-cli find "Learn more"
playwright-cli close
```

Uses a separate browser session by default. Prefer targeted queries and partial
snapshots to keep output small.

### Graphify

Installs Graphify **0.9.91** and MCP SDK **1.30.0**. Indexing is local and needs no
LLM. Leave `cwd` unset so Codex selects the repository; ask it to call
`graphify_status` to check indexing progress.

### Context Mode

Installs Context Mode **1.0.169** and its Codex overlay. Register the package as a
Codex plugin for hooks and skills, or use its generated MCP snippet for tools
only. Enable one MCP entry. Existing packages must match the pinned version.

### Graphiti

Installs Graphiti, `llama-cpp-python` **0.3.16**, a pinned `nomic-embed-text` GGUF,
FalkorDB, and a startup bridge. Ollama is not installed or started.
New configurations use your Codex CLI ChatGPT login for extraction and reranking,
with local 768-dimension embeddings. Codex inference still uses hosted models.
Install a current Codex CLI supporting `exec --ignore-user-config` and run
`codex login` first. No separate LLM API key is needed.

The embedding model runs directly inside Graphiti on the CPU. Apple Silicon uses
a prebuilt Python wheel; Linux and Intel Macs build the pinned runtime with CMake
and a C++ compiler. Model downloads are checked against a pinned SHA-256. An exact
cached copy from an earlier Ollama installation is reused without running Ollama.

The installer backs up and migrates the previous default `nomic-embed-text`
embedding configuration to `llama_cpp`. The older default `qwen3.5:9b` LLM also
migrates to Codex. Custom providers and database settings are preserved; custom
Ollama models require an explicit compatible replacement before installation.
The new embedding settings are:

```yaml
embedder:
  provider: llama_cpp
  model: nomic-embed-text
  dimensions: 768
```

`nomic-embed-text` resolves to `$GRAPHITI_LOCAL_HOME/models/nomic-embed-text.gguf`.
For a custom model, set `model` to its GGUF path and keep dimensions compatible
with the stored graph. Runtime startup does not download packages or models.
The launcher registers the adapter without editing the upstream Graphiti checkout.
Codex starts the service when its MCP connection initializes.

```bash
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti status
```

See the [startup guide](codex-mcp-autostart/README.md) for manual startup, Linux
systemd setup, configuration, and removal. `autostart` is an alias for `graphiti`.

## Configuration

Run `bash install.sh --help` for installation paths and environment overrides.
A complete fresh-Mac installation has not yet been verified end to end.

## Upstream

[Playwright CLI](https://github.com/microsoft/playwright-cli),
[Graphify](https://github.com/Graphify-Labs/graphify), and
[Graphiti](https://github.com/getzep/graphiti) use Apache-2.0.
[Context Mode](https://github.com/mksglu/context-mode) uses Elastic-2.0.
Credentials, caches, and personal memories are not included.

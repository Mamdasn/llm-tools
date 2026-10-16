# Shared MCP startup

`mcp.sh` is the canonical entry point on macOS and Linux. The Bash script selects
an installed Python interpreter and invokes a readiness/transport bridge. It
does not install dependencies on a normal Codex launch.

From the repository root, `bash install.sh graphiti` provisions dependencies and
installs this runtime. `bash install.sh all` includes it too. For an already
provisioned installation, `bash codex-mcp-autostart/install.sh` installs just the
adapter; add `--check` to validate without changing anything.

## Codex configuration

Merge the generated `~/.local/share/codex-mcp-autostart/codex.toml`:

1. Place `mcp_optional_startup_grace_ms = 0` before any TOML table headers.
2. Replace `[mcp_servers.graphiti]` with the generated command/args table.
   Remove the previous `url` from that table.
3. Reload Codex.

Codex invokes `/bin/bash /absolute/path/to/mcp.sh graphiti mcp`. The bridge starts
or reuses Graphiti and waits up to 160 seconds; the Codex entry allows 180 seconds.
The grace setting makes Codex wait for optional MCP startup when building its
tool catalog. Connection initialization still follows Codex's lifecycle; this
does not guarantee initialization of every MCP just by opening an idle window.

## Operations

```bash
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti start   # ensure ready, exit
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti status  # check only
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti mcp     # stdio transport
bash ~/.local/share/codex-mcp-autostart/mcp.sh graphiti serve   # monitor for systemd
```

Linux installation generates `codex-mcp.target` and `codex-graphiti.service` in
`${XDG_CONFIG_HOME:-~/.config}/systemd/user`. To activate:

```bash
systemctl --user daemon-reload
systemctl --user enable --now codex-mcp.target
journalctl --user -u codex-graphiti.service
```

The service restarts after failures. The target uses `Wants`, so inspect the
service's status for readiness/failures, not just the target's status. User units
normally run while logged in; enabling user lingering for boot startup is a
separate administrator choice. To disable:

```bash
systemctl --user disable --now codex-mcp.target
```

Stopping the service stops backend processes it spawned in its systemd control
group. It does not stop an independently running backend that it reused. A later
Codex connection can still start Graphiti through the bridge. Closing a Codex
connection only closes its stdio bridge; the shared backend stays available.

## Settings and recovery

`settings.json` beside the script stores HTTP endpoints, startup argv, selected
environment overrides, a state directory, and the startup timeout. Existing
settings are preserved byte-for-byte on reinstall. To change them, edit that
file explicitly; environment changes at reinstall do not replace existing settings.
`python-path` stores the interpreter as data, without shell evaluation. The
installer backs up overwritten adapter files beside the originals.

The default state directory is `~/.local/state/codex-mcp-autostart`; override it
with `CODEX_MCP_AUTOSTART_STATE_DIR` on first install. It contains a startup lock,
process identity, and `codex-graphiti-server.log`. Concurrent clients share the
lock. An already healthy backend is reused without running its startup script.
The bridge forwards the original MCP identity, tools, requests and responses.

Custom Graphiti YAML must match the local Ollama/FalkorDB setup provisioned by the
root installer. If using remote providers or another database, provision those
separately and run the adapter-only installer with `GRAPHITI_START_SCRIPT` and
`GRAPHITI_MCP_PYTHON`. Set the health and MCP URLs in `settings.json` to match.

To stop Codex from starting Graphiti, restore its HTTP-only configuration:

```toml
[mcp_servers.graphiti]
url = "http://127.0.0.1:8765/mcp/"
```

Then reload Codex. Models, volumes, configurations, and memories are retained.
If migrating from a custom macOS LaunchAgent watcher, unload that old watcher
after validating this script. This installer creates no LaunchAgent.

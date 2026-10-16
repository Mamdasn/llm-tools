#!/usr/bin/env python3
"""Install a shared Bash entry point; generate Linux user units and Codex config."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent


class InstallError(Exception):
    pass


def absolute(value):
    # Retain venv symlinks: resolving python would lose its virtual environment.
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def configuration(env=None, home=None):
    env = dict(os.environ if env is None else env)
    home = absolute(Path.home() if home is None else home)
    runtime = absolute(env.get("CODEX_MCP_AUTOSTART_HOME", home / ".local/share/codex-mcp-autostart"))
    graphiti = absolute(env.get("GRAPHITI_ROOT", home / "local-memory/graphiti"))
    local = absolute(env.get("GRAPHITI_LOCAL_HOME", home / ".local/share/graphiti-local"))
    startup_env = {"PATH": env.get("PATH", os.defpath), "GRAPHITI_ROOT": str(graphiti),
                   "GRAPHITI_CONFIG": str(absolute(env.get("GRAPHITI_CONFIG", local / "config.example.yaml")))}
    for key in ("GRAPHITI_DB_CONTAINER", "DOCKER_HOST", "DOCKER_CONTEXT"):
        if key in env:
            startup_env[key] = env[key]
    settings = {
        "health_url": "http://127.0.0.1:8765/health", "mcp_url": "http://127.0.0.1:8765/mcp/",
        "startup_command": ["/bin/bash", str(absolute(env.get("GRAPHITI_START_SCRIPT", local / "start-local.sh")))],
        "startup_env": startup_env,
        "state_dir": str(absolute(env.get("CODEX_MCP_AUTOSTART_STATE_DIR", home / ".local/state/codex-mcp-autostart"))),
        "startup_timeout_seconds": 160,
    }
    existing = runtime / "settings.json"
    if existing.exists():
        try:
            settings = json.loads(existing.read_text())
        except (OSError, ValueError) as error:
            raise InstallError(f"Cannot read existing settings: {existing}") from error
    return dict(home=home, runtime=runtime, settings=settings, existing_settings=existing.exists(),
                python=absolute(env.get("GRAPHITI_MCP_PYTHON", graphiti / "mcp_server/.venv/bin/python")),
                units=absolute(env.get("XDG_CONFIG_HOME", home / ".config")) / "systemd/user")


def validate(config):
    if platform.system() not in ("Darwin", "Linux"):
        raise InstallError("Supported platforms: macOS and Linux")
    python = config["python"]
    if not python.is_file() or not os.access(python, os.X_OK):
        raise InstallError(f"Missing Graphiti Python runtime: {python}. Run bash install.sh graphiti first.")
    if "\n" in str(python):
        raise InstallError("Python path cannot contain a newline")
    subprocess.run([str(python), "-B", "-c",
                    "import anyio; from mcp.client.streamable_http import streamable_http_client; "
                    "from mcp.server.stdio import stdio_server; from mcp.shared.message import ClientMessageMetadata\n"
                    "if 'headers' in ClientMessageMetadata.__dataclass_fields__:\n"
                    "    from mcp_types import PROTOCOL_VERSION_META_KEY\n"
                    "    from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_NAME_HEADER, "
                    "MCP_PROTOCOL_VERSION_HEADER, NAME_BEARING_METHODS, encode_header_value\n"], check=True, timeout=30)
    spec = importlib.util.spec_from_file_location("startup_bridge_validation", SOURCE / "bridge.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps(config["settings"]))
        settings = module.load_settings(path)
    if settings.startup_timeout_seconds >= 180:
        raise InstallError("Startup timeout must be below Codex's 180 seconds")
    command = settings.startup_command
    if len(command) < 2 or not Path(command[1]).is_file():
        raise InstallError("Install the Graphiti launcher first or set GRAPHITI_START_SCRIPT")


def codex_snippet(config):
    return ('# Place the top-level setting before all TOML table headers.\n'
            'mcp_optional_startup_grace_ms = 0\n\n[mcp_servers.graphiti]\ncommand = "/bin/bash"\n'
            f'args = {json.dumps([str(config["runtime"] / "mcp.sh"), "graphiti", "mcp"])}\n'
            'startup_timeout_sec = 180.0\n')


def unit_argument(value):
    # systemd parses commands itself; escape specifiers and env substitutions.
    return json.dumps(str(value).replace("%", "%%").replace("$", "$$"))


def unit_files(config):
    command = '/bin/bash ' + unit_argument(config["runtime"] / "mcp.sh") + ' graphiti '
    return {
        "codex-graphiti.service": (
            '[Unit]\nDescription=Local Graphiti MCP backend\nPartOf=codex-mcp.target\n'
            '\n[Service]\nType=exec\n'
            f'ExecStart={command}serve\nExecStartPost={command}start\n'
            'Restart=on-failure\nRestartSec=5\nTimeoutStartSec=180\nTimeoutStopSec=30\n'
            'KillMode=control-group\n'),
        "codex-mcp.target": (
            '[Unit]\nDescription=Local MCP backends for Codex\n'
            'Wants=codex-graphiti.service\nAfter=codex-graphiti.service\n'
            '\n[Install]\nWantedBy=default.target\n'),
    }


def install(config):
    validate(config)
    files = {config["runtime"] / name: (SOURCE / name).read_bytes() for name in ("bridge.py", "mcp.sh")}
    files[config["runtime"] / "python-path"] = (str(config["python"]) + "\n").encode()
    files[config["runtime"] / "codex.toml"] = codex_snippet(config).encode()
    if not config["existing_settings"]:
        files[config["runtime"] / "settings.json"] = (json.dumps(config["settings"], indent=2) + "\n").encode()
    if platform.system() == "Linux":
        files.update({config["units"] / name: content.encode() for name, content in unit_files(config).items()})
    suffix = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    changes = []
    try:
        for destination, content in files.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if destination.exists() or destination.is_symlink():
                backup = destination.with_name(destination.name + ".backup." + suffix)
                shutil.copy2(destination, backup, follow_symlinks=False)
            changes.append((destination, backup))
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stage:
                staged = Path(stage.name)
                try:
                    stage.write(content)
                    stage.flush()
                    staged.chmod(0o755 if destination.name == "mcp.sh" else 0o600)
                    staged.replace(destination)
                finally:
                    staged.unlink(missing_ok=True)
    except OSError:
        for destination, backup in reversed(changes):
            destination.unlink(missing_ok=True)
            if backup:
                shutil.copy2(backup, destination, follow_symlinks=False)
        raise
    print(f'Installed canonical entry point: {config["runtime"] / "mcp.sh"}')
    print(f'Codex configuration: {config["runtime"] / "codex.toml"}')
    if platform.system() == "Linux":
        print("Linux user units installed. Activate with:")
        print("  systemctl --user daemon-reload")
        print("  systemctl --user enable --now codex-mcp.target")
    print("Existing settings and backends preserved. Merge the snippet into Codex and reload it.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without installing or starting anything")
    args = parser.parse_args()
    try:
        config = configuration()
        if args.check:
            validate(config)
            print("Runtime prerequisites passed; nothing changed.")
        else:
            install(config)
    except (InstallError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Startup installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

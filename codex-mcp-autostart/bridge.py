#!/usr/bin/env python3
"""Start a local Graphiti service, then proxy MCP stdio to its HTTP endpoint."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


@dataclass(frozen=True)
class Settings:
    health_url: str
    mcp_url: str
    startup_command: list[str]
    startup_env: dict[str, str]
    state_dir: Path
    startup_timeout_seconds: float


def load_settings(path: Path) -> Settings:
    """Read generated settings without importing MCP or expanding shell syntax."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"Cannot read valid JSON settings from {path}") from error
    if not isinstance(raw, dict):
        raise ValueError("Settings must be a JSON object")
    for field in ("health_url", "mcp_url"):
        value = raw.get(field)
        parsed = urllib.parse.urlparse(value) if isinstance(value, str) else None
        if parsed is None or parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"{field} must be an absolute HTTP or HTTPS URL")
    command = raw.get("startup_command")
    if (not isinstance(command, list) or not command or not command[0]
            or any(not isinstance(arg, str) or "\0" in arg for arg in command)):
        raise ValueError("startup_command must be a nonempty array of command arguments")
    env = raw.get("startup_env")
    if (not isinstance(env, dict)
            or any(not isinstance(key, str) or not key or "=" in key or "\0" in key
                   or not isinstance(value, str) or "\0" in value for key, value in env.items())):
        raise ValueError("startup_env must map valid environment variable names to strings")
    state_dir = raw.get("state_dir")
    if not isinstance(state_dir, str) or not Path(state_dir).is_absolute():
        raise ValueError("state_dir must be an absolute path")
    timeout = raw.get("startup_timeout_seconds")
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("startup_timeout_seconds must be a positive finite number")
    return Settings(raw["health_url"], raw["mcp_url"], command, env, Path(state_dir), float(timeout))


class Bootstrap:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.state_dir = settings.state_dir
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def healthy(self):
        try:
            with self.opener.open(self.settings.health_url, timeout=2) as response:
                payload = json.loads(response.read(65536))
            return payload.get("service") == "graphiti-mcp" and payload.get("status") == "healthy"
        except (OSError, ValueError, AttributeError, urllib.error.URLError):
            return False

    @staticmethod
    def process_birth(pid):
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def recorded_process_alive(self, state_path):
        try:
            state = json.loads(state_path.read_text())
            pid = int(state["pid"])
            return pid > 0 and bool(state["birth"]) and self.process_birth(pid) == state["birth"]
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            return False

    def ensure(self):
        if self.healthy():
            return
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        deadline = time.monotonic() + self.settings.startup_timeout_seconds
        lock_path = self.state_dir / "codex-graphiti-startup.lock"
        with lock_path.open("a") as lock:
            os.chmod(lock_path, 0o600)
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self.healthy():
                        return
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Timed out waiting for the other Graphiti startup attempt")
                    time.sleep(0.25)
            if self.healthy():
                return
            state_path = self.state_dir / "codex-graphiti-process.json"
            process = None
            if not self.recorded_process_alive(state_path):
                log_path = self.state_dir / "codex-graphiti-server.log"
                env = os.environ.copy()
                env.update(self.settings.startup_env)
                with log_path.open("ab", buffering=0) as log:
                    os.chmod(log_path, 0o600)
                    process = subprocess.Popen(
                        self.settings.startup_command, env=env,
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        start_new_session=True,
                    )
                state_path.write_text(json.dumps({
                    "pid": process.pid,
                    "birth": self.process_birth(process.pid),
                }))
                os.chmod(state_path, 0o600)
            while time.monotonic() < deadline:
                if self.healthy():
                    return
                if process is not None and process.poll() is not None:
                    # A launcher may exit 0 after discovering an existing server.
                    if self.healthy():
                        return
                    raise RuntimeError(
                        f"Graphiti launcher exited {process.returncode}; see codex-graphiti-server.log"
                    )
                if process is None and not self.recorded_process_alive(state_path):
                    raise RuntimeError("The earlier Graphiti startup process stopped; retry initialization")
                time.sleep(0.5)
            raise RuntimeError("Graphiti is still starting; see codex-graphiti-server.log")


class BridgeProtocolHeaders:
    """Restore HTTP metadata for SDK 2; SDK 1 negotiates headers in its transport."""

    def __init__(self):
        from mcp.shared.message import ClientMessageMetadata

        self.supports_headers = "headers" in ClientMessageMetadata.__dataclass_fields__
        self.protocol_version = None
        self.initialize_id = None

    def observe_response(self, message):
        if not self.supports_headers:
            return
        wire = message.message.model_dump(by_alias=True, exclude_unset=True)
        if "method" in wire or self.initialize_id is None or wire.get("id") != self.initialize_id:
            return
        self.initialize_id = None
        result = wire.get("result")
        if isinstance(result, dict) and isinstance(result.get("protocolVersion"), str):
            self.protocol_version = result["protocolVersion"]

    def outgoing(self, message):
        if not self.supports_headers:
            return message
        from dataclasses import replace
        from mcp_types import PROTOCOL_VERSION_META_KEY
        from mcp.shared.inbound import (
            MCP_METHOD_HEADER, MCP_NAME_HEADER, MCP_PROTOCOL_VERSION_HEADER,
            NAME_BEARING_METHODS, encode_header_value,
        )
        from mcp.shared.message import ClientMessageMetadata, SessionMessage

        wire = message.message.model_dump(by_alias=True, exclude_unset=True)
        method = wire.get("method")
        if method == "initialize":
            self.initialize_id = wire.get("id")
            return message

        params = wire.get("params")
        params = params if isinstance(params, dict) else {}
        meta = params.get("_meta")
        meta = meta if isinstance(meta, dict) else {}
        envelope_version = meta.get(PROTOCOL_VERSION_META_KEY)
        version = envelope_version if isinstance(envelope_version, str) else self.protocol_version
        if version is None:
            return message

        previous = message.metadata
        metadata = previous if isinstance(previous, ClientMessageMetadata) else ClientMessageMetadata()
        headers = dict(metadata.headers or {})
        headers[MCP_PROTOCOL_VERSION_HEADER] = version
        if isinstance(method, str):
            headers[MCP_METHOD_HEADER] = method
            name_key = NAME_BEARING_METHODS.get(method)
            name = params.get(name_key) if name_key is not None else None
            if isinstance(name, str):
                headers[MCP_NAME_HEADER] = encode_header_value(name)
        return SessionMessage(message.message, metadata=replace(metadata, headers=headers))


async def bridge(mcp_url):
    import anyio
    import mcp.client.streamable_http as http_transport
    from mcp.server.stdio import stdio_server

    headers = BridgeProtocolHeaders()
    # Select the same HTTP library as the installed transport: MCP 1 uses
    # httpx and MCP 2 uses httpx2. Both clients accept these options.
    http = getattr(http_transport, "httpx2", None) or getattr(http_transport, "httpx")
    async with (
        stdio_server() as (local_read, local_write),
        http.AsyncClient(trust_env=False, timeout=http.Timeout(30.0, read=300.0)) as http_client,
    ):
        try:
            async with http_transport.streamable_http_client(mcp_url, http_client=http_client) as transport:
                remote_read, remote_write = transport[:2]
                async with anyio.create_task_group() as group:
                    async def forward(reader, writer, to_remote):
                        async for message in reader:
                            if isinstance(message, Exception):
                                raise message
                            if to_remote:
                                message = headers.outgoing(message)
                            else:
                                headers.observe_response(message)
                            await writer.send(message)
                        group.cancel_scope.cancel()

                    group.start_soon(forward, local_read, remote_write, True)
                    group.start_soon(forward, remote_read, local_write, False)
        finally:
            # stdio_server waits for its stdout writer at exit. Closing the
            # producer lets that writer drain and finish after Codex closes stdin.
            await local_write.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path(__file__).resolve().with_name("settings.json"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--ensure", action="store_true", help="Ensure HTTP service is ready, then exit")
    modes.add_argument("--check", action="store_true", help="Check readiness without starting anything")
    modes.add_argument("--supervise", action="store_true", help="Monitor readiness for a systemd user service")
    args = parser.parse_args()
    try:
        settings = load_settings(args.settings)
        service = Bootstrap(settings)
        if args.check:
            healthy = service.healthy()
            print(json.dumps({"graphiti": "healthy" if healthy else "unavailable"}))
            return 0 if healthy else 1
        service.ensure()
        if args.supervise:
            # systemd owns any backend spawned in this process's cgroup.
            # A backend already running elsewhere is reused and never killed.
            while True:
                time.sleep(5)
                if not service.healthy():
                    raise RuntimeError("Graphiti became unavailable; service manager may restart it")
        elif not args.ensure:
            import anyio
            anyio.run(bridge, settings.mcp_url)
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        # Keep backend configuration and HTTP payloads out of protocol output.
        detail = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
        print(f"[codex-graphiti] {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

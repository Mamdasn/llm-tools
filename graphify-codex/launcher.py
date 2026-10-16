import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

INSTALL_ROOT = Path(__file__).resolve().parent
RUNTIME_BIN = INSTALL_ROOT / "tools" / "graphifyy" / "bin"
CACHE_ROOT = Path.home() / ".cache" / "graphify"
GRAPH_TOOLS = {
    "query_graph", "get_node", "get_neighbors", "get_community",
    "god_nodes", "graph_stats", "shortest_path",
}
LOGGER = logging.getLogger("graphify-codex")


def repository_root(path: Path) -> Path | None:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def cache_directory(root: Path) -> Path:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", root.name)[:64]
    digest = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    return CACHE_ROOT / f"{name}-{digest}"


def child_environment(cache: Path) -> dict[str, str]:
    # Neither provider credentials nor provider-selection settings reach Graphify.
    environment = {
        key: value for key, value in os.environ.items()
        if key in {"HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL"}
    }
    environment.update({
        "PATH": f"{RUNTIME_BIN}:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
        "GRAPHIFY_OUT": str(cache),
        "GRAPHIFY_MAX_WORKERS": "2",
        "GRAPHIFY_QUERY_LOG": "0",
        "GRAPHIFY_NO_TIPS": "1",
    })
    return environment


def write_status(cache: Path, root: Path, state: str, **details: object) -> None:
    status = {
        "state": state, "repository": str(root), "cache": str(cache),
        "owner_pid": os.getpid(), "updated_at": time.time(), **details,
    }
    temporary = cache / f"status.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(cache / "status.json")


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


async def maintain_graph(root: Path, cache: Path, environment: dict[str, str]) -> None:
    process = None
    owns_lock = False
    with (cache / "watcher.lock").open("a") as lock:
        try:
            # Other chats wait here and take over if the owning chat closes.
            while not owns_lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    owns_lock = True
                except BlockingIOError:
                    await asyncio.sleep(1)

            log_path = cache / "activity.log"
            if log_path.exists() and log_path.stat().st_size > 5_000_000:
                log_path.replace(cache / "activity.previous.log")
            with log_path.open("a") as log:
                write_status(cache, root, "building", log=str(log_path))
                process = await asyncio.create_subprocess_exec(
                    str(RUNTIME_BIN / "graphify"), "extract", str(root),
                    "--code-only", "--max-workers", "2", "--exclude", "graphify-out/",
                    cwd=root, env=environment, stdin=asyncio.subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True,
                )
                returncode = await process.wait()
                if returncode != 0 or not (cache / "graph.json").is_file():
                    write_status(cache, root, "failed", exit_code=returncode, log=str(log_path))
                    LOGGER.error("Code-only graph build failed; see %s", log_path)
                    return

                process = await asyncio.create_subprocess_exec(
                    str(RUNTIME_BIN / "graphify"), "watch", str(root),
                    cwd=root, env=environment, stdin=asyncio.subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True,
                )
                write_status(cache, root, "watching", watcher_pid=process.pid, log=str(log_path))
                returncode = await process.wait()
                write_status(cache, root, "failed", exit_code=returncode, log=str(log_path))
                LOGGER.error("Graphify watcher exited; see %s", log_path)
        except asyncio.CancelledError:
            if owns_lock:
                write_status(cache, root, "stopped")
            raise
        except Exception:
            if owns_lock:
                write_status(cache, root, "failed", log=str(cache / "activity.log"))
            LOGGER.exception("Graphify index maintenance failed")
        finally:
            if process is not None:
                await stop_process(process)
            if owns_lock:
                fcntl.flock(lock, fcntl.LOCK_UN)


async def serve(root: Path | None) -> None:
    task = asyncio.current_task()
    assert task is not None
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    cache = cache_directory(root) if root is not None else None
    if cache is not None:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = Server(
        "graphify-code-only",
        instructions=(
            f"Local code-only Graphify index for {root}. "
            "Graphs are created and refreshed automatically outside the repository. "
            "Use graphify_status to check first-build progress. Graph tools are scoped "
            "to this checkout; verify results against source files. No model-based "
            "extraction is configured."
        ),
    )
    upstream = None
    graph_tools: list[types.Tool] = []

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="graphify_status",
                description="Check this checkout's code-only graph, cache location and watcher status.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
                annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
            *graph_tools,
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object]) -> types.CallToolResult:
        if root is None or cache is None:
            return types.CallToolResult(
                isError=True,
                content=[types.TextContent(type="text", text=(
                    "No Git checkout was detected in the MCP working directory. "
                    "Open a repository chat, or launch this server with --repo /absolute/path."
                ))],
            )
        if name == "graphify_status":
            status_path = cache / "status.json"
            status: dict[str, object] = json.loads(status_path.read_text()) if status_path.exists() else {"state": "starting"}
            graph = cache / "graph.json"
            status.update({
                "repository": str(root), "cache": str(cache),
                "graph_exists": graph.is_file(),
                "graph_modified_at": graph.stat().st_mtime if graph.is_file() else None,
                "llm_extraction": False,
            })
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(status))])
        if name not in GRAPH_TOOLS:
            raise ValueError(f"Unsupported tool: {name}")
        if not (cache / "graph.json").is_file():
            return types.CallToolResult(
                isError=True,
                content=[types.TextContent(type="text", text=(
                    "The initial code-only graph is not ready. Call graphify_status "
                    "for progress and the build log, then retry when it is watching."
                ))],
            )
        if "project_path" in arguments:
            raise ValueError("Graph queries are bound to this chat's checkout; project_path is unsupported.")
        assert upstream is not None
        return await upstream.call_tool(name=name, arguments=arguments)

    async with contextlib.AsyncExitStack() as stack:
        maintenance = None
        if root is not None and cache is not None:
            environment = child_environment(cache)
            upstream_log = stack.enter_context((cache / "mcp.log").open("a"))
            streams = await stack.enter_async_context(stdio_client(
                StdioServerParameters(
                    command=str(RUNTIME_BIN / "graphify-mcp"),
                    args=[str(cache / "graph.json")], cwd=str(root), env=environment,
                ),
                errlog=upstream_log,
            ))
            upstream = await stack.enter_async_context(ClientSession(*streams))
            await upstream.initialize()
            available = await upstream.list_tools()
            for tool in available.tools:
                if tool.name in GRAPH_TOOLS:
                    bound = tool.model_copy(deep=True)
                    bound.inputSchema.get("properties", {}).pop("project_path", None)
                    bound.inputSchema["additionalProperties"] = False
                    bound.annotations = types.ToolAnnotations(readOnlyHint=True, openWorldHint=False)
                    graph_tools.append(bound)
            if {tool.name for tool in graph_tools} != GRAPH_TOOLS:
                raise RuntimeError("Graphify's tool interface changed; review the integration before use.")
            maintenance = asyncio.create_task(maintain_graph(root, cache, environment))
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream=read_stream, write_stream=write_stream,
                    initialization_options=server.create_initialization_options(),
                )
        finally:
            if maintenance is not None:
                maintenance.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maintenance


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Code-only Graphify MCP with external per-checkout caches.")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--cache-path", action="store_true")
    arguments = parser.parse_args()
    root = repository_root(arguments.repo or Path.cwd())
    if arguments.cache_path:
        if root is None:
            parser.error("The working directory is not a Git checkout.")
        sys.stdout.write(str(cache_directory(root)) + "\n")
        return
    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(serve(root))


if __name__ == "__main__":
    main()

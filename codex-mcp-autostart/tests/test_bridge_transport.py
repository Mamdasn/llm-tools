"""Exercise real stdio and HTTP transports against a local, read-only fixture."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import threading
import unittest

BRIDGE = Path(__file__).resolve().parents[1] / "bridge.py"


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, payload=None, *, session=False):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session:
            self.send_header("Mcp-Session-Id", "fixture-session")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"service": "graphiti-mcp", "status": "healthy"})
        else:
            self.reply(405)

    def do_DELETE(self):
        self.reply(200)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((request, dict(self.headers)))
        method = request["method"]
        if "id" not in request:
            self.reply(202)
            return
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "Graphiti fixture", "version": "test"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": json.dumps(request["params"]["arguments"])}]}
        else:
            result = {}
        self.reply(200, {"jsonrpc": "2.0", "id": request["id"], "result": result}, session=method == "initialize")


class BridgeTransportTests(unittest.TestCase):
    def test_handshake_tool_call_headers_and_clean_eof(self):
        with tempfile.TemporaryDirectory() as temp:
            server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
            server.requests = []
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            settings = Path(temp) / "settings.json"
            settings.write_text(json.dumps({
                "health_url": base_url + "/health", "mcp_url": base_url + "/mcp/",
                "startup_command": [sys.executable, "-c", "raise SystemExit('must not launch')"],
                "startup_env": {}, "state_dir": str(Path(temp) / "state"),
                "startup_timeout_seconds": 5,
            }))
            env = os.environ.copy()
            env.update({"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
                        "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""})
            process = subprocess.Popen([sys.executable, "-B", str(BRIDGE), "--settings", str(settings)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, env=env)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                def send(payload, response=True):
                    process.stdin.write(json.dumps({"jsonrpc": "2.0", **payload}) + "\n")
                    process.stdin.flush()
                    if not response:
                        return None
                    self.assertTrue(selector.select(15), "Timed out waiting for bridge response")
                    line = process.stdout.readline()
                    self.assertTrue(line, "Bridge exited before responding")
                    return json.loads(line)

                init = send({"id": "init", "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "bridge-test", "version": "1"},
                }})
                self.assertEqual(init["result"]["serverInfo"]["name"], "Graphiti fixture")
                send({"method": "notifications/initialized"}, response=False)
                self.assertEqual(send({"id": 2, "method": "tools/list"})["result"]["tools"][0]["name"], "echo")
                arguments = {"literal": "$(never-run)", "unicode": "こんにちは"}
                result = send({"id": "preserved-id", "method": "tools/call", "params": {"name": "echo", "arguments": arguments}})
                self.assertEqual(result["id"], "preserved-id")
                self.assertEqual(json.loads(result["result"]["content"][0]["text"]), arguments)
                self.assertEqual(send({"id": 4, "method": "ping"})["result"], {})
                calls = [(wire, {key.lower(): value for key, value in headers.items()})
                         for wire, headers in server.requests if wire["method"] != "initialize"]
                for wire, headers in calls:
                    self.assertEqual(headers.get("mcp-protocol-version"), "2025-06-18", wire["method"])
                    self.assertEqual(headers.get("mcp-session-id"), "fixture-session")
                self.assertFalse((Path(temp) / "state").exists(), "Healthy backend must not run its startup command")
                process.stdin.close()
                process.stdin = None
                _, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                selector.close()
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

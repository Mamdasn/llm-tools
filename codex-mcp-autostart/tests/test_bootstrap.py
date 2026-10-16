"""Validate configuration and exercise concurrent, detached cold startup."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BRIDGE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE_DIR))
from bridge import Bootstrap, load_settings

# The fixture deliberately uses file readiness, so no real Graphiti data or
# network service is touched. Separate clients still contend on the real flock.
WORKER = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from bridge import Bootstrap, load_settings
settings = load_settings(Path(sys.argv[2]))
Bootstrap.healthy = lambda self: (self.state_dir / 'ready').exists()
Bootstrap(settings).ensure()
"""
BACKEND = """
import json, os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
with (root / 'starts').open('a') as file:
    file.write('started\\n')
(root / 'environment').write_text(json.dumps({
    'inherited': os.environ.get('BRIDGE_TEST_INHERITED'),
    'override': os.environ.get('BRIDGE_TEST_OVERRIDE'),
}))
time.sleep(0.25)
(root / 'ready').touch()
time.sleep(60)
"""


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings_file = self.root / "settings.json"
        self.raw = {
            "health_url": "http://127.0.0.1:8765/health", "mcp_url": "http://127.0.0.1:8765/mcp/",
            "startup_command": [sys.executable, "-c", BACKEND, str(self.root)],
            "startup_env": {"BRIDGE_TEST_OVERRIDE": "configured"}, "state_dir": str(self.root),
            "startup_timeout_seconds": 5,
        }
        self.settings_file.write_text(json.dumps(self.raw))

    def tearDown(self):
        # Only stop this test's detached backend, after verifying its birth time.
        state_file = self.root / "codex-graphiti-process.json"
        if state_file.exists():
            service = Bootstrap(load_settings(self.settings_file))
            if service.recorded_process_alive(state_file):
                os.kill(json.loads(state_file.read_text())["pid"], signal.SIGTERM)
        self.temp.cleanup()

    def test_settings_reject_invalid_command_env_timeout_and_relative_state(self):
        for field, value in [("startup_command", "bash start.sh"), ("startup_command", []),
                             ("startup_env", {"BAD=NAME": "value"}), ("state_dir", "relative"),
                             ("startup_timeout_seconds", True), ("startup_timeout_seconds", 0),
                             ("startup_timeout_seconds", float("inf")), ("mcp_url", "file:///tmp/mcp")]:
            with self.subTest(field=field, value=value):
                invalid = dict(self.raw)
                invalid[field] = value
                candidate = self.root / "invalid.json"
                candidate.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    load_settings(candidate)

    def test_concurrent_clients_start_once_and_preserve_environment(self):
        env = os.environ.copy()
        env.update({"BRIDGE_TEST_INHERITED": "retained", "BRIDGE_TEST_OVERRIDE": "old"})
        clients = [subprocess.Popen(
            [sys.executable, "-B", "-c", WORKER, str(BRIDGE_DIR), str(self.settings_file)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        ) for _ in range(3)]
        try:
            for client in clients:
                stdout, stderr = client.communicate(timeout=10)
                self.assertEqual(client.returncode, 0, stderr)
                self.assertEqual(stdout, "", "Startup must not pollute the MCP protocol stream")
            self.assertEqual((self.root / "starts").read_text().splitlines(), ["started"])
            self.assertEqual(json.loads((self.root / "environment").read_text()),
                             {"inherited": "retained", "override": "configured"})
            service = Bootstrap(load_settings(self.settings_file))
            state_file = self.root / "codex-graphiti-process.json"
            self.assertTrue(service.recorded_process_alive(state_file), "Backend must outlive its bootstrap client")
            state = json.loads(state_file.read_text())
            state["birth"] = "a different process with the same PID"
            state_file.write_text(json.dumps(state))
            self.assertFalse(service.recorded_process_alive(state_file))
            state["birth"] = service.process_birth(state["pid"])
            state_file.write_text(json.dumps(state))
        finally:
            for client in clients:
                if client.poll() is None:
                    client.kill()
                client.communicate(timeout=5)

    def test_healthy_service_never_launches_backend(self):
        service = Bootstrap(load_settings(self.settings_file))
        with patch.object(service, "healthy", return_value=True), patch("bridge.subprocess.Popen") as spawn:
            service.ensure()
            spawn.assert_not_called()
        self.assertFalse((self.root / "codex-graphiti-startup.lock").exists())


if __name__ == "__main__":
    unittest.main()

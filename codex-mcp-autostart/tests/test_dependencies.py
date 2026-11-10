"""Exercise provisioning decisions with fake commands; never install on the host."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dependency test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls"
        self.env = dict(os.environ, PATH=str(self.bin) + ":" + os.environ["PATH"], CALLS=str(self.log),
                        HOME=str(self.root), XDG_STATE_HOME=str(self.root / "state"))
        self.command("uname", "echo Linux")
        self.command("docker", 'echo "docker $*" >> "$CALLS"\nif [[ "$1 $2" == "container inspect" ]]; then exit "${CONTAINER_MISSING:-0}"; fi')
        self.command("ollama", 'echo forbidden-ollama >> "$CALLS"; exit 1')
        graphiti = self.root / "graphiti/mcp_server/.venv/bin"
        graphiti.mkdir(parents=True)
        (graphiti / "python").write_text('#!/bin/bash\nexec ' + shlex.quote(sys.executable) + ' "$@"\n')
        (graphiti / "python").chmod(0o755)
        self.config = self.root / "local/config.example.yaml"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({
            "llm": {"provider": "codex", "model": "gpt-6.1-sol"},
            "embedder": {"provider": "openai", "model": "custom-remote"},
        }))

    def command(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_function(self, command, extra_env=None):
        assignments = {"source_dir": str(REPO), "graphiti_root": str(self.root / "graphiti"),
                       "graphiti_dir": str(self.root / "local"), "context_dir": str(self.root / "context")}
        script = "set -euo pipefail\n" + "\n".join(k + "=" + shlex.quote(v) for k, v in assignments.items())
        script += '\nsource "$source_dir/scripts/dependencies.sh"\n' + command
        return subprocess.run(["bash", "-c", script], env=dict(self.env, **(extra_env or {})), capture_output=True, text=True)

    def test_existing_database_and_custom_embedding_provider_are_reused(self):
        before = self.config.read_bytes()
        result = self.run_function("provision_graphiti_data")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertNotIn("docker run", calls)
        self.assertNotIn("ollama", calls)
        self.assertIn("docker start graphiti-db", calls)
        self.assertEqual(self.config.read_bytes(), before)

    def test_missing_database_binds_loopback_without_starting_ollama(self):
        result = self.run_function("provision_graphiti_data", {"CONTAINER_MISSING": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn("-p 127.0.0.1:6379:6379", calls)
        self.assertIn("graphiti-memory:/data", calls)
        self.assertNotIn("ollama", calls)

    def test_missing_custom_model_stops_before_database_start(self):
        self.config.write_text(json.dumps({
            "llm": {"provider": "codex", "model": "gpt-6.1-sol"},
            "embedder": {"provider": "llama_cpp", "model": str(self.root / "missing.gguf")},
        }))
        result = self.run_function("provision_graphiti_data")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Install the configured custom GGUF", result.stderr)
        self.assertFalse(self.log.exists())

    def test_runtime_starts_without_ollama_or_injected_api_credentials(self):
        python = self.root / "graphiti/mcp_server/.venv/bin/python"
        python.write_text('#!/bin/bash\necho "python $*" >> "$CALLS"\n'
                          '[[ -z "${OPENAI_API_KEY:-}${OPENAI_BASE_URL:-}" ]]\n')
        result = self.run_function('GRAPHITI_ROOT="$graphiti_root" bash "$source_dir/graphiti-local/start-local.sh"',
                                   {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertNotIn("ollama", calls)
        self.assertIn("codex_server.py", calls)

    def test_linux_does_not_try_to_start_colima(self):
        self.command("docker", "exit 1")
        self.command("systemctl", 'echo "$*" >> "$CALLS"; exit 1')
        self.command("colima", 'echo forbidden >> "$CALLS"')
        result = self.run_function('source "$source_dir/graphiti-local/runtime.sh"; start_docker')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("forbidden", self.log.read_text())
        self.assertIn("Docker is unavailable", result.stderr)

    def test_existing_context_package_is_not_reinstalled(self):
        (self.root / "context").mkdir()
        self.command("npm", 'echo forbidden >> "$CALLS"; exit 1')
        result = self.run_function("ensure_context_mode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())

    def test_existing_private_node_is_reused_when_global_node_is_old(self):
        self.command("node", "exit 1")
        node = self.root / ".local/share/llm-tools/node/bin"
        node.mkdir(parents=True)
        for name in ("node", "npm"):
            (node / name).write_text("#!/bin/bash\nexit 0\n")
            (node / name).chmod(0o755)
        result = self.run_function("ensure_node; command -v node")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(node / "node"))


if __name__ == "__main__":
    unittest.main()

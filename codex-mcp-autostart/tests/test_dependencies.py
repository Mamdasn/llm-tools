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
        self.command("ollama", 'echo "ollama $*" >> "$CALLS"\nif [[ "$1" == show && "$2" == qwen3.5:9b ]]; then exit "${MODEL_MISSING:-0}"; fi\nif [[ "$1" == pull ]]; then exit "${PULL_FAIL:-0}"; fi')
        graphiti = self.root / "graphiti/mcp_server/.venv/bin"
        graphiti.mkdir(parents=True)
        # Stub model extraction: validate selection semantics without PyYAML.
        (graphiti / "python").write_text('#!/bin/bash\ncat >/dev/null\nprintf "qwen3.5:9b\\nnomic-embed-text\\n"\n')
        (graphiti / "python").chmod(0o755)

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

    def test_existing_database_and_models_are_reused(self):
        result = self.run_function("provision_graphiti_data")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertNotIn("docker run", calls)
        self.assertNotIn("ollama pull", calls)
        self.assertIn("docker start graphiti-db", calls)

    def test_missing_database_binds_loopback_and_only_missing_model_downloaded(self):
        result = self.run_function("provision_graphiti_data", {"CONTAINER_MISSING": "1", "MODEL_MISSING": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn("-p 127.0.0.1:6379:6379", calls)
        self.assertIn("graphiti-memory:/data", calls)
        self.assertIn("ollama pull qwen3.5:9b", calls)
        self.assertNotIn("ollama pull nomic", calls)

    def test_failed_model_download_is_not_reported_successful(self):
        result = self.run_function("provision_graphiti_data", {"MODEL_MISSING": "1", "PULL_FAIL": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Model download failed", result.stderr)

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

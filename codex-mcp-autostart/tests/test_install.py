import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("autostart_install", SOURCE / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="startup test ")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = installer.configuration(env={"PATH": "/test/bin:/usr/bin"}, home=self.home)

    def test_only_allowlisted_environment_saved_and_paths_retained(self):
        env = {"PATH": "/bin", "GRAPHITI_ROOT": str(self.home / "other"), "OPENAI_API_KEY": "secret"}
        config = installer.configuration(env=env, home=self.home)
        self.assertEqual(config["python"], self.home / "other/mcp_server/.venv/bin/python")
        self.assertNotIn("secret", json.dumps(config["settings"]))
        self.assertEqual(config["settings"]["startup_env"]["GRAPHITI_ROOT"], env["GRAPHITI_ROOT"])

    def test_codex_and_linux_use_same_bash_script_with_escaped_paths(self):
        self.config["runtime"] = self.home / 'quote " percent % dollar $'
        snippet = installer.codex_snippet(self.config)
        args = json.loads(next(line[7:] for line in snippet.splitlines() if line.startswith("args = ")))
        self.assertEqual(args, [str(self.config["runtime"] / "mcp.sh"), "graphiti", "mcp"])
        unit = installer.unit_files(self.config)["codex-graphiti.service"]
        self.assertIn('percent %% dollar $$', unit)
        self.assertIn('\\"', unit)
        self.assertIn('graphiti serve', unit)
        self.assertIn('graphiti start', unit)

    def test_failed_validation_does_not_touch_installation(self):
        with mock.patch.object(installer, "validate", side_effect=installer.InstallError("missing")):
            with self.assertRaises(installer.InstallError):
                installer.install(self.config)
        self.assertFalse(self.config["runtime"].exists())

    def test_mac_reinstall_preserves_settings_and_does_not_create_os_service(self):
        runtime = self.config["runtime"]
        runtime.mkdir(parents=True)
        original = json.dumps(self.config["settings"], separators=(",", ":"))
        (runtime / "settings.json").write_text(original)
        (runtime / "bridge.py").write_text("old")
        config = installer.configuration(env={}, home=self.home)
        with mock.patch.object(installer, "validate"), mock.patch.object(installer.platform, "system", return_value="Darwin"), mock.patch("builtins.print"):
            installer.install(config)
        self.assertEqual((runtime / "settings.json").read_text(), original)
        self.assertEqual(next(runtime.glob("bridge.py.backup.*")).read_text(), "old")
        self.assertEqual((runtime / "mcp.sh").stat().st_mode & 0o777, 0o755)
        self.assertFalse(config["units"].exists())
        self.assertFalse((self.home / "Library").exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_linux_installs_units_without_enabling_them(self):
        with mock.patch.object(installer, "validate"), mock.patch.object(installer.platform, "system", return_value="Linux"), mock.patch("builtins.print"), mock.patch.object(installer.subprocess, "run") as run:
            installer.install(self.config)
        run.assert_not_called()
        self.assertTrue((self.config["units"] / "codex-mcp.target").is_file())

    def test_partial_write_failure_restores_old_files(self):
        runtime = self.config["runtime"]
        runtime.mkdir(parents=True)
        (runtime / "bridge.py").write_text("previous")
        original = Path.replace
        def fail_mcp(path, dest):
            if dest.name == "mcp.sh":
                raise OSError("injected failure")
            return original(path, dest)
        with mock.patch.object(installer, "validate"), mock.patch.object(installer.platform, "system", return_value="Darwin"), mock.patch.object(Path, "replace", fail_mcp):
            with self.assertRaises(OSError):
                installer.install(self.config)
        self.assertEqual((runtime / "bridge.py").read_text(), "previous")
        self.assertFalse((runtime / "mcp.sh").exists())

    def test_bash_entry_passes_arguments_without_shell_evaluation(self):
        (self.home / "mcp.sh").write_bytes((SOURCE / "mcp.sh").read_bytes())
        python = self.home / 'python $literal'
        python.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
        python.chmod(0o755)
        (self.home / "python-path").write_text(str(python) + "\n")
        env = dict(os.environ)
        env.pop("GRAPHITI_MCP_PYTHON", None)
        for mode, expected in (("start", "--ensure"), ("status", "--check"), ("serve", "--supervise"), ("mcp", None)):
            result = subprocess.run(["bash", str(self.home / "mcp.sh"), "graphiti", mode], env=env, capture_output=True, text=True, check=True)
            args = [str(self.home / "bridge.py"), "--settings", str(self.home / "settings.json")]
            if expected: args.append(expected)
            self.assertEqual(result.stdout.splitlines(), args)


if __name__ == "__main__":
    unittest.main()

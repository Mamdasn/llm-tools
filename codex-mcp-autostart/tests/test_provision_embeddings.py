"""Exercise config migration and model integrity without downloading a real model."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

SOURCE = Path(__file__).resolve().parents[2] / 'graphiti-local/provision_embeddings.py'
spec = importlib.util.spec_from_file_location('provision_embeddings', SOURCE)
provisioner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provisioner)


class EmbeddingProvisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config.yaml'
        self.destination = self.root / 'runtime/models/nomic-embed-text.gguf'
        self.raw = {
            'llm': {'provider': 'codex', 'model': 'gpt-6.1-sol'},
            'embedder': {
                'provider': 'openai', 'model': 'nomic-embed-text', 'dimensions': 768,
                'providers': {'openai': {'api_key': 'ollama', 'api_url': 'http://localhost:11434/v1'}},
            },
            'database': {'provider': 'falkordb', 'providers': {'falkordb': {'database': 'existing'}}},
        }
        self.config.write_text(json.dumps(self.raw))

    def test_default_migration_preserves_database_and_backs_up_original(self):
        before = self.config.read_bytes()
        with patch.object(provisioner, 'ensure_model') as model:
            provisioner.provision(self.config, self.root / 'runtime')
        model.assert_called_once_with(self.destination)
        updated = yaml.safe_load(self.config.read_text())
        self.assertEqual(updated['embedder'], dict(provider='llama_cpp', model='nomic-embed-text', dimensions=768))
        self.assertEqual(updated['llm'], self.raw['llm'])
        self.assertEqual(updated['database'], self.raw['database'])
        self.assertEqual(next(self.root.glob('config.yaml.backup.*')).read_bytes(), before)

    def test_previous_default_llm_also_migrates_to_codex(self):
        self.raw['llm'] = dict(self.raw['embedder'], model='qwen3.5:9b', small_model='qwen3.5:9b')
        self.config.write_text(json.dumps(self.raw))
        with patch.object(provisioner, 'ensure_model'):
            provisioner.provision(self.config, self.root / 'runtime')
        self.assertEqual(yaml.safe_load(self.config.read_text())['llm']['provider'], 'codex')

    def test_failed_model_setup_leaves_config_and_backups_untouched(self):
        before = self.config.read_bytes()
        with patch.object(provisioner, 'ensure_model', side_effect=OSError('download failed')):
            with self.assertRaisesRegex(OSError, 'download failed'):
                provisioner.provision(self.config, self.root / 'runtime')
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(list(self.root.glob('*.backup.*')), [])

    def test_custom_ollama_model_is_not_silently_replaced(self):
        self.raw['embedder']['model'] = 'custom-embedding'
        self.config.write_text(json.dumps(self.raw))
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Custom Ollama embeddings'):
            provisioner.provision(self.config, self.root / 'runtime')
        self.assertEqual(self.config.read_bytes(), before)

    def test_cached_model_is_copied_and_no_service_or_download_runs(self):
        content = b'GGUF test fixture'
        sha256 = hashlib.sha256(content).hexdigest()
        cached = self.root / '.ollama/models/blobs' / ('sha256-' + sha256)
        cached.parent.mkdir(parents=True)
        cached.write_bytes(content)
        with patch.object(provisioner, 'MODEL_SHA256', sha256), \
             patch.object(Path, 'home', return_value=self.root), \
             patch.object(provisioner.subprocess, 'run') as command:
            provisioner.ensure_model(self.destination)
            provisioner.ensure_model(self.destination)
        command.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), content)

    def test_corrupt_download_is_not_published(self):
        def download(args, **kwargs):
            Path(args[-1]).write_bytes(b'corrupt download')

        with patch.object(Path, 'home', return_value=self.root), \
             patch.object(provisioner.subprocess, 'run', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                provisioner.ensure_model(self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_failed_download_is_not_published(self):
        with patch.object(Path, 'home', return_value=self.root), \
             patch.object(provisioner.subprocess, 'run', side_effect=subprocess.CalledProcessError(22, 'curl')):
            with self.assertRaises(subprocess.CalledProcessError):
                provisioner.ensure_model(self.destination)
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()

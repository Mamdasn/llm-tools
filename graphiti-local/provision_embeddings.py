"""Provision the pinned Nomic GGUF and migrate the previous default configuration."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

import yaml

MODEL_SHA256 = '970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6'
MODEL_URL = (
    'https://registry.ollama.ai/v2/library/nomic-embed-text/blobs/sha256:' + MODEL_SHA256
)


def digest(path: Path) -> str:
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def uses_ollama(section: dict) -> bool:
    provider = section.get('provider', '').lower()
    endpoint = section.get('providers', {}).get(provider, {}).get('api_url', '')
    url = urlsplit(endpoint)
    return url.hostname in ('localhost', '127.0.0.1', '::1') and url.port == 11434


def prepare_config(config: dict) -> bool:
    changed = False
    llm = config['llm']
    if uses_ollama(llm):
        if llm.get('model') != 'qwen3.5:9b' or llm.get('small_model', 'qwen3.5:9b') != 'qwen3.5:9b':
            raise ValueError('Custom Ollama LLM: set llm.provider to codex and select llm.model first.')
        config['llm'] = dict(provider='codex', model='gpt-6.1-sol', max_tokens=llm.get('max_tokens', 8192))
        changed = True
    embedder = config['embedder']
    if uses_ollama(embedder):
        if embedder.get('model') != 'nomic-embed-text' or embedder.get('dimensions') != 768:
            raise ValueError('Custom Ollama embeddings: configure a compatible llama_cpp GGUF first.')
        config['embedder'] = dict(provider='llama_cpp', model='nomic-embed-text', dimensions=768)
        changed = True
    return changed


def ensure_model(destination: Path) -> None:
    if destination.exists():
        if digest(destination) != MODEL_SHA256:
            raise ValueError(f'Embedding model checksum mismatch: {destination}')
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reuse the exact model bytes; no Ollama executable or running service is needed.
    cached = Path.home() / '.ollama/models/blobs' / ('sha256-' + MODEL_SHA256)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / 'model.gguf'
        if cached.is_file() and digest(cached) == MODEL_SHA256:
            shutil.copyfile(cached, staged)
        else:
            subprocess.run([
                'curl', '--fail', '--show-error', '--location', '--proto', '=https',
                '--proto-redir', '=https', '--retry', '3', MODEL_URL, '-o', str(staged),
            ], check=True)
        if digest(staged) != MODEL_SHA256:
            raise ValueError('Downloaded embedding model checksum mismatch; rerun installation.')
        staged.replace(destination)


def provision(config_path: Path, runtime: Path) -> None:
    config = yaml.safe_load(config_path.read_text())
    changed = prepare_config(config)
    embedder = config['embedder']
    if embedder['provider'].lower() == 'llama_cpp':
        if embedder['model'] == 'nomic-embed-text':
            if embedder['dimensions'] != 768:
                raise ValueError('The pinned Nomic embedding model requires 768 dimensions.')
            ensure_model(runtime / 'models/nomic-embed-text.gguf')
        elif not Path(embedder['model']).expanduser().is_file():
            raise ValueError('Install the configured custom GGUF embedding model before continuing.')
    if changed:
        # Publish migration only after model provisioning succeeds, preserving a full backup.
        with tempfile.NamedTemporaryFile(
            prefix=config_path.name + '.backup.', dir=config_path.parent, delete=False,
        ) as backup:
            backup_path = Path(backup.name)
        shutil.copy2(config_path, backup_path)
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        print(f'Migrated standard Graphiti configuration; backup: {backup_path}')


if __name__ == '__main__':
    try:
        provision(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'Embedding setup failed: {error}')

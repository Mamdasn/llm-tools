"""Register the local Codex provider before starting upstream Graphiti."""

import importlib
import runpy
import sys
from pathlib import Path
from typing import Any

from codex_client import CodexClient, CodexRerankerClient
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig


def main() -> None:
    server_root = Path.cwd()
    sys.path.insert(0, str(server_root / 'src'))
    factories = importlib.import_module('services.factories')
    original_llm = factories.LLMClientFactory.create
    original_reranker = factories.CrossEncoderFactory.create

    def create_llm(config: Any) -> LLMClient:
        if config.provider.lower() != 'codex':
            return original_llm(config)
        return CodexClient(
            config=LLMConfig(
                model=config.model,
                small_model=config.model,
                max_tokens=config.max_tokens,
            )
        )

    def create_reranker(llm_config: Any, embedder_config: Any) -> CrossEncoderClient:
        if llm_config.provider.lower() != 'codex':
            return original_reranker(llm_config, embedder_config)
        return CodexRerankerClient(client=CodexClient(config=LLMConfig(model=llm_config.model)))

    factories.LLMClientFactory.create = staticmethod(create_llm)
    factories.CrossEncoderFactory.create = staticmethod(create_reranker)
    runpy.run_path(str(server_root / 'main.py'), run_name='__main__')


if __name__ == '__main__':
    main()

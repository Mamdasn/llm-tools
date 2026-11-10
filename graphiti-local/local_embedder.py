"""Run the existing Nomic embedding model directly, without an Ollama service."""

import asyncio
import os
from pathlib import Path
from threading import Lock

from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig


class LocalEmbedder(EmbedderClient):
    def __init__(self, model_path: str, dimensions: int) -> None:
        from llama_cpp import Llama

        if model_path == 'nomic-embed-text':
            model_path = str(Path(__file__).parent / 'models/nomic-embed-text.gguf')
        else:
            model_path = str(Path(model_path).expanduser())
        self.config = EmbedderConfig(embedding_dim=dimensions)
        self._lock = Lock()
        self._model = Llama(
            model_path=model_path,
            embedding=True,
            n_ctx=8192,
            n_batch=8192,
            n_ubatch=8192,
            n_threads=min(4, os.cpu_count() or 1),
            n_gpu_layers=0,
            offload_kqv=False,
            verbose=False,
        )
        if self._model.n_embd() != dimensions:
            raise ValueError('Local embedding dimensions must match the existing graph index')

    def _embed(self, texts: list[str]) -> list[list[float]]:
        # The model context is shared; serialize inference and keep it off the event loop.
        with self._lock:
            return [self._model.embed(text, normalize=True) for text in texts]

    async def create(self, input_data: str | list[str]) -> list[float]:
        text = input_data if isinstance(input_data, str) else input_data[0]
        return (await self.create_batch([text]))[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed, input_data_list)

"""Embedding function for the vector store.

Default: ChromaDB's bundled ``all-MiniLM-L6-v2`` (384-dim) — runs locally on
CPU with no API key, computed client-side by both ingestion and queries.

Optional: set ``EMBEDDING_BASE_URL`` (and ``EMBEDDING_MODEL``) to offload
embedding to an OpenAI-compatible ``/v1/embeddings`` server — e.g. llama.cpp
running an embedding GGUF on a GPU box. Much faster for bulk ingestion.

⚠️ Whatever embeds at write time must embed at query time (same model, same
dimensions) — switching embedders requires a fresh collection and a full
re-ingest (see README).
"""

from __future__ import annotations

import httpx
from chromadb.utils import embedding_functions

from star_agent.config import Settings


class OpenAICompatibleEmbeddingFunction:
    """Minimal EF for OpenAI-compatible /v1/embeddings endpoints (llama.cpp)."""

    def __init__(self, base_url: str, model: str) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._client = httpx.Client(timeout=120.0)

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 — chroma EF protocol
        resp = self._client.post(
            self._url, json={"model": self._model, "input": input}
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # API returns items with an "index" field; keep input order.
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def get_embedding_function(settings: Settings | None = None):
    """Return the configured embedding function.

    Local MiniLM by default; an external OpenAI-compatible server when
    ``EMBEDDING_BASE_URL`` is configured.
    """
    if settings is not None and settings.embedding_base_url:
        return OpenAICompatibleEmbeddingFunction(
            settings.embedding_base_url, settings.embedding_model
        )
    return embedding_functions.DefaultEmbeddingFunction()

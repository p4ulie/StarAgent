"""Embedding function for the vector store.

Default: ChromaDB's bundled ``all-MiniLM-L6-v2`` (384-dim) — runs locally on
CPU with no API key, computed client-side by both ingestion and queries.

Optional: set ``EMBEDDING_BASE_URL`` (and ``EMBEDDING_MODEL``) to offload
embedding to an OpenAI-compatible ``/v1/embeddings`` server — e.g. llama.cpp
running an embedding GGUF on a GPU box. Much faster for bulk ingestion.

⚠️ Whatever embeds at write time must embed at query time (same model, same
dimensions). Switching embedders requires a **fresh collection** (different
``CHROMA_COLLECTION`` or a wiped ``chroma-data/``) and a full re-ingest — a
collection stores its embedding function, and dimensions differ between models.
"""

from __future__ import annotations

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils import embedding_functions

from star_agent.config import Settings


class OpenAICompatibleEmbeddingFunction(EmbeddingFunction[Documents]):
    """Chroma embedding function backed by an OpenAI-compatible /v1 server."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = httpx.Client(timeout=120.0, headers=headers)

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 — Chroma EF protocol
        resp = self._client.post(
            f"{self._base_url}/embeddings",
            json={"model": self._model, "input": list(input)},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda d: d["index"])  # preserve input order
        return [d["embedding"] for d in data]

    @staticmethod
    def name() -> str:
        return "star_agent_openai_compatible"

    def get_config(self) -> dict:
        # The API key is a secret — never persist it in the collection config.
        return {"base_url": self._base_url, "model": self._model}

    @classmethod
    def build_from_config(cls, config: dict) -> "OpenAICompatibleEmbeddingFunction":
        return cls(base_url=config["base_url"], model=config["model"])


def get_embedding_function(settings: Settings | None = None):
    """Return the configured embedding function.

    Local MiniLM by default; an external OpenAI-compatible server when
    ``EMBEDDING_BASE_URL`` is configured.
    """
    if settings is not None and settings.embedding_base_url:
        return OpenAICompatibleEmbeddingFunction(
            settings.embedding_base_url,
            settings.embedding_model,
            settings.embedding_api_key,
        )
    return embedding_functions.DefaultEmbeddingFunction()

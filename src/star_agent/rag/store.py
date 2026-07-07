"""Thin wrapper around a ChromaDB collection.

Connects to the Chroma server (its own container) over HTTP and exposes the
few operations the rest of the app needs: upsert, similarity query, and count.
Embeddings are produced client-side by the collection's embedding function
(see :mod:`star_agent.rag.embeddings`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import chromadb

from star_agent.config import Settings
from star_agent.rag.embeddings import get_embedding_function


class VectorStore:
    """A single Chroma collection used as the Star Citizen knowledge base."""

    def __init__(self, settings: Settings) -> None:
        self._client = chromadb.HttpClient(
            host=settings.chroma_host, port=settings.chroma_port
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        ids: Sequence[str],
        documents: Sequence[str],
        metadatas: Sequence[Mapping[str, Any]],
    ) -> None:
        """Insert or update documents by stable id (re-runnable ingestion)."""
        if not ids:
            return
        self._collection.upsert(
            ids=list(ids),
            documents=list(documents),
            metadatas=[dict(m) for m in metadatas],
        )

    def query(
        self,
        text: str,
        n_results: int = 5,
        where: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Nearest-neighbour search; returns Chroma's raw result dict."""
        return self._collection.query(
            query_texts=[text],
            n_results=n_results,
            where=dict(where) if where else None,
        )

    def count(self) -> int:
        """Number of documents currently indexed."""
        return self._collection.count()

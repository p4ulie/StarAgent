"""Embedding function for the vector store.

Uses ChromaDB's bundled default, ``all-MiniLM-L6-v2`` (384-dim), which runs
locally with no API key. It is computed client-side, so both ingestion and
query embedding use this same function — keep it consistent across writes and
reads or similarity search breaks.
"""

from __future__ import annotations

from chromadb.utils import embedding_functions


def get_embedding_function():
    """Return the local default (MiniLM) embedding function.

    Downloads the model on first use, then caches it on disk.
    """
    return embedding_functions.DefaultEmbeddingFunction()

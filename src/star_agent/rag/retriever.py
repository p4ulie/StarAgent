"""Turn a question into ranked, citable context for the agent."""

from __future__ import annotations

from dataclasses import dataclass

from star_agent.rag.store import VectorStore


@dataclass(slots=True)
class RetrievedChunk:
    """One retrieved passage plus provenance for citation."""

    text: str
    source: str
    url: str
    title: str
    score: float  # similarity in [0, 1]; higher is closer


class Retriever:
    """Queries the vector store and assembles cited context."""

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def retrieve(self, query: str, n_results: int = 5) -> list[RetrievedChunk]:
        result = self._store.query(query, n_results=n_results)
        chunks: list[RetrievedChunk] = []
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for text, meta, dist in zip(documents, metadatas, distances, strict=False):
            meta = meta or {}
            chunks.append(
                RetrievedChunk(
                    text=text or "",
                    source=str(meta.get("source", "unknown")),
                    url=str(meta.get("url", "")),
                    title=str(meta.get("title", "")),
                    # cosine distance -> similarity
                    score=round(1.0 - float(dist), 4),
                )
            )
        return chunks

    @staticmethod
    def format_context(chunks: list[RetrievedChunk]) -> str:
        """Render chunks as a numbered, citable context block for the LLM."""
        if not chunks:
            return "No relevant information was found in the knowledge base."
        parts: list[str] = []
        for i, c in enumerate(chunks, start=1):
            header = f"[{i}] {c.title or c.source}".strip()
            if c.url:
                header += f" ({c.url})"
            parts.append(f"{header}\n{c.text}")
        return "\n\n".join(parts)

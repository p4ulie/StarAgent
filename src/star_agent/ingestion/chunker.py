"""Split documents into embeddable chunks with citation metadata."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from star_agent.ingestion.sources.base import Document


def content_hash(text: str) -> str:
    """Stable short hash of document text — used to skip unchanged re-embeds."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, Any]


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Greedy paragraph-aware split with character overlap between chunks."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            # carry an overlap tail for context continuity
            current = (current[-overlap:] + "\n\n" + para) if overlap else para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def chunk_document(
    doc: Document,
    retrieved_at: str,
    max_chars: int = 1500,
    overlap: int = 150,
) -> list[Chunk]:
    """Chunk a document, attaching provenance metadata to each piece."""
    # Drop empty / near-empty fragments: they carry no signal and an embedding
    # server rejects a zero-token input (HTTP 400).
    pieces = [p for p in _split_text(doc.text, max_chars, overlap) if len(p.strip()) >= 3]
    single = len(pieces) == 1
    chunks: list[Chunk] = []
    for i, piece in enumerate(pieces):
        chunk_id = doc.id if single else f"{doc.id}::chunk{i}"
        metadata: dict[str, Any] = {
            "source": doc.source,
            "url": doc.url,
            "title": doc.title,
            "patch_version": doc.patch_version or "",
            "retrieved_at": retrieved_at,
            "doc_id": doc.id,
            "chunk_index": i,
            "content_hash": content_hash(doc.text),
        }
        # Chroma metadata values must be str/int/float/bool.
        metadata.update({k: str(v) for k, v in doc.extra.items()})
        chunks.append(Chunk(id=chunk_id, text=piece, metadata=metadata))
    return chunks

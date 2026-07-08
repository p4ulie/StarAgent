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


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    """Split a long string into <=max_chars pieces on word boundaries."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        # A single word longer than max_chars: break it on characters.
        while len(word) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        if current and len(current) + 1 + len(word) > max_chars:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text into chunks that never exceed ``max_chars``.

    Prefers paragraph boundaries; a paragraph longer than ``max_chars`` is
    word-wrapped so no chunk overflows (which would truncate on short-context
    embedders like MiniLM, or 500 on a small embedding-server batch).
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    # Normalize into units no larger than max_chars.
    units: list[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(_hard_wrap(para, max_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) + 2 > max_chars:
            chunks.append(current)
            # Carry an overlap tail for continuity, but never exceed max_chars.
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{unit}" if tail else unit
            while len(current) > max_chars:
                chunks.append(current[:max_chars])
                current = current[max_chars:]
        else:
            current = f"{current}\n\n{unit}" if current else unit
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

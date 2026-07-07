"""Orchestrate the ingestion pipeline: load -> chunk -> embed -> upsert.

Run manually with ``star-agent-ingest`` (or
``python -m star_agent.ingestion.build_index``). Progress bars show fetching,
chunking, and embedding/upserting per source.

Re-runnable: documents use stable, source-scoped ids, so re-running updates the
knowledge base in place (refreshing ``retrieved_at``) instead of duplicating.

MVP registers only the official RSI Ship Matrix. Add more sources by appending
to :data:`SOURCES`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from tqdm import tqdm

from star_agent.config import Settings, get_settings
from star_agent.ingestion.chunker import Chunk, chunk_document
from star_agent.ingestion.loaders import HttpFetcher
from star_agent.ingestion.sources.rsi_ship_matrix import RsiShipMatrixSource
from star_agent.rag.store import VectorStore

logger = logging.getLogger(__name__)

# Registered ingestion sources (MVP: RSI Ship Matrix). Order does not matter.
SOURCES = [RsiShipMatrixSource]

# Upsert in small batches so the embedding progress bar moves smoothly
# (embeddings are computed client-side inside upsert).
_UPSERT_BATCH_SIZE = 32


def _ingest_source(source, store: VectorStore, retrieved_at: str) -> int:
    """Fetch, chunk, and upsert one source. Returns the number of chunks."""
    # 1. Fetch — document count is unknown up front, so this bar just counts up.
    documents = []
    with tqdm(desc=f"[{source.name}] fetching documents", unit="doc") as bar:
        for doc in source.fetch():
            documents.append(doc)
            bar.update(1)

    # 2. Chunk
    chunks: list[Chunk] = []
    for doc in tqdm(documents, desc=f"[{source.name}] chunking", unit="doc"):
        chunks.extend(chunk_document(doc, retrieved_at))

    # 3. Embed + upsert in batches (embedding happens inside upsert)
    with tqdm(
        total=len(chunks), desc=f"[{source.name}] embedding + upserting", unit="chunk"
    ) as bar:
        for start in range(0, len(chunks), _UPSERT_BATCH_SIZE):
            batch = chunks[start : start + _UPSERT_BATCH_SIZE]
            store.upsert(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
            )
            bar.update(len(batch))

    return len(chunks)


def build_index(settings: Settings | None = None) -> dict[str, int]:
    """(Re)build the knowledge base from all registered sources.

    Returns a mapping of source name -> number of chunks upserted. A failing
    source is logged and skipped so one bad source can't abort the whole build.
    """
    settings = settings or get_settings()
    print("Connecting to ChromaDB and loading the embedding model "
          "(first run downloads it — may take a minute)...")
    store = VectorStore(settings)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, int] = {}

    with HttpFetcher(settings) as http:
        for source_cls in SOURCES:
            source = source_cls(http)
            try:
                results[source.name] = _ingest_source(source, store, retrieved_at)
            except Exception:  # noqa: BLE001 — one source must not abort the build
                logger.exception("Source %r failed; skipping", source.name)
                results[source.name] = 0

    return results


def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,  # keep the console clean for the progress bars
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    results = build_index()
    store = VectorStore(get_settings())
    print("\nIngestion complete:")
    for name, n in results.items():
        status = f"{n} chunks" if n else "FAILED (see log above)"
        print(f"  {name}: {status}")
    print(f"Knowledge base now holds {store.count()} documents.")


if __name__ == "__main__":
    main()

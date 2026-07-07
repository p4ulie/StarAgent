"""Orchestrate the ingestion pipeline: load -> chunk -> embed -> upsert.

Re-runnable: documents use stable, source-scoped ids, so re-running updates the
knowledge base in place (refreshing ``retrieved_at``) instead of duplicating.

MVP registers only the official RSI Ship Matrix. Add more sources by appending
to :data:`SOURCES`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from star_agent.config import Settings, get_settings
from star_agent.ingestion.chunker import chunk_document
from star_agent.ingestion.loaders import HttpFetcher
from star_agent.ingestion.sources.rsi_ship_matrix import RsiShipMatrixSource
from star_agent.rag.store import VectorStore

logger = logging.getLogger(__name__)

# Registered ingestion sources (MVP: RSI Ship Matrix). Order does not matter.
SOURCES = [RsiShipMatrixSource]


def build_index(settings: Settings | None = None) -> dict[str, int]:
    """(Re)build the knowledge base from all registered sources.

    Returns a mapping of source name -> number of chunks upserted. A failing
    source is logged and skipped so one bad source can't abort the whole build.
    """
    settings = settings or get_settings()
    store = VectorStore(settings)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, int] = {}

    with HttpFetcher(settings) as http:
        for source_cls in SOURCES:
            source = source_cls(http)
            try:
                documents = list(source.fetch())
            except Exception:  # noqa: BLE001 — one source must not abort the build
                logger.exception("Source %r failed; skipping", source.name)
                results[source.name] = 0
                continue

            ids: list[str] = []
            texts: list[str] = []
            metadatas: list[dict] = []
            for doc in documents:
                for chunk in chunk_document(doc, retrieved_at):
                    ids.append(chunk.id)
                    texts.append(chunk.text)
                    metadatas.append(chunk.metadata)

            store.upsert(ids, texts, metadatas)
            results[source.name] = len(ids)
            logger.info("Indexed %d chunks from %r", len(ids), source.name)

    logger.info("Knowledge base now holds %d documents", store.count())
    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    results = build_index()
    print("Ingestion complete:")
    for name, n in results.items():
        print(f"  {name}: {n} chunks")


if __name__ == "__main__":
    main()

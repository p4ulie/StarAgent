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

import argparse
import logging
from datetime import datetime, timezone

from tqdm import tqdm

from star_agent.config import Settings, get_settings
from star_agent.ingestion.chunker import Chunk, chunk_document
from star_agent.ingestion.loaders import HttpFetcher
from star_agent.ingestion.sources.rsi_ship_matrix import RsiShipMatrixSource
from star_agent.ingestion.sources.star_citizen_wiki import (
    CelestialObjectsSource,
    CommLinksSource,
    GalactapediaSource,
    ItemsSource,
    StarSystemsSource,
    VehiclesSource,
)
from star_agent.ingestion.sources.uex import (
    UexCommoditiesSource,
    UexTradeRoutesSource,
    UexVehiclePricesSource,
)
from star_agent.rag.store import VectorStore

logger = logging.getLogger(__name__)

# Registered ingestion sources, keyed by CLI name.
SOURCES = {
    RsiShipMatrixSource.name: RsiShipMatrixSource,
    GalactapediaSource.name: GalactapediaSource,
    CommLinksSource.name: CommLinksSource,
    StarSystemsSource.name: StarSystemsSource,
    CelestialObjectsSource.name: CelestialObjectsSource,
    VehiclesSource.name: VehiclesSource,
    ItemsSource.name: ItemsSource,
    UexCommoditiesSource.name: UexCommoditiesSource,
    UexVehiclePricesSource.name: UexVehiclePricesSource,
    UexTradeRoutesSource.name: UexTradeRoutesSource,
}

# Upsert in small batches so the embedding progress bar moves smoothly
# (embeddings are computed client-side inside upsert).
_UPSERT_BATCH_SIZE = 32


def _ingest_source(source, store: VectorStore, retrieved_at: str) -> int:
    """Fetch, chunk, and upsert one source. Returns the number of chunks."""
    # 1. Fetch — document count is unknown up front, so this bar just counts up.
    # Dedupe by id: paginated APIs can return the same item on two pages when
    # new content lands mid-crawl and shifts the pages (Chroma rejects
    # duplicate ids within one upsert batch).
    documents = []
    seen_ids: set[str] = set()
    with tqdm(desc=f"[{source.name}] fetching documents", unit="doc") as bar:
        for doc in source.fetch():
            if doc.id in seen_ids:
                continue
            seen_ids.add(doc.id)
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


def build_index(
    settings: Settings | None = None,
    source_names: list[str] | None = None,
    max_docs: int | None = None,
) -> dict[str, int]:
    """(Re)build the knowledge base from the selected sources.

    ``source_names`` selects which registered sources run (default: all).
    ``max_docs`` caps documents per source (default: each source's own cap).
    Returns a mapping of source name -> number of chunks upserted. A failing
    source is logged and skipped so one bad source can't abort the whole build.
    """
    settings = settings or get_settings()
    selected = source_names or list(SOURCES)
    unknown = [n for n in selected if n not in SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s): {unknown}. Available: {list(SOURCES)}")

    print("Connecting to ChromaDB and loading the embedding model "
          "(first run downloads it — may take a minute)...")
    store = VectorStore(settings)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, int] = {}

    with HttpFetcher(settings) as http:
        for name in selected:
            source = SOURCES[name](http, max_docs=max_docs)
            try:
                results[name] = _ingest_source(source, store, retrieved_at)
            except Exception:  # noqa: BLE001 — one source must not abort the build
                logger.exception("Source %r failed; skipping", name)
                results[name] = 0

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="star-agent-ingest",
        description="(Re)build the Star Citizen knowledge base.",
    )
    parser.add_argument(
        "--source",
        "-s",
        action="append",
        choices=sorted(SOURCES),
        help="Source to ingest (repeatable). Default: all sources.",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        metavar="N",
        help="Cap documents per source; 0 = no cap. "
        "Default: each source's own cap (comm_links: 300, others: unlimited).",
    )
    parser.add_argument(
        "--list", action="store_true", help="List available sources and exit."
    )
    args = parser.parse_args()

    if args.list:
        print("Available sources:")
        for name, cls in sorted(SOURCES.items()):
            cap = getattr(cls, "default_max_docs", 0)
            cap_note = f"default cap: {cap} docs" if cap else "no default cap"
            print(f"  {name:<18} {cap_note}")
        return

    logging.basicConfig(
        level=logging.WARNING,  # keep the console clean for the progress bars
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    results = build_index(source_names=args.source, max_docs=args.max_docs)
    store = VectorStore(get_settings())
    print("\nIngestion complete:")
    for name, n in results.items():
        status = f"{n} chunks" if n else "FAILED (see log above)"
        print(f"  {name}: {status}")
    print(f"Knowledge base now holds {store.count()} documents.")


if __name__ == "__main__":
    main()

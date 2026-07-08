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
from star_agent.ingestion.chunker import Chunk, chunk_document, content_hash
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

# Upsert in batches (embeddings are computed client-side inside upsert).
# Larger batches improve ONNX embedding throughput.
_UPSERT_BATCH_SIZE = 128


def _ingest_source(
    source,
    store: VectorStore,
    retrieved_at: str,
    existing_hashes: dict[str, str] | None = None,
    max_chars: int = 1500,
    overlap: int = 150,
) -> int:
    """Fetch, chunk, and upsert one source. Returns the number of chunks.

    Streams document -> chunk -> embed -> upsert so peak memory stays flat
    (only one batch of chunks is held at a time) — important on small hosts.
    Documents whose ``content_hash`` matches what is indexed are skipped, so
    re-runs only embed new or changed content.
    """
    existing_hashes = existing_hashes or {}
    seen_ids: set[str] = set()
    pending: list[Chunk] = []
    unchanged = 0
    total = 0
    skipped = 0

    def flush() -> None:
        nonlocal skipped
        if not pending:
            return
        try:
            store.upsert(
                ids=[c.id for c in pending],
                documents=[c.text for c in pending],
                metadatas=[c.metadata for c in pending],
            )
        except Exception:  # noqa: BLE001 — batch failed; isolate the offenders
            # Retry chunk-by-chunk so one bad input (e.g. too long for the
            # embedding server) doesn't drop the entire batch/source.
            for c in pending:
                try:
                    store.upsert(ids=[c.id], documents=[c.text], metadatas=[c.metadata])
                except Exception as exc:  # noqa: BLE001
                    skipped += 1
                    logger.warning("Skipped chunk %s: %s", c.id, str(exc)[:160])
        pending.clear()

    with tqdm(desc=f"[{source.name}] embed+upsert", unit="chunk") as bar:
        for doc in source.fetch():
            # Dedupe by id: paginated APIs can re-serve an item across pages;
            # Chroma also rejects duplicate ids within one upsert batch.
            if doc.id in seen_ids:
                continue
            seen_ids.add(doc.id)
            if existing_hashes.get(doc.id) == content_hash(doc.text):
                unchanged += 1
                continue
            for chunk in chunk_document(doc, retrieved_at, max_chars, overlap):
                pending.append(chunk)
                total += 1
                if len(pending) >= _UPSERT_BATCH_SIZE:
                    flush()
                    bar.update(_UPSERT_BATCH_SIZE)
        flush()
        bar.update(len(pending))  # no-op after clear, keeps the bar honest

    if unchanged:
        print(f"[{source.name}] {unchanged} unchanged documents skipped")
    if skipped:
        print(f"[{source.name}] {skipped} chunks FAILED to embed (see warnings)")
    return total - skipped


def build_index(
    settings: Settings | None = None,
    source_names: list[str] | None = None,
    max_docs: int | None = None,
    force: bool = False,
) -> dict[str, int]:
    """(Re)build the knowledge base from the selected sources.

    ``source_names`` selects which registered sources run (default: all).
    ``max_docs`` caps documents per source (default: each source's own cap).
    Unchanged documents (matching content hash) are skipped unless ``force``.
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
    existing_hashes = {} if force else store.doc_hashes()
    if existing_hashes:
        print(f"Loaded {len(existing_hashes)} existing document hashes "
              "(unchanged documents will be skipped; --force re-embeds all)")
    results: dict[str, int] = {}

    with HttpFetcher(settings) as http:
        for name in selected:
            source = SOURCES[name](http, max_docs=max_docs)
            try:
                results[name] = _ingest_source(
                    source,
                    store,
                    retrieved_at,
                    existing_hashes,
                    max_chars=settings.chunk_max_chars,
                    overlap=settings.chunk_overlap,
                )
            except Exception:  # noqa: BLE001 — one source must not abort the build
                logger.exception("Source %r failed; skipping", name)
                results[name] = -1  # sentinel: failure (0 = all docs unchanged)

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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed everything, ignoring stored content hashes.",
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
    results = build_index(
        source_names=args.source, max_docs=args.max_docs, force=args.force
    )
    store = VectorStore(get_settings())
    print("\nIngestion complete:")
    for name, n in results.items():
        if n < 0:
            status = "FAILED (see log above)"
        elif n == 0:
            status = "up to date (all documents unchanged)"
        else:
            status = f"{n} chunks"
        print(f"  {name}: {status}")
    print(f"Knowledge base now holds {store.count()} documents.")


if __name__ == "__main__":
    main()

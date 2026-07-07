"""Star Citizen Wiki API sources (api.star-citizen.wiki).

Community REST mirror of official content — the re-runnable JSON path for
Galactapedia (official lore) and Comm-Link (news/patch notes), which on RSI's
own site are an SPA / HTML only. Keyless reads, Laravel-style pagination via
``links.next``; full English text arrives in ``translations.en_EN``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import Any

from star_agent.ingestion.loaders import HttpFetcher
from star_agent.ingestion.sources.base import Document

logger = logging.getLogger(__name__)

_API_BASE = "https://api.star-citizen.wiki/api/v2"
_RSI_BASE = "https://robertsspaceindustries.com"

# Galactapedia articles not yet transcribed carry this placeholder.
_PENDING_MARKER = "Pending review by the Ark research team"


def _english_text(item: dict[str, Any]) -> str:
    translations = item.get("translations")
    if isinstance(translations, dict):
        return str(translations.get("en_EN") or "").strip()
    return ""


_PER_PAGE = 30


def _page_url(endpoint: str, page: int) -> str:
    return f"{endpoint}?limit={_PER_PAGE}&page%5Bnumber%5D={page}"


def _paginate(http: HttpFetcher, endpoint: str, max_docs: int) -> Iterator[dict[str, Any]]:
    """Yield items across pages until exhausted or ``max_docs`` reached.

    Pages are addressed explicitly (``page[number]=N`` up to ``meta.last_page``).
    Do NOT follow ``links.next``: the API appends a new ``page[number]`` param on
    every hop instead of replacing it, and after ~10 hops the crawl silently
    loops back to earlier pages, re-serving the same articles.

    Page 1 is fetched alone to learn ``last_page``; the remaining pages are
    fetched concurrently (order-preserving) via :meth:`HttpFetcher.get_json_many`.
    """
    yielded = 0

    def _emit(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        nonlocal yielded
        for item in payload.get("data") or []:
            if isinstance(item, dict):
                yield item
                yielded += 1
                if max_docs and yielded >= max_docs:
                    return

    first = http.get_json(_page_url(endpoint, 1))
    yield from _emit(first)
    if max_docs and yielded >= max_docs:
        return

    last_page = int((first.get("meta") or {}).get("last_page") or 1)
    if max_docs:
        # No point fetching pages past the cap.
        last_page = min(last_page, -(-max_docs // _PER_PAGE))

    # Fetch remaining pages in chunks so results stream instead of buffering
    # the entire crawl in memory.
    batch = 8
    for start in range(2, last_page + 1, batch):
        pages = range(start, min(start + batch, last_page + 1))
        for payload in http.get_json_many([_page_url(endpoint, p) for p in pages]):
            yield from _emit(payload)
            if max_docs and yielded >= max_docs:
                return


class GalactapediaSource:
    """Official lore articles (Galactapedia) via the community API mirror."""

    name = "galactapedia"
    default_max_docs = 0  # no cap (~1,500 articles)

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs

    def fetch(self) -> Iterable[Document]:
        skipped = 0
        for item in _paginate(
            self._http, f"{_API_BASE}/galactapedia", self._max_docs
        ):
            text = _english_text(item)
            title = str(item.get("title") or "").strip()
            article_id = str(item.get("id") or "").strip()
            if not article_id or not title or not text or _PENDING_MARKER in text:
                skipped += 1
                continue
            rsi_url = str(item.get("rsi_url") or "")
            categories = ", ".join(
                str(c.get("name")) for c in item.get("categories") or [] if c.get("name")
            )
            body = f"{title}" + (f" ({categories})" if categories else "") + f"\n\n{text}"
            yield Document(
                id=f"galactapedia::{article_id}",
                title=title,
                url=f"{_RSI_BASE}{rsi_url}" if rsi_url.startswith("/") else rsi_url,
                source="RSI Galactapedia",
                text=body,
                extra={"categories": categories} if categories else {},
            )
        if skipped:
            logger.info("Galactapedia: skipped %d empty/pending articles", skipped)


class StarSystemsSource:
    """Star systems (name, type, lore description) via the community API."""

    name = "starsystems"
    default_max_docs = 0  # ~100 systems

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs

    def fetch(self) -> Iterable[Document]:
        for item in _paginate(self._http, f"{_API_BASE}/starsystems", self._max_docs):
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            if not code or not name:
                continue
            desc = ""
            if isinstance(item.get("description"), dict):
                desc = str(item["description"].get("en_EN") or "").strip()
            facts = [
                f"Star system: {name}",
                f"Type: {item.get('type') or 'unknown'}",
            ]
            text = "\n".join(facts) + (f"\n\n{desc}" if desc else "")
            yield Document(
                id=f"starsystem::{code}",
                title=f"{name} system",
                url=str(item.get("web_url") or ""),
                source="Starmap (star system)",
                text=text,
            )


class CelestialObjectsSource:
    """Planets, moons, and stations with lore descriptions via the community API."""

    name = "celestial_objects"
    default_max_docs = 0

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs

    def fetch(self) -> Iterable[Document]:
        skipped = 0
        for item in _paginate(
            self._http, f"{_API_BASE}/celestial-objects", self._max_docs
        ):
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            desc = ""
            if isinstance(item.get("description"), dict):
                desc = str(item["description"].get("en_EN") or "").strip()
            # Objects without prose are bare coordinates — no retrieval value.
            if not code or not name or not desc:
                skipped += 1
                continue
            designation = str(item.get("designation") or "").strip()
            facts = [f"{name}" + (f" ({designation})" if designation else "")]
            if item.get("type"):
                facts.append(f"Type: {item['type']}")
            if item.get("habitable") is not None:
                facts.append(f"Habitable: {'yes' if item['habitable'] else 'no'}")
            yield Document(
                id=f"celestial::{code}",
                title=name,
                url=str(item.get("web_url") or ""),
                source="Starmap (celestial object)",
                text="\n".join(facts) + f"\n\n{desc}",
            )
        if skipped:
            logger.info("Celestial objects: skipped %d without descriptions", skipped)


class VehiclesSource:
    """In-game vehicle data (game-file extract) via the community API.

    Complements the RSI Ship Matrix with live-patch stats and the in-game
    description text.
    """

    name = "vehicles"
    default_max_docs = 0  # ~290 vehicles

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs

    def fetch(self) -> Iterable[Document]:
        for item in _paginate(self._http, f"{_API_BASE}/vehicles", self._max_docs):
            name = str(item.get("name") or "").strip()
            key = str(item.get("class_name") or item.get("id") or "").strip()
            if not name or not key:
                continue
            crew = item.get("crew") or {}
            facts: list[str] = [f"Vehicle: {name}"]
            if item.get("career"):
                facts.append(f"Career: {item['career']}")
            if item.get("cargo_capacity") is not None:
                facts.append(f"Cargo capacity (SCU): {item['cargo_capacity']}")
            if isinstance(crew, dict) and crew.get("min") is not None:
                facts.append(f"Crew: {crew.get('min')}–{crew.get('max')}")
            desc = str(
                item.get("game_description") or item.get("description") or ""
            ).strip()
            yield Document(
                id=f"vehicle::{key}",
                title=name,
                url=str(item.get("link") or ""),
                source="Game data (vehicle)",
                text="\n".join(facts) + (f"\n\n{desc}" if desc else ""),
            )


class ItemsSource:
    """Ship components & FPS items (game-file extract) via the community API.

    Skips cosmetic paints and description-less entries — of ~12,000 raw items
    only those with prose are worth retrieval.
    """

    name = "items"
    default_max_docs = 0

    _SKIP_CLASSIFICATIONS = {"Paints"}

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs

    def fetch(self) -> Iterable[Document]:
        skipped = 0
        for item in _paginate(self._http, f"{_API_BASE}/items", self._max_docs):
            name = str(item.get("name") or "").strip()
            key = str(item.get("class_name") or "").strip()
            desc = str(item.get("description") or "").strip()
            label = str(item.get("classification_label") or "").strip()
            if not name or not key or not desc or label in self._SKIP_CLASSIFICATIONS:
                skipped += 1
                continue
            manufacturer = item.get("manufacturer")
            if isinstance(manufacturer, dict):
                manufacturer = manufacturer.get("name")
            facts = [f"Item: {name}"]
            if label:
                facts.append(f"Category: {label}")
            if manufacturer:
                facts.append(f"Manufacturer: {manufacturer}")
            if item.get("size") is not None:
                facts.append(f"Size: {item['size']}")
            if item.get("grade") is not None:
                facts.append(f"Grade: {item['grade']}")
            yield Document(
                id=f"item::{key}",
                title=name,
                url=str(item.get("link") or ""),
                source="Game data (item)",
                text="\n".join(facts) + f"\n\n{desc}",
                extra={"classification": label} if label else {},
            )
        if skipped:
            logger.info("Items: skipped %d paints/description-less entries", skipped)


class CommLinksSource:
    """Official news posts (Comm-Link) via the community API mirror.

    Newest first; capped by default — there are ~6,000 posts going back years,
    and the recent ones carry the patch-relevant information.
    """

    name = "comm_links"
    default_max_docs = 300

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs

    def fetch(self) -> Iterable[Document]:
        for item in _paginate(
            self._http, f"{_API_BASE}/comm-links", self._max_docs
        ):
            text = _english_text(item)
            title = str(item.get("title") or "").strip()
            post_id = item.get("id")
            if post_id is None or not title or not text:
                continue
            channel = str(item.get("channel") or "").strip()
            header = f"{title}" + (f" [{channel}]" if channel else "")
            yield Document(
                id=f"comm-link::{post_id}",
                title=title,
                url=str(item.get("rsi_url") or ""),
                source="RSI Comm-Link",
                text=f"{header}\n\n{text}",
                extra={"channel": channel} if channel else {},
            )

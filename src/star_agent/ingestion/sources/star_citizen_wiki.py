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


def _paginate(http: HttpFetcher, url: str, max_docs: int) -> Iterator[dict[str, Any]]:
    """Yield items across pages until exhausted or ``max_docs`` reached."""
    yielded = 0
    while url:
        payload = http.get_json(url)
        for item in payload.get("data") or []:
            if isinstance(item, dict):
                yield item
                yielded += 1
                if max_docs and yielded >= max_docs:
                    return
        url = (payload.get("links") or {}).get("next")


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
            self._http, f"{_API_BASE}/galactapedia?limit=30", self._max_docs
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
            self._http, f"{_API_BASE}/comm-links?limit=30", self._max_docs
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

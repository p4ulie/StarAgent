"""HTTP fetching for the ingestion pipeline.

A small synchronous fetcher (ingestion is a batch job, not the bot event loop)
that always sends a descriptive User-Agent and rate-limits between requests.
Several Star Citizen sources sit behind Cloudflare and reject anonymous
fetches, so identifying ourselves and being polite is mandatory.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from star_agent.config import Settings

logger = logging.getLogger(__name__)


class HttpFetcher:
    """Rate-limited, thread-safe HTTP client with a real User-Agent."""

    def __init__(self, settings: Settings) -> None:
        self._delay = settings.ingest_rate_delay
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.ingest_user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def _throttle(self, spacing: float | None = None) -> None:
        """Enforce a minimum interval between request starts (thread-safe)."""
        spacing = self._delay if spacing is None else spacing
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < spacing:
                time.sleep(spacing - elapsed)
            self._last_request = time.monotonic()

    def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        _spacing: float | None = None,
    ) -> Any:
        self._throttle(_spacing)
        logger.debug("GET (json) %s", url)
        resp = self._client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_json_many(
        self,
        urls: list[str],
        headers: dict[str, str] | None = None,
        workers: int = 4,
    ) -> list[Any]:
        """Fetch several URLs concurrently, preserving order.

        Request starts stay globally spaced at ``delay / workers`` (~4 req/s
        at defaults) — parallelism overlaps response latency while remaining
        polite to community APIs.
        """
        if not urls:
            return []
        spacing = self._delay / max(workers, 1)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(self.get_json, url, headers, spacing) for url in urls
            ]
            return [f.result() for f in futures]

    def get_text(self, url: str) -> str:
        self._throttle()
        logger.debug("GET (text) %s", url)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

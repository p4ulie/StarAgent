"""HTTP fetching for the ingestion pipeline.

A small synchronous fetcher (ingestion is a batch job, not the bot event loop)
that always sends a descriptive User-Agent and rate-limits between requests.
Several Star Citizen sources sit behind Cloudflare and reject anonymous
fetches, so identifying ourselves and being polite is mandatory.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from star_agent.config import Settings

logger = logging.getLogger(__name__)


class HttpFetcher:
    """Rate-limited HTTP client with a real User-Agent."""

    def __init__(self, settings: Settings) -> None:
        self._delay = settings.ingest_rate_delay
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.ingest_user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request = time.monotonic()

    def get_json(self, url: str) -> Any:
        self._throttle()
        logger.debug("GET (json) %s", url)
        resp = self._client.get(url)
        resp.raise_for_status()
        return resp.json()

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

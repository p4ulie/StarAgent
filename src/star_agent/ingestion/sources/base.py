"""Shared types for ingestion sources."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from star_agent.ingestion.loaders import HttpFetcher


@dataclass(slots=True)
class Document:
    """A single knowledge-base document before chunking.

    ``id`` must be **stable** across runs (source-scoped) so re-ingestion
    upserts in place instead of duplicating.
    """

    id: str
    title: str
    url: str
    source: str
    text: str
    patch_version: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Source(Protocol):
    """A data source that yields documents for the knowledge base."""

    name: str

    def __init__(self, http: HttpFetcher) -> None: ...

    def fetch(self) -> Iterable[Document]: ...

"""The RAG retrieval tool exposed to the ADK agent.

ADK derives the tool schema from this function's signature and docstring, so the
signature stays clean (``query: str``) and the retriever is injected via
:func:`configure` at startup rather than passed as a parameter.
"""

from __future__ import annotations

import asyncio
import logging

from star_agent.rag.retriever import Retriever

logger = logging.getLogger(__name__)

_retriever: Retriever | None = None
_n_results: int = 5


def configure(retriever: Retriever, n_results: int = 5) -> None:
    """Wire the shared retriever the tool will use. Called once at startup."""
    global _retriever, _n_results
    _retriever = retriever
    _n_results = n_results


async def search_star_citizen_kb(query: str) -> dict:
    """Search the Star Citizen knowledge base for information.

    Call this for any question about Star Citizen: ships and their specs,
    components/items, locations, lore, factions, or gameplay. Returns the most
    relevant passages with their source titles and URLs so you can cite them.

    Args:
        query: The user's question or search terms about Star Citizen.

    Returns:
        A dict with ``status`` ("success" or "error") and, on success, a
        ``results`` list of passages, each with ``text``, ``title``, ``url``,
        ``source``, and a relevance ``score``.
    """
    if _retriever is None:
        return {"status": "error", "error": "Knowledge base is not configured."}
    try:
        # Chroma query is blocking network I/O — keep the event loop free.
        chunks = await asyncio.to_thread(_retriever.retrieve, query, _n_results)
    except Exception as exc:  # noqa: BLE001 — surface as a tool error to the model
        logger.exception("Knowledge-base search failed")
        return {"status": "error", "error": f"Search failed: {exc}"}

    return {
        "status": "success",
        "results": [
            {
                "text": c.text,
                "title": c.title,
                "url": c.url,
                "source": c.source,
                "score": c.score,
            }
            for c in chunks
        ],
    }

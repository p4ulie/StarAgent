"""MCP server exposing the Star Citizen knowledge base.

Serves two tools to any MCP client (Claude Desktop, IDEs, other agents):

- ``search_star_citizen_kb`` — raw retrieval: relevant passages + sources.
- ``ask`` — the full StarAgent RAG agent answers a question.

Both reuse the same ``agent``/``rag`` core as the Discord bot.
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server.fastmcp import FastMCP

from star_agent.agent.service import AgentService
from star_agent.config import Settings, get_settings
from star_agent.rag.retriever import Retriever
from star_agent.rag.store import VectorStore

logger = logging.getLogger(__name__)


def build_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or get_settings()
    store = VectorStore(settings)
    retriever = Retriever(store)
    agent_service = AgentService(settings, retriever)

    server = FastMCP("StarAgent", host=settings.mcp_host, port=settings.mcp_port)

    @server.tool()
    async def search_star_citizen_kb(query: str) -> str:
        """Search the Star Citizen knowledge base.

        Returns the most relevant passages with their source titles and URLs.
        Use for ships, components, locations, lore, factions, and gameplay.
        """
        chunks = await asyncio.to_thread(retriever.retrieve, query, 5)
        return Retriever.format_context(chunks)

    @server.tool()
    async def ask(question: str) -> str:
        """Answer a Star Citizen question using the StarAgent RAG agent.

        Retrieves relevant knowledge and generates a grounded, cited answer.
        """
        return await agent_service.answer(question, user_id="mcp", session_id="mcp")

    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = build_server()
    logger.info("Starting StarAgent MCP server (SSE transport)")
    server.run(transport="sse")


if __name__ == "__main__":
    main()

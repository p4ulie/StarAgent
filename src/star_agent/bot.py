"""Discord bot wiring.

The bot is a thin transport: it builds the shared knowledge-base store and
agent service once in ``setup_hook``, loads the command cogs, and syncs slash
commands. All real work happens in the ``agent``/``rag`` layers.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from star_agent.agent.service import AgentService
from star_agent.config import Settings
from star_agent.rag.retriever import Retriever
from star_agent.rag.store import VectorStore

logger = logging.getLogger(__name__)

_EXTENSIONS = ["star_agent.cogs.ask", "star_agent.cogs.admin"]

# Liveness heartbeat: a background task touches this file on an interval so the
# container healthcheck can tell the event loop is still turning. If the loop
# wedges (a blocking call, a deadlock), the file goes stale and the check fails.
HEARTBEAT_FILE = Path("/tmp/star_agent.heartbeat")
_HEARTBEAT_INTERVAL = 15.0  # seconds; healthcheck staleness threshold is higher


class StarAgentBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        # Slash commands don't need the privileged message_content intent.
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.settings = settings
        self.store: VectorStore | None = None
        self.agent_service: AgentService | None = None

    async def setup_hook(self) -> None:
        # VectorStore init connects to Chroma and loads the local embedding
        # model — offload the blocking work so startup doesn't stall the loop.
        self.store = await asyncio.to_thread(VectorStore, self.settings)
        self.agent_service = AgentService(self.settings, Retriever(self.store))

        for ext in _EXTENSIONS:
            await self.load_extension(ext)

        # Warm the LLM in the background so the first /ask doesn't pay the
        # model's cold-load. Non-blocking: startup continues regardless.
        self.loop.create_task(self._warmup())
        self.loop.create_task(self._heartbeat())

        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced commands to guild %s", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("Synced global commands (may take up to ~1h to propagate)")

    async def _warmup(self) -> None:
        if self.agent_service is None:
            return
        try:
            await self.agent_service.answer("ping", user_id="warmup", session_id="warmup")
            logger.info("LLM warmup complete")
        except Exception as exc:  # noqa: BLE001 — warmup is best-effort
            logger.warning("LLM warmup failed (model may be cold on first query): %s", exc)

    async def _heartbeat(self) -> None:
        """Touch HEARTBEAT_FILE on a fixed interval for the container healthcheck.

        Runs on the event loop, so a wedged loop stops the updates and the
        file's mtime goes stale — that's exactly the hang the check detects.
        """
        while True:
            HEARTBEAT_FILE.touch()
            await asyncio.sleep(_HEARTBEAT_INTERVAL)

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id: %s)", self.user, getattr(self.user, "id", "?"))

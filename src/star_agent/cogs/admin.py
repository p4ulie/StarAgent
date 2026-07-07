"""Admin slash commands: /health and /reindex."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from star_agent.ingestion.build_index import build_index

logger = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="health", description="Show StarAgent status")
    async def health(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        store = getattr(self.bot, "store", None)
        if store is None:
            await interaction.followup.send("Knowledge base is not ready yet.")
            return
        try:
            count = await asyncio.to_thread(store.count)
        except Exception:
            logger.exception("Health check failed")
            await interaction.followup.send("⚠️ Could not reach the knowledge base (Chroma).")
            return
        await interaction.followup.send(
            f"✅ Knowledge base online — {count} documents indexed."
        )

    @app_commands.command(
        name="reindex", description="Rebuild the Star Citizen knowledge base"
    )
    @app_commands.default_permissions(administrator=True)
    async def reindex(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            # Ingestion is blocking (HTTP + embedding) — run off the event loop.
            results = await asyncio.to_thread(build_index, self.bot.settings)
        except Exception:
            logger.exception("Reindex failed")
            await interaction.followup.send("⚠️ Reindex failed — check the logs.")
            return
        summary = "\n".join(f"• {name}: {n} chunks" for name, n in results.items())
        await interaction.followup.send(f"✅ Reindex complete:\n{summary or 'no sources'}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))

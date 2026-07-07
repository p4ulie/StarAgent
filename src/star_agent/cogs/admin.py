"""Admin slash commands.

Note: knowledge-base (re)indexing is deliberately NOT a Discord command. A full
run takes 15+ minutes — past Discord's 15-minute interaction-token lifetime —
and local embedding would hog the bot container's CPU, degrading /ask for
everyone. Run it as the manual CLI instead:

    docker compose run --rm bot star-agent-ingest
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))

"""The /ask slash command."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

_DISCORD_MSG_LIMIT = 2000


class AskCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="ask", description="Ask a question about Star Citizen"
    )
    @app_commands.describe(question="Your question about Star Citizen")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        # A RAG + LLM call takes longer than Discord's 3s ack window, so defer
        # immediately, then deliver the answer with followup.send().
        await interaction.response.defer(thinking=True)

        service = getattr(self.bot, "agent_service", None)
        if service is None:
            await interaction.followup.send(
                "The agent is still starting up — please try again in a moment."
            )
            return

        try:
            answer = await service.answer(
                question,
                user_id=str(interaction.user.id),
                session_id=f"{interaction.channel_id}:{interaction.user.id}",
            )
        except Exception:
            logger.exception("Failed to answer question")
            answer = "Sorry — something went wrong answering that. Please try again."

        answer = answer.strip() or "I couldn't find an answer to that."
        if len(answer) > _DISCORD_MSG_LIMIT:
            answer = answer[: _DISCORD_MSG_LIMIT - 1] + "…"
        await interaction.followup.send(answer)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskCog(bot))

"""The /ask slash command."""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

_DISCORD_MSG_LIMIT = 2000
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _row_cells(row: str) -> list[str]:
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [c.strip() for c in row.split("|")]


def _render_table(rows: list[str]) -> str:
    """Render markdown table rows as an aligned monospace code block."""
    grid = [_row_cells(r) for r in rows]
    ncol = max(len(r) for r in grid)
    grid = [r + [""] * (ncol - len(r)) for r in grid]
    widths = [max(len(r[c]) for r in grid) for c in range(ncol)]
    lines = ["  ".join(r[c].ljust(widths[c]) for c in range(ncol)).rstrip() for r in grid]
    return "```\n" + "\n".join(lines) + "\n```"


def _tables_to_code_blocks(text: str) -> str:
    """Convert markdown tables to code blocks — Discord can't render tables."""
    lines = text.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        is_header = "|" in lines[i]
        has_sep = i + 1 < n and _SEPARATOR_RE.match(lines[i + 1]) and "-" in lines[i + 1]
        if is_header and has_sep:
            header = lines[i]
            k = i + 2
            body: list[str] = []
            while k < n and lines[k].strip() and "|" in lines[k]:
                body.append(lines[k])
                k += 1
            out.append(_render_table([header, *body]))
            i = k
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


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

        answer = _tables_to_code_blocks(answer.strip()) or "I couldn't find an answer to that."
        if len(answer) > _DISCORD_MSG_LIMIT:
            answer = answer[: _DISCORD_MSG_LIMIT - 1] + "…"
        await interaction.followup.send(answer)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskCog(bot))

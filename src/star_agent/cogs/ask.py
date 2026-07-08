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


def _split_for_discord(text: str, limit: int = 1990) -> list[str]:
    """Split text into <=limit-char messages, keeping code blocks balanced."""
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    in_code = False

    def flush() -> None:
        nonlocal cur, cur_len
        if not cur:
            return
        body = "\n".join(cur)
        if in_code:
            body += "\n```"  # close an open fence so the message is valid
        chunks.append(body)
        cur, cur_len = [], 0

    for raw in text.split("\n"):
        # Hard-wrap a pathologically long single line.
        for line in ([raw] if len(raw) <= limit else
                     [raw[i:i + limit] for i in range(0, len(raw), limit)]):
            reserve = 4 if in_code else 0
            if cur and cur_len + len(line) + 1 + reserve > limit:
                reopen = in_code
                flush()
                if reopen:
                    cur.append("```")
                    cur_len += 4
            cur.append(line)
            cur_len += len(line) + 1
            if line.lstrip().startswith("```"):
                in_code = not in_code
    flush()
    return chunks or [""]


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
        parts = _split_for_discord(answer)
        # Cap at a few messages so a runaway answer can't spam the channel.
        if len(parts) > 5:
            parts = parts[:5]
            parts[-1] += "\n… (truncated)"
        for part in parts:
            await interaction.followup.send(part)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskCog(bot))

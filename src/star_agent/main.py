"""Entrypoint for the Discord bot (``star-agent-bot``)."""

from __future__ import annotations

import logging

from star_agent.bot import StarAgentBot
from star_agent.config import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    token = settings.require_discord_token()  # fails fast with a clear message
    bot = StarAgentBot(settings)
    bot.run(token)


if __name__ == "__main__":
    main()

"""Typed configuration loaded from environment / .env.

The only real secret is ``DISCORD_TOKEN``. Everything else is host/config wiring.
See ``.env.example`` for documentation of each variable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Discord ---
    discord_token: str = Field(default="", description="Discord bot token (required to run the bot)")
    discord_guild_id: int | None = Field(
        default=None, description="Optional guild id for instant slash-command sync during dev"
    )

    # --- LLM (external llama.cpp, OpenAI-compatible) ---
    llm_base_url: str = "http://host.docker.internal:8080/v1"
    llm_model: str = "llama.cpp"
    llm_timeout: float = 120.0

    # --- ChromaDB ---
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_collection: str = "star_citizen"

    # --- Ingestion ---
    ingest_user_agent: str = "StarAgent/0.1 (+https://github.com/p4ulie/StarAgent)"
    ingest_rate_delay: float = 1.0

    # --- MCP server ---
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8765

    # --- Optional data-source keys (not needed for MVP) ---
    uex_api_token: str | None = None
    starcitizen_api_key: str | None = None

    @field_validator(
        "discord_guild_id", "uex_api_token", "starcitizen_api_key", mode="before"
    )
    @classmethod
    def _blank_env_is_unset(cls, v: object) -> object:
        """Treat empty strings (e.g. `DISCORD_GUILD_ID=` in .env) as unset."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    def require_discord_token(self) -> str:
        """Return the Discord token or fail fast with a clear message."""
        if not self.discord_token:
            raise RuntimeError(
                "DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token."
            )
        return self.discord_token


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()

# Single image for the Discord bot, the MCP server, and ingestion.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the package (dependency resolution is the slow layer; keep it cached
# by copying metadata first).
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# Run as a non-root user; HOME is writable for the local embedding-model cache.
RUN useradd --create-home app && chown -R app:app /app
USER app

# Default entrypoint is the Discord bot; compose overrides it for the MCP server
# and for one-off ingestion (`... run --rm bot star-agent-ingest`).
CMD ["star-agent-bot"]

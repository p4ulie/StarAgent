# Single image for the Discord bot, the MCP server, and ingestion.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies against a stub package first, so this heavy layer stays
# cached until pyproject.toml changes. Code edits then only re-run the fast
# --no-deps package install below, instead of reinstalling the whole dep tree.
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p src/star_agent && touch src/star_agent/__init__.py \
    && pip install --upgrade pip && pip install .

# Now install the real package (fast — dependencies are already present).
COPY src ./src
RUN pip install --no-deps --force-reinstall .

# Run as a non-root user; HOME is writable for the local embedding-model cache.
# A numeric UID, because Kubernetes' runAsNonRoot can only verify a number.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /home/app/.cache \
    && chown -R app:app /app /home/app/.cache
USER 10001

# Bake the local MiniLM embedding model (~80 MB) into the image, so a pod needs neither a cache volume nor
# network access to download it on first use.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as E; E()(['warm-up'])"

# Default entrypoint is the Discord bot; compose overrides it for the MCP server
# and for one-off ingestion (`... run --rm bot star-agent-ingest`).
CMD ["star-agent-bot"]

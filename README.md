# StarAgent

Knowledge base agent for **Star Citizen** — a Discord bot **and** MCP server that answers
questions about the game using a Retrieval-Augmented Generation (RAG) system over a scraped,
continuously updatable knowledge base.

> ### ⚠️ Copyright & ownership
> StarAgent is an **unofficial fan project**. It is **not affiliated with, authorized, or endorsed
> by Cloud Imperium Games (CIG) or Roberts Space Industries (RSI)**.
>
> **Cloud Imperium Games / Roberts Space Industries is the sole owner of all copyright, trademarks,
> and intellectual property in *Star Citizen*, *Squadron 42*, and everything related to them.**
> StarAgent claims no ownership of any of that content; it only indexes publicly available
> information to answer questions. All game names, artwork, lore, and data belong to their owner.

## How it works

```
Discord user ──/ask──▶ discord.py (cogs) ┐
                                          │  two thin transports, one shared core
MCP client   ──tool──▶ MCP server        ┘
                          ▼
                     ADK AgentService (Google Agent Development Kit)
                          ▼
                     RAG retriever ──▶ ChromaDB  (local MiniLM embeddings)
                          ▼
                     your llama.cpp server (via LiteLlm) writes the grounded answer

  ingestion pipeline ──scrape/pull──▶ chunk + embed ──▶ ChromaDB   (run to (re)build the KB)
```

- **Fully self-hosted / offline.** Embeddings run locally (ChromaDB's `all-MiniLM-L6-v2`); the LLM
  is **your own external llama.cpp server** (OpenAI-compatible), pointed to by `LLM_BASE_URL`.
- **The only secret is `DISCORD_TOKEN`.** Nothing sensitive is committed — see `.env.example`.
- **Updatable knowledge base.** The ingestion pipeline is re-runnable so the KB tracks game patches.

## Quick start

1. **Run a llama.cpp server** (OpenAI-compatible), e.g. `llama-server -m model.gguf --port 8080`.
2. `cp .env.example .env` and set `DISCORD_TOKEN` (and `LLM_BASE_URL` if not the default).
3. `docker compose up --build` — starts ChromaDB, the Discord bot, and the MCP server.
4. Build the knowledge base: `docker compose run --rm bot star-agent-ingest`.
5. In Discord, run `/ask question:<your Star Citizen question>`.

Local dev without Docker: `pip install -e .[dev]`, run a local Chroma (`CHROMA_HOST=localhost`),
then `star-agent-bot` / `star-agent-mcp` / `star-agent-ingest`.

## Data sources

The knowledge base is built by scraping/pulling from the sources below. The MVP ingests the
**official RSI site** first; other sources are added incrementally. The full verified list —
with URLs, access method (API vs. scraping), and terms/rate-limit notes — is in
**[`docs/data-sources.md`](docs/data-sources.md)**.

- **Official (CIG / RSI):** [Ship Matrix](https://robertsspaceindustries.com/ship-matrix),
  [Galactapedia](https://robertsspaceindustries.com/galactapedia),
  [Comm-Link](https://robertsspaceindustries.com/comm-link),
  [Starmap](https://robertsspaceindustries.com/starmap)
- **Community wikis:** [Star Citizen Wiki](https://starcitizen.tools) (+ its
  [REST API](https://api.star-citizen.wiki)), [Fandom wiki](https://starcitizen.fandom.com)
- **Item / ship data:** [scunpacked](https://scunpacked.com) & GitHub game-data dumps,
  [Universal Item Finder](https://finder.cstone.space), [Erkul](https://www.erkul.games)
- **Trade / economy (planned, not in MVP):** [UEX](https://uexcorp.space),
  [SC Trade Tools](https://sc-trade.tools)

Community wikis are unofficial fansites; their content is licensed CC BY-NC-SA / CC BY-SA
(attribution + non-commercial). Respect each source's terms of service and `robots.txt`.

## License

The StarAgent **source code** is licensed under the [MIT License](LICENSE). This license covers
only the code in this repository — **not** any Star Citizen content, which remains the property of
Cloud Imperium Games / Roberts Space Industries (see the notice above).

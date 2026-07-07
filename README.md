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
2. **Set up the Discord bot** (see [Discord setup](#discord-setup) below) to get your bot token.
3. `cp .env.example .env` and set `DISCORD_TOKEN` (and `LLM_BASE_URL` if not the default).
4. `docker compose up --build` — starts ChromaDB, the Discord bot, and the MCP server.
5. Build the knowledge base: `docker compose run --rm bot star-agent-ingest`.
6. In Discord, run `/ask question:<your Star Citizen question>`.

Local dev without Docker: `pip install -e .[dev]`, run a local Chroma (`CHROMA_HOST=localhost`),
then `star-agent-bot` / `star-agent-mcp` / `star-agent-ingest`.

## Discord setup

How to create the bot and add it to your server:

1. **Create the application.** Go to the
   [Discord Developer Portal](https://discord.com/developers/applications), sign in, click
   **New Application**, and give it a name (e.g. *StarAgent*).

2. **Get the bot token.** In your application, open the **Bot** tab and click
   **Reset Token** → copy the token shown (it is displayed only once). Put it in your `.env` as
   `DISCORD_TOKEN=...`. **Treat the token like a password** — anyone who has it controls your
   bot. Never commit it; if it ever leaks, reset it immediately on the same page.

3. **Intents.** StarAgent only uses slash commands, so **no privileged gateway intents are
   needed** — leave *Presence*, *Server Members*, and *Message Content* switched **off** on the
   Bot tab (this also avoids Discord's verification requirements later).

4. **Build the invite URL.** Open **OAuth2 → URL Generator** and select:
   - **Scopes:** `bot` **and** `applications.commands` (the second one is required for slash
     commands to appear).
   - **Bot permissions:** `Send Messages`, `Embed Links`, and (if you'll use it in threads)
     `Send Messages in Threads`. Nothing else is needed.

   Copy the generated URL at the bottom. It looks like:
   `https://discord.com/oauth2/authorize?client_id=<APP_ID>&permissions=<...>&scope=bot+applications.commands`

5. **Invite the bot.** Open that URL in your browser, pick your server from the dropdown
   (you need **Manage Server** permission there), and click **Authorize**. The bot appears in
   the member list — offline until you start it.

6. **(Recommended for development) instant command sync.** Enable **Developer Mode** in your
   Discord client (*User Settings → Advanced*), right-click your server icon → **Copy Server
   ID**, and set it in `.env` as `DISCORD_GUILD_ID=...`. Commands sync to that server instantly;
   without it, global commands can take up to ~1 hour to appear.

7. **Start the bot** (`docker compose up -d bot`) and type `/ask` in your server. Available
   commands: `/ask` (ask a Star Citizen question) and `/health` (knowledge-base status).

### Running on multiple Discord servers

One bot process serves any number of servers (Discord allows up to **100** per bot before
requiring [bot verification](https://support-dev.discord.com/hc/en-us/articles/23926564536471);
StarAgent needs no privileged intents, which keeps verification simple if you ever get there).

- **Invite:** reuse the same OAuth2 invite URL (step 4 above) on each server — whoever has
  *Manage Server* there opens it and authorizes.
- **Command sync:** leave `DISCORD_GUILD_ID` **empty** in `.env` for multi-server use. Commands
  then register **globally** — every server gets them (first registration can take up to ~1 hour
  to propagate; servers joined later see them immediately). Setting `DISCORD_GUILD_ID` restricts
  instant command sync to that one guild — useful during development, wrong for multi-server.
- **Isolation:** conversation memory is keyed by `channel:user`, so users on different servers
  never share context. The knowledge base itself is shared — every server gets the same answers.
- **Capacity:** all servers share your single llama.cpp instance. The bot allows 4 concurrent
  generations (queueing beyond that) with a 120s timeout (`LLM_TIMEOUT`); if traffic grows,
  raise your llama.cpp parallelism first.

## Ingestion — building & updating the knowledge base

Ingestion is a **manual command**, safe to re-run anytime (documents have stable ids, so
re-running updates in place — no duplicates). Run it after game patches to keep answers current.
Re-runs are **incremental**: unchanged documents are detected by content hash and skipped, so a
full refresh takes ~3 minutes when little has changed (use `--force` to re-embed everything).

```bash
# Ingest ALL registered sources (with per-source progress bars):
docker compose run --rm bot star-agent-ingest

# List the available sources and their default caps:
docker compose run --rm bot star-agent-ingest --list

# Ingest only specific sources (-s/--source is repeatable):
docker compose run --rm bot star-agent-ingest --source rsi_ship_matrix
docker compose run --rm bot star-agent-ingest -s galactapedia -s comm_links

# Cap documents per source (0 = no cap) — handy for a quick test run:
docker compose run --rm bot star-agent-ingest -s galactapedia --max-docs 50

# Pull MORE news history than the default 300 most-recent Comm-Links:
docker compose run --rm bot star-agent-ingest -s comm_links --max-docs 1000
```

(Without Docker: the same command is `star-agent-ingest ...`. Ingestion is deliberately **not**
a Discord command — a full run exceeds Discord's 15-minute interaction limit and the embedding
would compete with the bot for CPU.)

**Scheduled auto-ingest:** the systemd installer (below) also sets up a **timer** that runs a full
ingestion on a schedule (default: daily at 04:17 local). Because unchanged documents are skipped,
these runs are typically ~3 minutes. Trigger one immediately with
`systemctl --user start staragent-ingest.service`; check the next run with
`systemctl --user list-timers staragent-ingest.timer`; change the cadence by editing
`OnCalendar=` in [`deploy/staragent-ingest.timer`](deploy/staragent-ingest.timer) and re-running
the installer.

### Registered sources and the URLs they pull

Each source is a module in [`src/star_agent/ingestion/sources/`](src/star_agent/ingestion/sources/) —
**that's where the ingested URLs are defined**. Currently registered:

| Source name | Data | Endpoint it pulls | Module |
|---|---|---|---|
| `rsi_ship_matrix` | Official ship specs (~250 ships) | `https://robertsspaceindustries.com/ship-matrix/index` | [`rsi_ship_matrix.py`](src/star_agent/ingestion/sources/rsi_ship_matrix.py) |
| `galactapedia` | Official lore (~1,500 articles) | `https://api.star-citizen.wiki/api/v2/galactapedia` | [`star_citizen_wiki.py`](src/star_agent/ingestion/sources/star_citizen_wiki.py) |
| `comm_links` | Official news/patch notes (all ~6,000 posts) | `https://api.star-citizen.wiki/api/v2/comm-links` | [`star_citizen_wiki.py`](src/star_agent/ingestion/sources/star_citizen_wiki.py) |
| `starsystems` | Star systems with lore descriptions (~100) | `https://api.star-citizen.wiki/api/v2/starsystems` | [`star_citizen_wiki.py`](src/star_agent/ingestion/sources/star_citizen_wiki.py) |
| `celestial_objects` | Planets, moons & stations with lore (~1,700, described only) | `https://api.star-citizen.wiki/api/v2/celestial-objects` | [`star_citizen_wiki.py`](src/star_agent/ingestion/sources/star_citizen_wiki.py) |
| `vehicles` | In-game vehicle stats + descriptions from game files (~290) | `https://api.star-citizen.wiki/api/v2/vehicles` | [`star_citizen_wiki.py`](src/star_agent/ingestion/sources/star_citizen_wiki.py) |
| `items` | Ship components & FPS items from game files (~12,000 raw; paints and description-less entries skipped) | `https://api.star-citizen.wiki/api/v2/items` | [`star_citizen_wiki.py`](src/star_agent/ingestion/sources/star_citizen_wiki.py) |
| `uex_commodities` | Commodity trading: prices + best buy/sell terminals (~150 commodities, community-reported) | `https://api.uexcorp.space/2.0/commodities` + `/commodities_prices_all` | [`uex.py`](src/star_agent/ingestion/sources/uex.py) |
| `uex_vehicle_prices` | Where to buy each ship in-game (aUEC) — requires `UEX_API_TOKEN` | `https://api.uexcorp.space/2.0/vehicles_purchases_prices_all` | [`uex.py`](src/star_agent/ingestion/sources/uex.py) |
| `uex_trade_routes` | Best trade routes per origin planet (profit/ROI) — requires `UEX_API_TOKEN` | `https://api.uexcorp.space/2.0/commodities_routes` | [`uex.py`](src/star_agent/ingestion/sources/uex.py) |

To add a new source: create a module there implementing `Source` (see `base.py`), then register
it in the `SOURCES` dict in
[`build_index.py`](src/star_agent/ingestion/build_index.py).

### Faster ingestion — offload embeddings to your LLM box

By default embeddings run **locally on the container's CPU** (MiniLM, ~7 chunks/s). Thanks to
the incremental hash-skip this is rarely a problem — but a from-scratch build (~14k chunks) takes
~35 minutes. You can offload embedding to any **OpenAI-compatible `/v1/embeddings` server**,
e.g. llama.cpp on a GPU machine, typically 10–50× faster:

1. On your llama.cpp box, serve an embedding model, e.g.:
   `llama-server -m nomic-embed-text-v1.5.Q8_0.gguf --embeddings --port 8081`
   (good GGUF choices: `nomic-embed-text-v1.5`, `bge-m3`, `snowflake-arctic-embed`)
2. In `.env`, set `EMBEDDING_BASE_URL=http://<llm-host>:8081/v1` and
   `EMBEDDING_MODEL=<model name>`.
3. ⚠️ **Embeddings must be consistent** — vectors written by one model can't be queried with
   another. Switching embedders means starting a fresh collection: stop the stack, delete the
   `chroma-data/` directory (or change `CHROMA_COLLECTION`), start Chroma, then run a full
   `star-agent-ingest --force`. The bot and MCP server must run with the same
   `EMBEDDING_*` settings so queries use the same model.

Leave `EMBEDDING_BASE_URL` unset to keep the zero-dependency local default.

## Choosing an LLM (including CPU-only)

StarAgent needs an OpenAI-compatible `/v1` server whose model handles **function/tool calling
reliably** (the agent calls one retrieval tool) plus grounded summarization. Any llama.cpp
`llama-server` works — **launch it with `--jinja`**, which is required for tool calling.

**GPU (reference setup):** a mid-size model like Qwen3.5-9B Q4_K_M gives fast, high-quality
answers.

**Hosted / authenticated endpoints:** any OpenAI-compatible API works — set `LLM_BASE_URL` to the
endpoint, `LLM_MODEL` to the model id, and `LLM_API_KEY` to your key (e.g. OpenAI, OpenRouter, or a
llama.cpp server behind an auth proxy). Local llama.cpp needs no key, so `LLM_API_KEY` stays blank.

**CPU-only is viable** with a small model — the sweet spot is **3–4B parameters, Q4_K_M**:

| Model | Size (Q4) | Tool calling in llama.cpp | Notes |
|---|---|---|---|
| **Qwen3-4B** ⭐ try first | ~2.5–3.3 GB | Native, reliable | Best balance; strong multilingual |
| **Qwen3-1.7B** | ~1.2–1.5 GB | Native — topped an independent 20-run tool-calling benchmark | Fastest; step down to this if 4B is too slow |
| Phi-4-mini (3.8B) | ~2.3–2.7 GB | Native but less reliable on borderline tool decisions | Good English reasoning |
| SmolLM3-3B | ~1.8–2 GB | Native | Fully open, multilingual |
| Llama 3.2 3B | ~2.0–2.2 GB | Native but over-eager (calls tools when it shouldn't) | |

Avoid 7–8B models on CPU (~4–5 tok/s generation blows the latency budget). Notably, tool-calling
quality does **not** track parameter count — Qwen3's small variants beat larger models in
benchmarks.

**Expected latency (8-core AVX2, Q4 3–4B):** ~30–65 s per answer. The bottleneck is *prompt
processing* of the RAG context, not generation. Tuning that matters:

```bash
llama-server -m Qwen3-4B-Q4_K_M.gguf --port 8080 \
  --jinja \                 # REQUIRED for tool calling
  --threads <physical cores> \  # not hyperthreads — oversubscribing hurts
  --ubatch-size 512         # bigger ubatch = much faster prompt processing
# Keep KV cache at f16 — quantized KV (-ctk q4_0) degrades tool calling.
# Build llama.cpp with OpenBLAS/MKL for a large prefill speedup.
```

Minimum sensible CPU host: ~8 physical cores + 8 GB RAM for <60 s answers (4 cores works with
Qwen3-1.7B). Benchmark your box with `llama-bench -p 2048` before committing. The bot's
`LLM_TIMEOUT` (default 120 s) already accommodates CPU-speed generation.

## Run at boot (systemd user service)

```bash
./deploy/install-service.sh
```

Installs [`deploy/staragent.service`](deploy/staragent.service) as a **systemd user service**:
renders the unit with this repo's path, enables it, and turns on lingering
(`loginctl enable-linger`) so the stack starts at boot without a login. Manage it with:

```bash
systemctl --user status staragent     # or start / stop / restart
journalctl --user -u staragent        # service logs (container logs: docker compose logs)
```

The unit runs `docker compose up -d` (stop: `docker compose down`) and waits for the Docker
daemon before starting. Containers themselves restart on failure via compose's
`restart: unless-stopped`.

It also installs and enables **`staragent-ingest.timer`** (+ its oneshot service), which
re-ingests the knowledge base on a schedule (see *Scheduled auto-ingest* above).

## Data sources

The knowledge base is built by scraping/pulling from the sources above. The full **catalog of
candidate sources** — with URLs, access method (API vs. scraping), and terms/rate-limit notes —
is in **[`docs/data-sources.md`](docs/data-sources.md)**.

- **Official (CIG / RSI):** [Ship Matrix](https://robertsspaceindustries.com/ship-matrix),
  [Galactapedia](https://robertsspaceindustries.com/galactapedia),
  [Comm-Link](https://robertsspaceindustries.com/comm-link),
  [Starmap](https://robertsspaceindustries.com/starmap)
- **Community wikis:** [Star Citizen Wiki](https://starcitizen.tools) (+ its
  [REST API](https://api.star-citizen.wiki)), [Fandom wiki](https://starcitizen.fandom.com)
- **Item / ship data:** [scunpacked](https://scunpacked.com) & GitHub game-data dumps,
  [Universal Item Finder](https://finder.cstone.space), [Erkul](https://www.erkul.games)
- **Trade / economy:** [UEX](https://uexcorp.space) (ingested — commodities & trade locations;
  set `UEX_API_TOKEN` in `.env` for rate-limit headroom); [SC Trade Tools](https://sc-trade.tools) (planned)

Community wikis are unofficial fansites; their content is licensed CC BY-NC-SA / CC BY-SA
(attribution + non-commercial). Respect each source's terms of service and `robots.txt`.

## License

The StarAgent **source code** is licensed under the [MIT License](LICENSE). This license covers
only the code in this repository — **not** any Star Citizen content, which remains the property of
Cloud Imperium Games / Roberts Space Industries (see the notice above).

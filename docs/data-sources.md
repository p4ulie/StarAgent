# Star Citizen Data Sources

Verified 2026-07-07. This is the reference list the ingestion pipeline draws from.

> **Ownership.** Cloud Imperium Games / Roberts Space Industries owns all *Star Citizen* copyright,
> trademarks, and IP. Every source below is either official RSI content or an **unofficial fansite**;
> none is affiliated with CIG. Respect each site's terms of service and `robots.txt`.

**General scraping notes.** RSI's own site and several community sites (e.g. `starcitizen.tools`)
sit behind Cloudflare bot protection — naive fetches can return **HTTP 403**. Always send a
descriptive `User-Agent` (configured via `INGEST_USER_AGENT`), prefer JSON/REST endpoints over HTML,
and rate-limit conservatively (`INGEST_RATE_DELAY`). robots.txt / explicit rate limits for RSI,
`starcitizen.tools`, Erkul, and CStone were **not individually confirmed — assume restrictive**.

## 1. Official (CIG / RSI)

No official public REST API is published; there are a few undocumented JSON endpoints plus HTML.

| Name | URL | Data | Access | Notes |
|---|---|---|---|---|
| RSI site | `https://robertsspaceindustries.com` | Hub | HTML | Cloudflare (403 to naive fetch). |
| **Ship Matrix (JSON)** | `https://robertsspaceindustries.com/ship-matrix/index` | Official ship specs (size, speed, crew, cargo, price, status, components) | **Undocumented JSON** — returns `{success, code, data:[…ships]}` | Best programmatic official ship source. May change without notice. **MVP source.** |
| Ship Matrix (HTML) | `https://robertsspaceindustries.com/ship-matrix` | Same as above | HTML | Canonical human page. |
| Galactapedia | `https://robertsspaceindustries.com/galactapedia` | Official lore: factions, characters, systems, species, tech | HTML; internal AJAX JSON (undocumented). Mirror: `api.star-citizen.wiki/galactapedia` | Prefer the community API mirror for structured pulls. |
| Starmap | `https://robertsspaceindustries.com/starmap` | Systems, planets/moons, stations, jump points | WebGL app + undocumented internal JSON. Mirror: `api.star-citizen.wiki/starmap/...` | Community mirror is the re-runnable path. |
| Comm-Link | `https://robertsspaceindustries.com/comm-link` | News, patch notes, dev updates, lore fiction | HTML; mirror `api.star-citizen.wiki/comm-links` | Updated multiple times weekly; stable numeric transmission IDs. |
| Spectrum | `https://robertsspaceindustries.com/spectrum` | Forums/chat | Undocumented internal REST/WS; auth often required | Low KB value; heavy scraping likely against ToS. |

## 2. Community wikis (MediaWiki / REST APIs — preferred)

| Name | URL / API | Data | Access | Notes |
|---|---|---|---|---|
| **Star Citizen Wiki** | Site `https://starcitizen.tools` · Action API `https://starcitizen.tools/api.php` · REST `https://starcitizen.tools/rest.php` | Ships, items/components, locations, lore, orgs, manufacturers | Public MediaWiki Action + REST + Semantic APIs (no key for reads) | Best community wiki. **CC BY-NC-SA** (attribution + non-commercial). Send a real User-Agent; use `api.php` not HTML. Tracks patch versions. |
| **Star Citizen Wiki API** | Base `https://api.star-citizen.wiki` · Docs `https://docs.star-citizen.wiki` | `/vehicles`, `/items`, `/galactapedia`, `/starmap/*`, `/comm-links`, `/locations`, `/commodities`, `/manufacturers` | Community REST (JSON), reads open (no key documented) | Cleanest single structured feed spanning lore + ships + starmap. Tracks multiple game versions. **RSI fallback mirror.** GitHub: `StarCitizenWiki/API`. |
| Fandom wiki | Site `https://starcitizen.fandom.com` · API `.../api.php` | General fan guide, lore, ships | Public MediaWiki Action API | **CC BY-SA**. Lower quality/currency than `.tools`; secondary. |

## 3. Item / ship databases

| Name | URL | Data | Access | Notes |
|---|---|---|---|---|
| scunpacked | `https://scunpacked.com` | Ships, components, FPS items from game files | Static JSON on the site | Prefer the GitHub dumps below. |
| **Game-data dumps (GitHub)** | `github.com/octfx/ScDataDumper` (active), `github.com/StarCitizenWiki/scunpacked-data`, `github.com/Dymerz/StarCitizen-GameData` | Authoritative ship/item/component JSON from `Data.p4k` | **git clone / raw fetch** | Most durable & re-runnable for in-game stats; version-tagged per patch. |
| CStone Universal Item Finder | `https://finder.cstone.space` | Where to buy items, shop inventories, prices | HTML scraping only | Crowdsourced (shop/price data removed from game files since 3.20); accuracy varies. |
| Erkul Games | `https://www.erkul.games` | Ship loadouts, weapon DPS, components | HTML SPA + undocumented internal API | Great derived combat stats; treat as scraping. |

## 4. Trade / economy / location — **deferred, NOT in the MVP**

| Name | URL / API | Data | Access | Notes |
|---|---|---|---|---|
| UEX Corp | `https://uexcorp.space` · `https://api.uexcorp.space/2.0` | Commodities, live prices, terminals, locations, mining | REST; reference reads ~public, enriched/write needs **Bearer token** | ~120 req/min. Community-reported (may lag). Tracks game version. |
| SC Trade Tools | `https://sc-trade.tools` · `/mcp` | Trade routes, prices, mining | API via **Bearer token** (MCP endpoint) | Player-reported, continuously updated. |
| Regolith | `https://regolith.rocks` | (was) mining optimization | — | **Defunct — shut down 2026-06-01. Do not use.** |

## 5. Programmatic APIs / datasets

| Name | URL | Data | Access | Notes |
|---|---|---|---|---|
| starcitizen-api.com | `https://starcitizen-api.com` | Ships, users, orgs (from RSI) + starmap + gamedata | Community REST — **API key required** (obtained via their Discord) | 1,000 live req/day; cache mode unlimited. |
| Star Citizen Wiki API | `https://api.star-citizen.wiki` | (see §2) | Community REST, no key | Strongest single re-runnable JSON feed. |
| GitHub game-data dumps | (see §3) | Authoritative ship/item JSON | git clone / raw | Most durable & re-runnable. |
| scdatatools | `https://gitlab.com/scmodding/frameworks/scdatatools` | Toolkit to unpack `Data.p4k` yourself | Python library | Use to generate your own dumps. |

## Ingestion priority (re-runnable → scrape-only)

1. **MVP:** RSI Ship Matrix JSON, then RSI Galactapedia + Comm-Link (with `api.star-citizen.wiki`
   as the fallback mirror).
2. Structured JSON/REST, no key: `api.star-citizen.wiki`, GitHub `ScDataDumper` / `scunpacked-data`.
3. MediaWiki API: `starcitizen.tools/api.php` (mind CC BY-NC-SA non-commercial clause).
4. Keyed/token REST (later): UEX, `starcitizen-api.com`, SC Trade Tools.
5. Scrape-only (real User-Agent, respect Cloudflare): RSI HTML, Erkul, CStone, Fandom.

Each ingested chunk stores metadata `{source, url, title, patch_version, retrieved_at}` for
citation and re-indexing.

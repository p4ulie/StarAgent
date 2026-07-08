"""Live UEX Corp tools for the agent.

Trade/economy data (prices, rentals, routes) is structured and volatile — a
poor fit for RAG. Instead the agent queries the UEX API live at request time
through these tools. Reference data is cached briefly to avoid hammering UEX
and to keep latency low.

Configured once at startup via :func:`configure`.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_API = "https://api.uexcorp.space/2.0"
_CACHE_TTL = 600.0  # seconds; prices don't change faster than this meaningfully


class _UexClient:
    """Async UEX client with a simple per-endpoint TTL cache."""

    def __init__(self, token: str | None, ttl: float = _CACHE_TTL) -> None:
        self._ttl = ttl
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._http = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def get(self, endpoint: str) -> list[dict]:
        now = time.monotonic()
        cached = self._cache.get(endpoint)
        if cached and cached[0] > now:
            return cached[1]
        resp = await self._http.get(f"{_API}/{endpoint}")
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        data = data if isinstance(data, list) else []
        self._cache[endpoint] = (now + self._ttl, data)
        return data


_client: _UexClient | None = None


def configure(token: str | None) -> None:
    """Wire the shared UEX client. Called once at startup."""
    global _client
    _client = _UexClient(token)


def _fmt(v: object, unit: str = "aUEC") -> str:
    try:
        return f"{int(v):,} {unit}"
    except (TypeError, ValueError):
        return str(v)


async def _ship_locations(ship_name: str, endpoint: str, price_key: str, mode: str) -> dict:
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        rows = await _client.get(endpoint)
    except Exception as exc:  # noqa: BLE001
        logger.exception("UEX lookup failed")
        return {"status": "error", "error": f"UEX request failed: {exc}"}

    q = ship_name.lower().strip()
    ships: dict[str, list[dict]] = {}
    for r in rows:
        name = str(r.get("vehicle_name") or "")
        if q in name.lower() and r.get(price_key):
            ships.setdefault(name, []).append(r)
    if not ships:
        return {"status": "not_found", "mode": mode, "ship_name": ship_name}

    results = []
    for name, recs in sorted(ships.items()):
        recs = sorted(recs, key=lambda r: r[price_key])
        results.append({
            "ship": name,
            "locations": [
                {"terminal": r.get("terminal_name"), "price": _fmt(r[price_key])} for r in recs
            ],
        })
    return {"status": "success", "mode": mode, "results": results,
            "note": "Community-reported via UEX; changes with game patches."}


async def get_ship_rental_locations(ship_name: str) -> dict:
    """Find where to RENT a ship in-game, with rental prices (aUEC).

    Use ONLY for rental questions ("where can I rent the Cutlass Black", "rent
    an Avenger"). For buying, use get_ship_purchase_locations instead. Matches
    ship names loosely (e.g. "Cutlass" returns all Cutlass variants).

    Args:
        ship_name: The ship/vehicle name or part of it.
    """
    return await _ship_locations(ship_name, "vehicles_rentals_prices_all", "price_rent", "rent")


async def get_ship_purchase_locations(ship_name: str) -> dict:
    """Find where to BUY a ship in-game, with purchase prices (aUEC).

    Use ONLY for buying questions ("where can I buy the Cutlass Black"). For
    renting, use get_ship_rental_locations instead. Matches ship names loosely.

    Args:
        ship_name: The ship/vehicle name or part of it.
    """
    return await _ship_locations(ship_name, "vehicles_purchases_prices_all", "price_buy", "buy")


async def list_rentable_ships() -> dict:
    """List EVERY rentable ship with its cheapest rental price and location.

    Use for "what ships can I rent", "list all rentable ships", "cheapest
    ships to rent". Returns the COMPLETE list in one call — every entry has a
    price, so present all of them; do not sample or omit any.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        rents = await _client.get("vehicles_rentals_prices_all")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    cheapest: dict[str, dict] = {}
    for r in rents:
        name = str(r.get("vehicle_name") or "")
        price = r.get("price_rent")
        if not name or not price:
            continue
        if name not in cheapest or price < cheapest[name]["_price"]:
            cheapest[name] = {"_price": price, "terminal": r.get("terminal_name")}
    ships = [
        {"ship": name, "cheapest_rent": _fmt(v["_price"]), "location": v["terminal"]}
        for name, v in sorted(cheapest.items())
    ]
    return {
        "status": "success",
        "count": len(ships),
        "ships": ships,
        "note": "Cheapest rental location per ship; community-reported via UEX.",
    }


async def get_item_purchase_locations(item_name: str) -> dict:
    """Find where to BUY an item in-game, with prices (aUEC).

    Covers weapons/guns, armor, clothing, and ship components (shields,
    coolers, quantum drives, etc.). Use for "where can I buy the P4-AR",
    "where to buy [armor/gun/component]". Matches names loosely.

    Args:
        item_name: The item name or part of it.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        rows = await _client.get("items_prices_all")
    except Exception as exc:  # noqa: BLE001
        logger.exception("UEX lookup failed")
        return {"status": "error", "error": f"UEX request failed: {exc}"}

    q = item_name.lower().strip()
    items: dict[str, list[dict]] = {}
    for r in rows:
        name = str(r.get("item_name") or "")
        if q in name.lower() and r.get("price_buy"):
            items.setdefault(name, []).append(r)
    if not items:
        return {"status": "not_found", "item_name": item_name}
    # A broad query (e.g. "armor") can match hundreds of items — return just
    # the names so the user can narrow, rather than a giant dump.
    if len(items) > 12:
        return {
            "status": "too_many",
            "item_name": item_name,
            "match_count": len(items),
            "matching_items": sorted(items)[:60],
            "note": "Many items match — ask about a more specific item name.",
        }
    results = []
    for name, recs in sorted(items.items()):
        recs = sorted(recs, key=lambda r: r["price_buy"])
        results.append({
            "item": name,
            "locations": [
                {"terminal": r.get("terminal_name"), "price": _fmt(r["price_buy"])} for r in recs
            ],
        })
    return {"status": "success", "results": results,
            "note": "Community-reported via UEX; changes with game patches."}


async def get_commodity_trade_prices(commodity_name: str) -> dict:
    """Best places to BUY and SELL a commodity, with current aUEC/SCU prices.

    Use for "where do I sell Laranite", "best price for Gold". Matches loosely.

    Args:
        commodity_name: The commodity name or part of it.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        prices = await _client.get("commodities_prices_all")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    q = commodity_name.lower().strip()
    recs = [r for r in prices if q in str(r.get("commodity_name") or "").lower()]
    if not recs:
        return {"status": "not_found", "commodity_name": commodity_name}
    name = recs[0].get("commodity_name")
    buys = sorted((r for r in recs if r.get("price_buy")), key=lambda r: r["price_buy"])[:5]
    sells = sorted((r for r in recs if r.get("price_sell")), key=lambda r: r["price_sell"], reverse=True)[:5]
    return {
        "status": "success",
        "commodity": name,
        "buy_at": [{"terminal": r.get("terminal_name"), "price": _fmt(r["price_buy"], "aUEC/SCU")} for r in buys],
        "sell_at": [{"terminal": r.get("terminal_name"), "price": _fmt(r["price_sell"], "aUEC/SCU")} for r in sells],
        "note": "Community-reported via UEX; changes with game patches.",
    }


async def find_trade_routes_from(origin: str) -> dict:
    """Best commodity trade routes starting from a planet, ranked by profit.

    Use for "what should I haul from Hurston", "best trade route from ArcCorp".

    Args:
        origin: Origin planet name (e.g. "Hurston", "ArcCorp", "microTech").
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        planets = await _client.get("planets")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    q = origin.lower().strip()
    match = next((p for p in planets if q in str(p.get("name") or "").lower() and p.get("is_available")), None)
    if not match:
        return {"status": "not_found", "origin": origin}
    try:
        routes = await _client.get(f"commodities_routes?id_planet_origin={match['id']}")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    routes = sorted((r for r in routes if r.get("profit")), key=lambda r: r["profit"], reverse=True)[:8]
    return {
        "status": "success",
        "origin": match.get("name"),
        "routes": [{
            "commodity": r.get("commodity_name"),
            "buy_at": r.get("origin_terminal_name"),
            "sell_at": f"{r.get('destination_terminal_name')} ({r.get('destination_planet_name') or r.get('destination_star_system_name')})",
            "profit_per_scu": _fmt(r.get("profit")),
            "roi_percent": r.get("price_roi"),
        } for r in routes],
        "note": "Community-reported via UEX; changes with game patches.",
    }


ALL_TOOLS = [
    get_ship_rental_locations,
    get_ship_purchase_locations,
    list_rentable_ships,
    get_item_purchase_locations,
    get_commodity_trade_prices,
    find_trade_routes_from,
]

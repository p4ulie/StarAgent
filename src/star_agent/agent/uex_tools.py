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


async def get_ship_buy_and_rent_locations(ship_name: str) -> dict:
    """Find where to BUY and RENT a ship in-game, with current aUEC prices.

    Use for questions like "where can I buy/rent the Cutlass Black" or "how
    much to rent an Avenger". Matches ship names loosely (e.g. "Cutlass"
    returns all Cutlass variants).

    Args:
        ship_name: The ship/vehicle name or part of it.

    Returns:
        Per matching ship: cheapest buy terminals and cheapest rent terminals.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        buys = await _client.get("vehicles_purchases_prices_all")
        rents = await _client.get("vehicles_rentals_prices_all")
    except Exception as exc:  # noqa: BLE001
        logger.exception("UEX lookup failed")
        return {"status": "error", "error": f"UEX request failed: {exc}"}

    q = ship_name.lower().strip()
    ships: dict[str, dict] = {}
    for r in buys:
        name = str(r.get("vehicle_name") or "")
        if q in name.lower() and r.get("price_buy"):
            ships.setdefault(name, {"buy": [], "rent": []})["buy"].append(r)
    for r in rents:
        name = str(r.get("vehicle_name") or "")
        if q in name.lower() and r.get("price_rent"):
            ships.setdefault(name, {"buy": [], "rent": []})["rent"].append(r)
    if not ships:
        return {"status": "not_found", "ship_name": ship_name}

    results = []
    for name, data in sorted(ships.items()):
        buy = sorted(data["buy"], key=lambda r: r["price_buy"])[:5]
        rent = sorted(data["rent"], key=lambda r: r["price_rent"])[:5]
        results.append({
            "ship": name,
            "buy": [{"terminal": r.get("terminal_name"), "price": _fmt(r["price_buy"])} for r in buy],
            "rent": [{"terminal": r.get("terminal_name"), "price": _fmt(r["price_rent"])} for r in rent],
        })
    return {"status": "success", "results": results,
            "note": "Community-reported via UEX; changes with game patches."}


async def list_rentable_ships() -> dict:
    """List every ship that can currently be rented in-game (via UEX).

    Use for "what ships can I rent", "list all rentable ships". Returns the
    complete list, not a sample.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        rents = await _client.get("vehicles_rentals_prices_all")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    names = sorted({str(r.get("vehicle_name")) for r in rents if r.get("price_rent") and r.get("vehicle_name")})
    return {"status": "success", "count": len(names), "ships": names}


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
    get_ship_buy_and_rent_locations,
    list_rentable_ships,
    get_commodity_trade_prices,
    find_trade_routes_from,
]

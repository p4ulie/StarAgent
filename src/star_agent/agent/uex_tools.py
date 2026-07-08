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
    """List EVERY rentable ship with cargo (SCU), cheapest rent price, location.

    Use for "what ships can I rent", "list rentable ships", "rentable ships by
    cargo". Joins rental data with ship specs so each entry already has cargo,
    price, and location — return ALL of them, sorted by cargo (largest first).
    Do not sample, omit, or try to look up cargo per ship yourself.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        rents = await _client.get("vehicles_rentals_prices_all")
        vehicles = await _client.get("vehicles")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}

    scu_by_name = {str(v.get("name")): v.get("scu") for v in vehicles if v.get("name")}
    cheapest: dict[str, dict] = {}
    for r in rents:
        name = str(r.get("vehicle_name") or "")
        price = r.get("price_rent")
        if not name or not price:
            continue
        if name not in cheapest or price < cheapest[name]["_price"]:
            cheapest[name] = {"_price": price, "terminal": r.get("terminal_name")}

    ships = [
        {
            "ship": name,
            "cargo_scu": scu_by_name.get(name),  # None if unknown ("where available")
            "cheapest_rent": _fmt(v["_price"]),
            "location": v["terminal"],
        }
        for name, v in cheapest.items()
    ]
    ships.sort(key=lambda s: (s["cargo_scu"] or -1), reverse=True)
    return {
        "status": "success",
        "count": len(ships),
        "ships": ships,
        "note": "Cargo in SCU; cheapest rental location per ship; community-reported via UEX.",
    }


_ROLE_FLAGS = {
    "is_cargo": "cargo", "is_mining": "mining", "is_salvage": "salvage",
    "is_military": "military", "is_exploration": "exploration", "is_medical": "medical",
    "is_racing": "racing", "is_stealth": "stealth", "is_refuel": "refueling",
    "is_repair": "repair", "is_passenger": "passenger", "is_industrial": "industrial",
    "is_interdiction": "interdiction", "is_ground_vehicle": "ground vehicle",
    "is_starter": "starter", "is_science": "science", "is_construction": "construction",
    "is_refinery": "refinery", "is_bomber": "bomber", "is_datarunner": "data running",
}
_SHIP_LIST_CAP = 60


def _ship_roles(v: dict) -> list[str]:
    return [label for flag, label in _ROLE_FLAGS.items() if v.get(flag)]


async def get_ship_specifications(ship_name: str) -> dict:
    """Get a ship's specifications: cargo (SCU), crew, size, mass, roles.

    Use for "what's the cargo capacity of the Freelancer", "how big is the
    Carrack", "specs for the Cutlass". Matches names loosely.

    Args:
        ship_name: The ship/vehicle name or part of it.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        vehicles = await _client.get("vehicles")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    q = ship_name.lower().strip()
    matches = [v for v in vehicles if q in str(v.get("name") or "").lower()]
    if not matches:
        return {"status": "not_found", "ship_name": ship_name}
    ships = [{
        "ship": v.get("name"),
        "manufacturer": v.get("company_name"),
        "cargo_scu": v.get("scu"),
        "crew": v.get("crew"),
        "mass_kg": v.get("mass"),
        "size_m": {"length": v.get("length"), "width": v.get("width"), "height": v.get("height")},
        "roles": _ship_roles(v),
        "quantum_capable": bool(v.get("is_quantum_capable")),
    } for v in matches[:_SHIP_LIST_CAP]]
    return {"status": "success", "ships": ships,
            "note": "From UEX (game-file data); tracks the live game version."}


async def list_ships_by_cargo(min_scu: int = 0) -> dict:
    """List ships by cargo capacity (SCU), largest first.

    Use for "which ships carry the most cargo", "list ships by cargo",
    "cargo ships over 100 SCU". Optionally filter to ships with at least
    ``min_scu`` cargo. Returns the top ships by capacity.

    Args:
        min_scu: Minimum cargo capacity in SCU (0 = no minimum).
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        vehicles = await _client.get("vehicles")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    ships = []
    for v in vehicles:
        scu = v.get("scu")
        if scu and scu >= min_scu:
            ships.append({"ship": v.get("name"), "cargo_scu": scu,
                          "manufacturer": v.get("company_name")})
    ships.sort(key=lambda s: s["cargo_scu"], reverse=True)
    total = len(ships)
    shown = ships[:_SHIP_LIST_CAP]
    result = {"status": "success", "count": total, "ships": shown,
              "note": "Cargo in SCU, from UEX game-file data."}
    if total > len(shown):
        result["truncated"] = f"Showing the {len(shown)} largest of {total}; raise min_scu to narrow."
    return result


async def list_buyable_ships() -> dict:
    """List EVERY ship buyable in-game with cargo (SCU), cheapest price, location.

    Use for "ships I can buy in game", "buyable ships by cargo", "cheapest
    ships to buy". Joins purchase data with ship specs — one call returns all
    of them with cargo, price, and location, sorted by cargo. Return them all;
    do not sample or look up cargo per ship yourself. (These are in-game aUEC
    prices, not pledge-store USD.)
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        buys = await _client.get("vehicles_purchases_prices_all")
        vehicles = await _client.get("vehicles")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}

    scu_by_name = {str(v.get("name")): v.get("scu") for v in vehicles if v.get("name")}
    cheapest: dict[str, dict] = {}
    for r in buys:
        name = str(r.get("vehicle_name") or "")
        price = r.get("price_buy")
        if not name or not price:
            continue
        if name not in cheapest or price < cheapest[name]["_price"]:
            cheapest[name] = {"_price": price, "terminal": r.get("terminal_name")}

    ships = [
        {
            "ship": name,
            "cargo_scu": scu_by_name.get(name),
            "cheapest_price": _fmt(v["_price"]),
            "location": v["terminal"],
        }
        for name, v in cheapest.items()
    ]
    ships.sort(key=lambda s: (s["cargo_scu"] or -1), reverse=True)
    return {
        "status": "success",
        "count": len(ships),
        "ships": ships,
        "note": "Cargo in SCU; cheapest in-game purchase location per ship; community-reported via UEX.",
    }


_ROLE_LOOKUP = {label: flag for flag, label in _ROLE_FLAGS.items()}
_ROLE_SYNONYMS = {
    "combat": "military", "fighter": "military", "hauler": "cargo",
    "transport": "cargo", "miner": "mining", "explorer": "exploration",
    "medic": "medical", "med": "medical", "refuel": "refueling", "fuel": "refueling",
}


async def find_ships_by_role(role: str) -> dict:
    """List ships by role/purpose, sorted by cargo capacity.

    Roles: cargo, mining, salvage, military, exploration, medical, racing,
    stealth, refueling, repair, passenger, industrial, interdiction, science,
    construction, refinery, bomber, "ground vehicle", "data running". Use for
    "list all mining ships", "what cargo ships are there", "military ships".

    Args:
        role: The role/purpose to filter by.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        vehicles = await _client.get("vehicles")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}

    q = role.lower().strip()
    q = _ROLE_SYNONYMS.get(q, q)
    qwords = set(q.split())
    flag = None
    matched_role = None
    for label, fl in _ROLE_LOOKUP.items():
        if q == label or (qwords & set(label.split())):
            flag, matched_role = fl, label
            break
    if flag is None:
        return {"status": "unknown_role", "role": role,
                "available_roles": sorted(_ROLE_LOOKUP)}

    ships = [
        {"ship": v.get("name"), "cargo_scu": v.get("scu"),
         "manufacturer": v.get("company_name")}
        for v in vehicles if v.get(flag)
    ]
    ships.sort(key=lambda s: (s["cargo_scu"] or -1), reverse=True)
    return {"status": "success", "role": matched_role, "count": len(ships),
            "ships": ships[:_SHIP_LIST_CAP], "note": "From UEX game-file role flags."}


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


def _fmt_route(r: dict) -> dict:
    dest = r.get("destination_planet_name") or r.get("destination_star_system_name")
    return {
        "commodity": r.get("commodity_name"),
        "buy_at": r.get("origin_terminal_name"),
        "sell_at": f"{r.get('destination_terminal_name')} ({dest})",
        "profit_per_scu": _fmt(r.get("profit")),
        "roi_percent": r.get("price_roi"),
    }


async def find_trade_routes_from(origin: str) -> dict:
    """Best commodity trade routes starting from a planet, ranked by profit.

    Use for "what should I haul from Hurston", "best trade route from ArcCorp".
    The destination may be in another system. For routes that stay within one
    system, use find_trade_routes_in_system.

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
        "routes": [_fmt_route(r) for r in routes],
        "note": "Community-reported via UEX; changes with game patches.",
    }


async def find_trade_routes_in_system(system: str) -> dict:
    """Best trade routes that start AND end in the same star system (no jumps).

    Use for "trade routes within Stanton", "best in-system routes in Pyro" —
    routes where you never leave the system.

    Args:
        system: The star system name (e.g. "Stanton", "Pyro").
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        systems = await _client.get("star_systems")
        q = system.lower().strip()
        sysm = next((s for s in systems if q in str(s.get("name") or "").lower()), None)
        if not sysm:
            return {"status": "not_found", "system": system}
        sid = sysm["id"]
        planets = [p for p in await _client.get("planets") if p.get("id_star_system") == sid]
        routes, seen = [], set()
        for p in planets:
            for r in await _client.get(f"commodities_routes?id_planet_origin={p['id']}"):
                if r.get("id_star_system_destination") == sid and r.get("profit"):
                    key = (r.get("commodity_name"), r.get("origin_terminal_name"),
                           r.get("destination_terminal_name"))
                    if key not in seen:
                        seen.add(key)
                        routes.append(r)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    routes.sort(key=lambda r: r["profit"], reverse=True)
    return {
        "status": "success",
        "system": sysm.get("name"),
        "count": len(routes),
        "routes": [_fmt_route(r) for r in routes[:12]],
        "note": "Routes staying within the system; community-reported via UEX.",
    }


_FACILITIES = {
    "has_clinic": "clinic", "has_food": "food", "has_refuel": "refuel",
    "has_refinery": "refinery", "has_habitation": "habitation",
    "has_cargo_center": "cargo center", "has_docking_port": "docking",
    "has_loading_dock": "loading dock", "has_freight_elevator": "freight elevator",
}


def _services(rec: dict) -> list[str]:
    return [label for flag, label in _FACILITIES.items() if rec.get(flag)]


def _where(rec: dict, systems: dict, planets: dict, moons: dict) -> str:
    parts = [moons.get(rec.get("id_moon")), planets.get(rec.get("id_planet"))]
    sysname = systems.get(rec.get("id_star_system"))
    if sysname:
        parts.append(f"{sysname} system")
    return ", ".join(p for p in parts if p)


async def find_location(name: str) -> dict:
    """Look up a location by name — system, planet, moon, station, city, outpost,
    or settlement (e.g. "Shepherd's Rest", "Lorville", "Daymar").

    Returns what it is, where it is, and (for outposts/settlements) which
    services it has. Matches names loosely.

    Args:
        name: The location name or part of it.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        systems = {s["id"]: s.get("name") for s in await _client.get("star_systems")}
        planets = {p["id"]: p.get("name") for p in await _client.get("planets")}
        moons = {m["id"]: m.get("name") for m in await _client.get("moons")}
        sources = [
            ("star system", "star_systems"), ("planet", "planets"), ("moon", "moons"),
            ("station", "space_stations"), ("city", "cities"),
            ("outpost/settlement", "outposts"), ("point of interest", "poi"),
        ]
        q = name.lower().strip()
        results = []
        for kind, ep in sources:
            for rec in await _client.get(ep):
                nm = str(rec.get("name") or "")
                if nm and q in nm.lower():
                    entry = {"name": nm, "type": kind,
                             "where": _where(rec, systems, planets, moons)}
                    if svc := _services(rec):
                        entry["services"] = svc
                    if rec.get("faction_name"):
                        entry["faction"] = rec["faction_name"]
                    results.append(entry)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    if not results:
        return {"status": "not_found", "name": name}
    return {"status": "success", "count": len(results),
            "locations": results[:_SHIP_LIST_CAP], "note": "From UEX."}


async def list_settlements_on(body: str) -> dict:
    """List settlements/outposts on a planet or moon, with their services.

    Use for "settlements on Hurston", "outposts on Daymar", "what's on
    microTech". Matches the planet/moon name loosely.

    Args:
        body: The planet or moon name.
    """
    if _client is None:
        return {"status": "error", "error": "UEX is not configured."}
    try:
        planets = await _client.get("planets")
        moons = await _client.get("moons")
        outposts = await _client.get("outposts")
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"UEX request failed: {exc}"}
    q = body.lower().strip()
    moon = next((m for m in moons if q in str(m.get("name") or "").lower()), None)
    planet = next((p for p in planets if q in str(p.get("name") or "").lower()), None)
    target, key = (moon, "id_moon") if moon else (planet, "id_planet")
    if not target:
        return {"status": "not_found", "body": body}
    found = [o for o in outposts if o.get(key) == target["id"]]
    settlements = [
        {"name": o.get("name"), "services": _services(o), "faction": o.get("faction_name")}
        for o in found
    ]
    return {"status": "success", "body": target.get("name"),
            "count": len(settlements), "settlements": settlements, "note": "From UEX."}


ALL_TOOLS = [
    get_ship_specifications,
    list_ships_by_cargo,
    find_ships_by_role,
    get_ship_rental_locations,
    get_ship_purchase_locations,
    list_rentable_ships,
    list_buyable_ships,
    get_item_purchase_locations,
    get_commodity_trade_prices,
    find_trade_routes_from,
    find_trade_routes_in_system,
    find_location,
    list_settlements_on,
]

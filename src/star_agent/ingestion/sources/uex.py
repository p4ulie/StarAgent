"""UEX Corp trade/economy source (uexcorp.space).

Produces one document per tradeable commodity summarizing what it is, its
average prices, and the best buy/sell terminals — answering "where do I sell
Laranite?"-style questions. Reference reads are public; a UEX_API_TOKEN (from
uexcorp.space "My Apps") is sent as a Bearer header when configured, for
rate-limit headroom.

Prices are community-reported and shift with game patches — re-ingest to
refresh (each chunk's ``retrieved_at`` records data age).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from star_agent.config import get_settings
from star_agent.ingestion.loaders import HttpFetcher
from star_agent.ingestion.sources.base import Document

logger = logging.getLogger(__name__)

_API_BASE = "https://api.uexcorp.space/2.0"
_TOP_N = 5  # best buy/sell locations listed per commodity


def _fmt_price(value: Any) -> str:
    try:
        return f"{int(value):,} aUEC/SCU"
    except (TypeError, ValueError):
        return str(value)


def _fmt_price_flat(value: Any) -> str:
    try:
        return f"{int(value):,} aUEC"
    except (TypeError, ValueError):
        return str(value)


class UexCommoditiesSource:
    """One document per commodity: description facts + best trade locations."""

    name = "uex_commodities"
    default_max_docs = 0  # ~150 commodities

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs
        token = get_settings().uex_api_token
        self._headers = {"Authorization": f"Bearer {token}"} if token else None

    def _get_data(self, endpoint: str) -> list[dict[str, Any]]:
        payload = self._http.get_json(f"{_API_BASE}/{endpoint}", headers=self._headers)
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, list) else []

    def fetch(self) -> Iterable[Document]:
        commodities = self._get_data("commodities")
        prices = self._get_data("commodities_prices_all")

        # Group price records (commodity x terminal) by commodity id.
        by_commodity: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for rec in prices:
            cid = rec.get("id_commodity")
            if isinstance(cid, int):
                by_commodity[cid].append(rec)

        count = 0
        for com in commodities:
            cid = com.get("id")
            name = str(com.get("name") or "").strip()
            if not isinstance(cid, int) or not name or not com.get("is_available"):
                continue

            facts = [f"Commodity: {name}"]
            if com.get("kind"):
                facts.append(f"Kind: {com['kind']}")
            if com.get("is_illegal"):
                facts.append("Legality: ILLEGAL to trade in monitored space")
            if com.get("price_buy"):
                facts.append(f"Average buy price: {_fmt_price(com['price_buy'])}")
            if com.get("price_sell"):
                facts.append(f"Average sell price: {_fmt_price(com['price_sell'])}")

            recs = by_commodity.get(cid, [])
            buys = sorted(
                (r for r in recs if r.get("price_buy")),
                key=lambda r: r["price_buy"],
            )[:_TOP_N]
            sells = sorted(
                (r for r in recs if r.get("price_sell")),
                key=lambda r: r["price_sell"],
                reverse=True,
            )[:_TOP_N]

            sections = ["\n".join(facts)]
            if buys:
                sections.append(
                    "Best places to BUY (lowest price):\n"
                    + "\n".join(
                        f"- {r.get('terminal_name')}: {_fmt_price(r['price_buy'])}"
                        for r in buys
                    )
                )
            if sells:
                sections.append(
                    "Best places to SELL (highest price):\n"
                    + "\n".join(
                        f"- {r.get('terminal_name')}: {_fmt_price(r['price_sell'])}"
                        for r in sells
                    )
                )
            sections.append(
                "Prices are community-reported via UEX and change with game patches."
            )

            yield Document(
                id=f"uex-commodity::{cid}",
                title=f"{name} (commodity trading)",
                url="https://uexcorp.space/commodities",
                source="UEX Corp",
                text="\n\n".join(sections),
                extra={"kind": str(com.get("kind") or "")},
            )
            count += 1
            if self._max_docs and count >= self._max_docs:
                return
        logger.info("UEX: produced %d commodity documents", count)


class UexVehiclePricesSource:
    """Where to buy each ship in-game (aUEC), one document per vehicle.

    Uses ``vehicles_purchases_prices_all`` (requires the Bearer token) — NOT
    ``vehicles_prices``, which is pledge-store USD pricing.
    """

    name = "uex_vehicle_prices"
    default_max_docs = 0  # ~150 purchasable vehicles

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs
        token = get_settings().uex_api_token
        self._headers = {"Authorization": f"Bearer {token}"} if token else None

    def fetch(self) -> Iterable[Document]:
        payload = self._http.get_json(
            f"{_API_BASE}/vehicles_purchases_prices_all", headers=self._headers
        )
        records = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            logger.warning("UEX vehicles_purchases_prices_all returned no data")
            return

        by_vehicle: dict[int, list[dict[str, Any]]] = defaultdict(list)
        names: dict[int, str] = {}
        for rec in records:
            vid = rec.get("id_vehicle")
            if isinstance(vid, int) and rec.get("price_buy"):
                by_vehicle[vid].append(rec)
                names.setdefault(vid, str(rec.get("vehicle_name") or "").strip())

        count = 0
        for vid, recs in by_vehicle.items():
            name = names.get(vid)
            if not name:
                continue
            recs.sort(key=lambda r: r["price_buy"])
            lines = [
                f"- {r.get('terminal_name')}: {_fmt_price_flat(r['price_buy'])}"
                for r in recs
            ]
            text = (
                f"Where to buy the {name} in game (aUEC):\n"
                + "\n".join(lines)
                + "\n\nPrices are community-reported via UEX and change with game patches."
            )
            yield Document(
                id=f"uex-vehicle-price::{vid}",
                title=f"{name} (in-game purchase locations)",
                url="https://uexcorp.space/vehicles",
                source="UEX Corp",
                text=text,
            )
            count += 1
            if self._max_docs and count >= self._max_docs:
                return
        logger.info("UEX: produced %d vehicle-price documents", count)


class UexTradeRoutesSource:
    """Best trade routes per origin planet (requires the Bearer token).

    One document per origin planet with its top routes by profit —
    "what should I haul from Hurston?" territory.
    """

    name = "uex_trade_routes"
    default_max_docs = 0  # ~20 available planets
    _TOP_ROUTES = 8

    def __init__(self, http: HttpFetcher, max_docs: int | None = None) -> None:
        self._http = http
        self._max_docs = self.default_max_docs if max_docs is None else max_docs
        token = get_settings().uex_api_token
        self._headers = {"Authorization": f"Bearer {token}"} if token else None

    def _get_data(self, endpoint: str) -> list[dict[str, Any]]:
        payload = self._http.get_json(f"{_API_BASE}/{endpoint}", headers=self._headers)
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, list) else []

    def fetch(self) -> Iterable[Document]:
        planets = [
            p for p in self._get_data("planets")
            if p.get("is_available") and isinstance(p.get("id"), int)
        ]
        count = 0
        for planet in planets:
            pid, pname = planet["id"], str(planet.get("name") or "").strip()
            if not pname:
                continue
            routes = self._get_data(f"commodities_routes?id_planet_origin={pid}")
            routes = [r for r in routes if r.get("profit") and r.get("price_margin")]
            routes.sort(key=lambda r: r.get("profit") or 0, reverse=True)
            if not routes:
                continue
            lines = []
            for r in routes[: self._TOP_ROUTES]:
                lines.append(
                    f"- {r.get('commodity_name')}: buy at {r.get('origin_terminal_name')} "
                    f"({_fmt_price_flat(r.get('price_origin'))}/SCU) -> sell at "
                    f"{r.get('destination_terminal_name')} "
                    f"({r.get('destination_planet_name') or r.get('destination_star_system_name')}) "
                    f"for {_fmt_price_flat(r.get('price_destination'))}/SCU — "
                    f"profit {_fmt_price_flat(r.get('profit'))}, ROI {r.get('price_roi')}%"
                )
            text = (
                f"Best commodity trade routes starting from {pname}:\n"
                + "\n".join(lines)
                + "\n\nPrices are community-reported via UEX and change with game patches."
            )
            yield Document(
                id=f"uex-routes::{pid}",
                title=f"Trade routes from {pname}",
                url="https://uexcorp.space/routes",
                source="UEX Corp",
                text=text,
            )
            count += 1
            if self._max_docs and count >= self._max_docs:
                return
        logger.info("UEX: produced %d trade-route documents", count)

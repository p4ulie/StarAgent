"""RSI Ship Matrix — the MVP ingestion source.

Pulls the official ship list from RSI's undocumented Ship Matrix JSON endpoint
and turns each ship into one readable knowledge-base document.

Caveats: the endpoint is undocumented (fields may change) and RSI sits behind
Cloudflare (a naive fetch can 403). If it fails, the build logs the error and
continues; the ``api.star-citizen.wiki`` mirror is the intended fallback source.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from star_agent.ingestion.loaders import HttpFetcher
from star_agent.ingestion.sources.base import Document

logger = logging.getLogger(__name__)

_RSI_BASE = "https://robertsspaceindustries.com"
_SHIP_MATRIX_URL = f"{_RSI_BASE}/ship-matrix/index"


def _clean(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _manufacturer(ship: dict[str, Any]) -> str:
    manu = ship.get("manufacturer")
    if isinstance(manu, dict):
        return _clean(manu.get("name") or manu.get("code"))
    return _clean(manu)


def _ship_to_document(ship: dict[str, Any]) -> Document | None:
    name = _clean(ship.get("name"))
    ship_id = _clean(ship.get("id"))
    if not name or not ship_id:
        return None

    manufacturer = _manufacturer(ship)
    rel_url = _clean(ship.get("url"))
    url = f"{_RSI_BASE}{rel_url}" if rel_url.startswith("/") else (rel_url or f"{_RSI_BASE}/ship-matrix")

    # Build a readable spec sheet; only include fields that are present.
    fields: list[tuple[str, str]] = [
        ("Manufacturer", manufacturer),
        ("Focus", _clean(ship.get("focus"))),
        ("Type", _clean(ship.get("type"))),
        ("Production status", _clean(ship.get("production_status"))),
        ("Size", _clean(ship.get("size"))),
        ("Length (m)", _clean(ship.get("length"))),
        ("Beam (m)", _clean(ship.get("beam"))),
        ("Height (m)", _clean(ship.get("height"))),
        ("Mass (kg)", _clean(ship.get("mass"))),
        ("Cargo capacity (SCU)", _clean(ship.get("cargocapacity"))),
        ("Max crew", _clean(ship.get("max_crew"))),
        ("Min crew", _clean(ship.get("min_crew"))),
        ("SCM speed (m/s)", _clean(ship.get("scm_speed"))),
        ("Afterburner speed (m/s)", _clean(ship.get("afterburner_speed"))),
        ("Price (UEC)", _clean(ship.get("price"))),
    ]
    spec_lines = [f"{label}: {val}" for label, val in fields if val]

    description = _clean(ship.get("description"))

    header = f"{name}" + (f" — {manufacturer}" if manufacturer else "")
    body_parts = [header]
    if spec_lines:
        body_parts.append("\n".join(spec_lines))
    if description:
        body_parts.append(description)
    text = "\n\n".join(body_parts)

    return Document(
        id=f"rsi-ship-matrix::{ship_id}",
        title=name,
        url=url,
        source="RSI Ship Matrix",
        text=text,
        extra={"manufacturer": manufacturer} if manufacturer else {},
    )


class RsiShipMatrixSource:
    """Yields one document per ship in the official RSI Ship Matrix."""

    name = "rsi_ship_matrix"

    def __init__(self, http: HttpFetcher) -> None:
        self._http = http

    def fetch(self) -> Iterable[Document]:
        payload = self._http.get_json(_SHIP_MATRIX_URL)
        ships = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(ships, list):
            logger.warning("RSI Ship Matrix returned no 'data' list; got keys: %s",
                           list(payload) if isinstance(payload, dict) else type(payload))
            return
        count = 0
        for ship in ships:
            if not isinstance(ship, dict):
                continue
            doc = _ship_to_document(ship)
            if doc is not None:
                count += 1
                yield doc
        logger.info("RSI Ship Matrix: produced %d ship documents", count)

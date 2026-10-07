"""Extrai ofertas do JSON que o site da LATAM recebe da sua API (``/bff/air-offers/.../offers/search``).

A API não é pública nem documentada, então o parser é tolerante: procura qualquer objeto com
uma lista ``brands`` (tarifas Light/Standard/Full/...) e tira voo, horários, escalas e preço
dos campos com os nomes que o site usa hoje, com alternativas para nomes parecidos.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

POINTS_CURRENCIES = {"PTS", "POINTS", "LATAMPASS", "LATAM_PASS", "LTP", "MILES", "MILLAS", "PUNTOS"}


def _walk(node: Any, parent: dict | None = None) -> Iterator[tuple[dict, dict | None]]:
    """(objeto, objeto que o contém) para todo dict do JSON."""
    if isinstance(node, dict):
        yield node, parent
        for v in node.values():
            yield from _walk(v, node)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, parent)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(" ", "")
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # "45.000" = 45 mil (formato brasileiro)
            s = s.replace(".", "")
        try:
            return float(s)
        except ValueError:
            return None
    if isinstance(value, dict):
        for k in ("amount", "value", "total", "points", "miles"):
            if k in value:
                return _num(value[k])
    return None


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def _price(brand: dict) -> tuple[float | None, str, float | None]:
    """(valor, moeda, taxas) de uma tarifa."""
    p = _first(brand, "price", "totalPrice", "fare", "offerPrice")
    amount = _num(p)
    currency = ""
    taxes = None
    if isinstance(p, dict):
        currency = str(_first(p, "currency", "currencyCode", "currencySymbol") or "")
        taxes = _num(_first(p, "taxes", "tax", "taxAmount", "fees"))
    currency = currency or str(_first(brand, "currency", "currencyCode") or "")
    if taxes is None:
        taxes = _num(_first(brand, "taxes", "tax", "taxAmount"))
    if amount is None:
        amount = _num(_first(brand, "points", "miles", "amount"))
        if amount is not None and not currency:
            currency = "PTS"
    return amount, currency.upper(), taxes


def _flight_code(offer: dict, summary: dict) -> str:
    code = _first(summary, "flightCode", "flightNumber")
    if code:
        return str(code)
    codes = []
    for seg in offer.get("itinerary") or summary.get("itinerary") or []:
        f = seg.get("flight", seg) if isinstance(seg, dict) else {}
        num = _first(f, "flightNumber", "number")
        if num:
            codes.append(f"{_first(f, 'airlineCode', 'operatingAirlineCode') or ''}{num}")
    return "+".join(codes)


def _stops(offer: dict, summary: dict) -> int | None:
    n = _first(summary, "stopQuantity", "stops", "numberOfStops")
    if n is None:
        n = _first(offer, "stopQuantity", "stops")
    if isinstance(n, list):
        return len(n)
    if n is not None:
        try:
            return int(n)
        except (TypeError, ValueError):
            pass
    segs = offer.get("itinerary") or summary.get("itinerary")
    if isinstance(segs, list) and segs:
        return len(segs) - 1
    return None


def _when(place: Any, *keys: str) -> str:
    if isinstance(place, dict):
        v = _first(place, *keys)
        return str(v) if v else ""
    return ""


def extract_offers(payload: Any) -> list[dict[str, Any]]:
    """Lista de tarifas (uma por voo × marca tarifária)."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for node, parent in _walk(payload):
        brands = node.get("brands")
        if not isinstance(brands, list) or not brands or not all(isinstance(b, dict) for b in brands):
            continue
        summary = node
        # "brands" fica em content[i].summary; os trechos ficam em content[i].itinerary.
        offer = parent if parent is not None and parent.get("summary") is node else node
        origin = _first(summary, "origin", "departure") or {}
        dest = _first(summary, "destination", "arrival") or {}
        flight = _flight_code(offer, summary)
        stops = _stops(offer, summary)
        depart = _when(origin, "departure", "departureDate", "dateTime", "date")
        arrive = _when(dest, "arrival", "arrivalDate", "dateTime", "date")
        duration = _first(summary, "duration", "totalDuration") or ""
        for b in brands:
            amount, currency, taxes = _price(b)
            if amount is None:
                continue
            brand = str(_first(b, "brandText", "name", "brandName", "id", "code") or "")
            key = (flight, depart, brand, amount, currency)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "flight": flight,
                    "depart": depart,
                    "arrive": arrive,
                    "stops": stops,
                    "duration": duration,
                    "brand": brand,
                    "price": amount,
                    "currency": currency,
                    "taxes": taxes,
                    "seats": _first(b, "availableSeats", "seatsAvailable", "seats") or "",
                }
            )
    return rows


def is_points(currency: str) -> bool:
    return currency.replace(" ", "").upper() in POINTS_CURRENCIES

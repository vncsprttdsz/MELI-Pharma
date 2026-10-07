"""Preço em dinheiro pelo Google Flights (biblioteca ``fli``, que usa a API interna do Google Flights).

O Google Flights mostra as tarifas da própria LATAM (mesmo preço do site, normalmente) e, ao contrário
do site da LATAM, aceita consultas a partir de servidores como o GitHub Actions.
"""

from __future__ import annotations

import logging
from typing import Any

from .config import Config
from .fetch import FetchError, Fetcher

log = logging.getLogger(__name__)


class GoogleFlightsFetcher(Fetcher):
    def __init__(self, config: Config):
        super().__init__(config)
        try:
            from fli.search import SearchFlights
        except ImportError as exc:  # pragma: no cover
            raise FetchError("biblioteca do Google Flights não instalada: pip install flights") from exc
        self._client = SearchFlights()

    def offers(self, origin: str, dest: str, day: str, points: bool) -> list[dict[str, Any]]:
        if points:
            raise FetchError("o Google Flights não tem preço em pontos")
        from fli.models import (
            Airline, Airport, FlightSearchFilters, FlightSegment, MaxStops, PassengerInfo, SeatType,
        )

        seat = {"Economy": SeatType.ECONOMY, "Premium": SeatType.PREMIUM_ECONOMY,
                "Business": SeatType.BUSINESS}.get(self.config.cabin, SeatType.ECONOMY)
        filters = FlightSearchFilters(
            passenger_info=PassengerInfo(adults=self.config.adults),
            flight_segments=[FlightSegment(
                departure_airport=[[Airport[origin], 0]],
                arrival_airport=[[Airport[dest], 0]],
                travel_date=day,
            )],
            stops=MaxStops.NON_STOP if self.config.direct_only else MaxStops.ANY,
            seat_type=seat,
            airlines=[Airline["LA"]],
        )
        self._wait()
        try:
            results = self._client.search(filters, currency="BRL", language="pt-BR", country="BR") or []
        except Exception as exc:  # noqa: BLE001 - erro de rede/parsing da biblioteca
            raise FetchError(f"Google Flights: {exc}") from exc
        rows = []
        for r in results:
            if r.price is None:
                continue
            legs = r.legs or []
            if not legs or any(getattr(leg.airline, "name", "") != "LA" for leg in legs):
                continue  # só voos operados/vendidos pela LATAM
            rows.append({
                "flight": "+".join(f"LA{leg.flight_number}" for leg in legs),
                "depart": legs[0].departure_datetime.isoformat(),
                "arrive": legs[-1].arrival_datetime.isoformat(),
                "stops": r.stops,
                "duration": r.duration,
                "brand": "Google Flights",
                "price": float(r.price),
                "currency": (r.currency or "BRL").upper(),
                "taxes": None,
                "seats": "",
            })
        self._dump(f"{origin}-{dest}-{day}-google.txt", "\n".join(map(str, rows)) or "sem resultados")
        return rows

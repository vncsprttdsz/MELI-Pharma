"""Histórico em CSV: uma linha por tarifa vista (quotes.csv) e uma por execução (runs.csv)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

QUOTE_FIELDS = [
    "checked_at", "leg", "origin", "destination", "date", "mode",
    "flight", "depart", "arrive", "stops", "duration", "brand", "price", "currency", "taxes", "seats",
]
# status por busca: ok (com voo direto), no_direct (só voos com escala), no_offers, error
SEARCH_FIELDS = ["checked_at", "leg", "origin", "destination", "date", "mode", "status", "offers", "detail"]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def append_csv(path: Path, fields: list[str], rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


class Storage:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.quotes_path = data_dir / "quotes.csv"
        self.searches_path = data_dir / "searches.csv"

    def save(self, quotes: list[dict], searches: list[dict]) -> None:
        append_csv(self.quotes_path, QUOTE_FIELDS, quotes)
        append_csv(self.searches_path, SEARCH_FIELDS, searches)

    def quotes(self) -> list[dict[str, str]]:
        return read_csv(self.quotes_path)

    def searches(self) -> list[dict[str, str]]:
        return read_csv(self.searches_path)

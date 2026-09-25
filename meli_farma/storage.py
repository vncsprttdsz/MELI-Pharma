"""Persistência em CSV.

Estrutura em ``data/``:

- ``snapshots/AAAA-MM-DD.csv.gz``  lista completa de produtos coletados no dia
- ``history/runs.csv``             uma linha por coleta (quantidade total de produtos)
- ``history/categories.csv``       uma linha por (dia, categoria): quantidade e preços
- ``products.csv``                 cadastro de todos os produtos já vistos (primeira/última vez)

Rodar mais de uma vez no mesmo dia substitui os dados daquele dia.
"""

from __future__ import annotations

import csv
import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .parse import Product
from .scraper import PATH_SEP, ScrapeResult

SNAPSHOT_FIELDS = list(Product.__dataclass_fields__.keys())
RUN_FIELDS = [
    "date", "scraped_at", "products_scraped", "ml_reported_total",
    "categories_l1", "pages_fetched", "errors", "listing_url",
]
CATEGORY_FIELDS = [
    "date", "depth", "category", "products", "ml_reported",
    "price_avg", "price_median", "price_min", "price_max", "discounted",
]
PRODUCT_FIELDS = [
    "item_id", "title", "category_l1", "category_path", "brand", "first_seen",
    "last_seen", "active", "last_price", "url",
]
UNCATEGORIZED = "Sem categoria"
TZ = ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------- CSV helpers


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(tmp, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _fmt(row.get(k)) for k in fields})
    tmp.replace(path)


def _fmt(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def to_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


# ---------------------------------------------------------------- agregações


def category_prefixes(path: str) -> list[str]:
    parts = [p for p in path.split(PATH_SEP) if p] if path else []
    if not parts:
        return [UNCATEGORIZED]
    return [PATH_SEP.join(parts[: i + 1]) for i in range(len(parts))]


def aggregate_categories(
    date: str, products: list[dict[str, Any]], ml_counts: dict[str, int | None]
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in products:
        for prefix in category_prefixes(p.get("category_path") or ""):
            groups[prefix].append(p)
    for path in ml_counts:
        groups.setdefault(path, [])

    rows = []
    for cat in sorted(groups):
        items = groups[cat]
        prices = [v for v in (to_float(str(p.get("price") or "")) for p in items) if v is not None]
        discounted = sum(1 for p in items if to_float(str(p.get("original_price") or "")))
        rows.append(
            {
                "date": date,
                "depth": 0 if cat == UNCATEGORIZED else cat.count(PATH_SEP) + 1,
                "category": cat,
                "products": len(items),
                "ml_reported": ml_counts.get(cat),
                "price_avg": statistics.fmean(prices) if prices else None,
                "price_median": statistics.median(prices) if prices else None,
                "price_min": min(prices) if prices else None,
                "price_max": max(prices) if prices else None,
                "discounted": discounted,
            }
        )
    return rows


# ---------------------------------------------------------------- gravação


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.snapshots = self.data_dir / "snapshots"
        self.history = self.data_dir / "history"

    def snapshot_path(self, date: str) -> Path:
        return self.snapshots / f"{date}.csv.gz"

    def snapshot_dates(self) -> list[str]:
        if not self.snapshots.exists():
            return []
        return sorted(p.name.removesuffix(".csv.gz") for p in self.snapshots.glob("*.csv.gz"))

    def load_snapshot(self, date: str) -> list[dict[str, str]]:
        return read_csv(self.snapshot_path(date))

    def save(self, result: ScrapeResult) -> str:
        date = result.scraped_at.astimezone(TZ).date().isoformat()
        rows = [p.to_row() for p in result.products.values()]
        rows.sort(key=lambda r: (r["category_path"], r["title"]))
        write_csv(self.snapshot_path(date), SNAPSHOT_FIELDS, rows)

        ml_counts = {c.path: c.reported for c in result.categories}
        l1 = {c.path for c in result.categories if c.depth == 1}
        self._upsert(
            self.history / "runs.csv",
            RUN_FIELDS,
            [
                {
                    "date": date,
                    "scraped_at": result.scraped_at.isoformat(timespec="seconds"),
                    "products_scraped": len(rows),
                    "ml_reported_total": result.total_reported,
                    "categories_l1": len(l1),
                    "pages_fetched": result.pages_fetched,
                    "errors": len(result.errors),
                    "listing_url": result.listing_url,
                }
            ],
            date,
        )
        self._upsert(
            self.history / "categories.csv",
            CATEGORY_FIELDS,
            aggregate_categories(date, rows, ml_counts),
            date,
        )
        self._update_products(date, rows)
        (self.history / "last_run_errors.json").write_text(
            json.dumps({"date": date, "errors": result.errors}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return date

    def _upsert(self, path: Path, fields: list[str], new_rows: list[dict[str, Any]], date: str) -> None:
        rows = [r for r in read_csv(path) if r["date"] != date] + new_rows
        rows.sort(key=lambda r: r["date"])
        write_csv(path, fields, rows)

    def _update_products(self, date: str, rows: list[dict[str, Any]]) -> None:
        path = self.data_dir / "products.csv"
        master = {r["item_id"]: r for r in read_csv(path)}
        current = {r["item_id"] for r in rows}
        for r in rows:
            entry = master.get(r["item_id"], {"item_id": r["item_id"], "first_seen": date})
            if entry.get("first_seen", date) > date:
                entry["first_seen"] = date
            entry.update(
                {
                    "title": r["title"],
                    "category_l1": category_prefixes(r["category_path"])[0],
                    "category_path": r["category_path"],
                    "brand": r["brand"],
                    "last_seen": max(date, entry.get("last_seen") or date),
                    "last_price": r["price"],
                    "url": r["url"],
                }
            )
            master[r["item_id"]] = entry
        latest = max([date] + [m.get("last_seen", "") for m in master.values()])
        for item_id, entry in master.items():
            entry["active"] = "1" if entry.get("last_seen") == latest else "0"
            if latest == date and item_id not in current:
                entry["active"] = "0"
        write_csv(path, PRODUCT_FIELDS, sorted(master.values(), key=lambda r: r["item_id"]))

"""Comparação entre coletas, resumo em Markdown e dashboard HTML estático (docs/index.html)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import PATH_SEP, Storage, category_prefixes, read_csv, to_float

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
MAX_SERIES = 7  # categorias com linha própria no gráfico; o resto vira "Outras"
MAX_CHANGES = 300


@dataclass
class Diff:
    date: str
    previous: str | None
    added: list[dict[str, str]] = field(default_factory=list)
    removed: list[dict[str, str]] = field(default_factory=list)
    price_changes: list[dict[str, Any]] = field(default_factory=list)


def compare(storage: Storage, date: str | None = None) -> Diff | None:
    dates = storage.snapshot_dates()
    if not dates:
        return None
    date = date or dates[-1]
    idx = dates.index(date)
    prev = dates[idx - 1] if idx > 0 else None
    cur_rows = {r["item_id"]: r for r in storage.load_snapshot(date)}
    diff = Diff(date=date, previous=prev)
    if prev is None:
        return diff
    prev_rows = {r["item_id"]: r for r in storage.load_snapshot(prev)}
    diff.added = [cur_rows[i] for i in cur_rows.keys() - prev_rows.keys()]
    diff.removed = [prev_rows[i] for i in prev_rows.keys() - cur_rows.keys()]
    for item_id in cur_rows.keys() & prev_rows.keys():
        old = to_float(prev_rows[item_id]["price"])
        new = to_float(cur_rows[item_id]["price"])
        if old and new and abs(new - old) >= 0.01:
            diff.price_changes.append(
                {**cur_rows[item_id], "old_price": old, "new_price": new, "change_pct": (new - old) / old * 100}
            )
    diff.added.sort(key=lambda r: (r["category_path"], r["title"]))
    diff.removed.sort(key=lambda r: (r["category_path"], r["title"]))
    diff.price_changes.sort(key=lambda r: -abs(r["change_pct"]))
    return diff


def _brl(v: float | None) -> str:
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def markdown_summary(storage: Storage) -> str:
    runs = read_csv(storage.history / "runs.csv")
    if not runs:
        return "Nenhuma coleta registrada ainda."
    last = runs[-1]
    prev = runs[-2] if len(runs) > 1 else None
    lines = [f"## MELI Farma — coleta de {last['date']}", ""]
    n = int(last["products_scraped"])
    delta = f" ({n - int(prev['products_scraped']):+d} vs {prev['date']})" if prev else ""
    lines.append(f"- **Produtos coletados:** {n}{delta}")
    if last["ml_reported_total"]:
        lines.append(f"- **Total informado pelo Mercado Livre:** {last['ml_reported_total']}")
    lines.append(f"- **Páginas baixadas:** {last['pages_fetched']} · **avisos/erros:** {last['errors']}")

    cats = [r for r in read_csv(storage.history / "categories.csv") if r["date"] == last["date"] and r["depth"] in ("0", "1")]
    prev_cats = {
        r["category"]: int(r["products"])
        for r in read_csv(storage.history / "categories.csv")
        if prev and r["date"] == prev["date"] and r["depth"] in ("0", "1")
    }
    if cats:
        lines += ["", "| Categoria | Produtos | Δ | Preço mediano |", "|---|---:|---:|---:|"]
        for r in sorted(cats, key=lambda r: -int(r["products"])):
            p = int(r["products"])
            d = f"{p - prev_cats[r['category']]:+d}" if r["category"] in prev_cats else "novo" if prev else ""
            lines.append(f"| {r['category']} | {p} | {d} | {_brl(to_float(r['price_median']))} |")

    diff = compare(storage)
    if diff and diff.previous:
        lines += [
            "",
            f"**Desde {diff.previous}:** {len(diff.added)} novos, {len(diff.removed)} removidos, "
            f"{len(diff.price_changes)} com preço alterado.",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- dashboard


def _category_history(cat_rows: list[dict[str, str]], dates: list[str], depth: str) -> dict[str, Any]:
    by_cat: dict[str, dict[str, int]] = defaultdict(dict)
    for r in cat_rows:
        if r["depth"] == depth or (depth == "1" and r["depth"] == "0"):
            by_cat[r["category"]][r["date"]] = int(r["products"])
    last = dates[-1] if dates else None
    ranked = sorted(by_cat, key=lambda c: -by_cat[c].get(last, 0))
    top, rest = ranked[:MAX_SERIES], ranked[MAX_SERIES:]
    series = [{"name": c, "values": [by_cat[c].get(d, 0) for d in dates]} for c in top]
    if rest:
        series.append(
            {"name": f"Outras ({len(rest)})", "values": [sum(by_cat[c].get(d, 0) for c in rest) for d in dates]}
        )
    return {"dates": dates, "series": series}


def _slim(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["item_id"],
        "t": row["title"],
        "c": row.get("category_path") or "",
        "p": to_float(str(row.get("price") or "")),
        "o": to_float(str(row.get("original_price") or "")),
        "u": row.get("url") or "",
    }


def build_dashboard_data(storage: Storage) -> dict[str, Any]:
    runs = read_csv(storage.history / "runs.csv")
    cat_rows = read_csv(storage.history / "categories.csv")
    dates = [r["date"] for r in runs]
    last = dates[-1] if dates else None
    prev = dates[-2] if len(dates) > 1 else None

    def cats_for(d: str | None) -> dict[str, dict[str, str]]:
        return {r["category"]: r for r in cat_rows if r["date"] == d}

    cur_cats, prev_cats = cats_for(last), cats_for(prev)
    current = []
    for name, r in cur_cats.items():
        p = prev_cats.get(name)
        current.append(
            {
                "name": name,
                "depth": int(r["depth"]),
                "products": int(r["products"]),
                "prev": int(p["products"]) if p else None,
                "ml": int(r["ml_reported"]) if r["ml_reported"] else None,
                "median": to_float(r["price_median"]),
                "avg": to_float(r["price_avg"]),
                "discounted": int(r["discounted"] or 0),
            }
        )

    products = [_slim(r) for r in storage.load_snapshot(last)] if last else []
    diff = compare(storage)
    changes = None
    if diff and diff.previous:
        changes = {
            "previous": diff.previous,
            "added_n": len(diff.added),
            "removed_n": len(diff.removed),
            "price_n": len(diff.price_changes),
            "added": [_slim(r) for r in diff.added[:MAX_CHANGES]],
            "removed": [_slim(r) for r in diff.removed[:MAX_CHANGES]],
            "price": [
                {**_slim(r), "op": r["old_price"], "np": r["new_price"], "pct": round(r["change_pct"], 1)}
                for r in diff.price_changes[:MAX_CHANGES]
            ],
        }

    max_depth = max((c["depth"] for c in current), default=1)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "last": last,
        "prev": prev,
        "runs": [
            {
                "date": r["date"],
                "products": int(r["products_scraped"]),
                "ml": int(r["ml_reported_total"]) if r["ml_reported_total"] else None,
            }
            for r in runs
        ],
        "history": {str(d): _category_history(cat_rows, dates, str(d)) for d in range(1, max_depth + 1)},
        "categories": current,
        "changes": changes,
        "products": products,
        "sep": PATH_SEP,
    }


def write_dashboard(storage: Storage, docs_dir: Path) -> Path:
    data = build_dashboard_data(storage)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


__all__ = ["compare", "markdown_summary", "build_dashboard_data", "write_dashboard", "category_prefixes"]

"""Análise do histórico: melhor tarifa por data, combinações ida+volta, alertas e dashboard HTML."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Config, date_window

BRT = timezone(timedelta(hours=-3))
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
TEMPLATE = Path(__file__).with_name("dashboard_template.html")

Key = tuple[str, str, str]  # (trecho, data, modo)


def _f(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def local_time(checked_at: str) -> str:
    try:
        dt = datetime.strptime(checked_at, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return checked_at
    return dt.astimezone(BRT).strftime("%d/%m %H:%M")


def day_label(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{WEEKDAYS[d.weekday()]} {d:%d/%m}"


def fmt_price(value: float | None, mode: str, currency: str = "BRL") -> str:
    if value is None:
        return "—"
    n = f"{value:,.0f}".replace(",", ".")
    if mode == "points":
        return f"{n} pts"
    return f"R$ {n}" if currency in ("BRL", "") else f"{currency} {n}"


def fmt_taxes(value: float | None) -> str:
    if not value:
        return ""
    return " + R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def best_by_run(quotes: list[dict]) -> dict[str, dict[Key, dict]]:
    """{checked_at: {(trecho, data, modo): tarifa mais barata}}."""
    out: dict[str, dict[Key, dict]] = defaultdict(dict)
    for q in quotes:
        price = _f(q.get("price"))
        if price is None:
            continue
        key = (q["leg"], q["date"], q["mode"])
        cur = out[q["checked_at"]].get(key)
        if cur is None or price < _f(cur["price"]):
            out[q["checked_at"]][key] = q
    return dict(out)


def search_status(searches: list[dict], checked_at: str) -> dict[Key, dict]:
    return {(s["leg"], s["date"], s["mode"]): s for s in searches if s["checked_at"] == checked_at}


def combos(best: dict[Key, dict], config: Config, mode: str) -> list[dict]:
    rows = []
    for out_day in date_window(config.outbound, config.flex_days):
        for in_day in date_window(config.inbound, config.flex_days):
            a, b = best.get(("ida", out_day, mode)), best.get(("volta", in_day, mode))
            if not a or not b:
                continue
            rows.append({
                "out": out_day, "in": in_day, "mode": mode,
                "price": _f(a["price"]) + _f(b["price"]),
                "taxes": (_f(a.get("taxes")) or 0) + (_f(b.get("taxes")) or 0),
                "currency": a.get("currency") or "",
                "flights": f"{a['flight']} / {b['flight']}",
                "nights": (datetime.fromisoformat(in_day) - datetime.fromisoformat(out_day)).days,
            })
    # Empate de preço: o voo ideal (datas centrais) vem primeiro.
    return sorted(rows, key=lambda r: (r["price"], (r["out"], r["in"]) != (config.outbound, config.inbound)))


def alerts(prev: dict[Key, dict], cur: dict[Key, dict], pct: float, all_time_low: dict[Key, float]) -> list[str]:
    msgs = []
    for key, q in sorted(cur.items()):
        leg, day, mode = key
        price = _f(q["price"])
        label = f"{leg} {day_label(day)} ({'pontos' if mode == 'points' else 'dinheiro'})"
        before = _f(prev[key]["price"]) if key in prev else None
        if before and price < before * (1 - pct / 100):
            msgs.append(f"⬇️ {label}: {fmt_price(before, mode)} → {fmt_price(price, mode)} ({q['flight']} {q['brand']})")
        low = all_time_low.get(key)
        if low is not None and price < low and not (before and price < before * (1 - pct / 100)):
            msgs.append(f"🏆 {label}: menor preço já visto, {fmt_price(price, mode)}")
    return msgs


def ideal_combo(rows: list[dict], config: Config) -> dict | None:
    """Combinação das datas centrais (a viagem ideal: ``LATAM_OUTBOUND`` + ``LATAM_INBOUND``)."""
    return next((r for r in rows if r["out"] == config.outbound and r["in"] == config.inbound), None)


def ideal_summary(config: Config, history: list[dict], combos_now: dict[str, list[dict]]) -> dict[str, dict]:
    """Por modo: preço atual do voo ideal, consulta anterior, mínimo histórico e diferença para o mais barato."""
    out = {}
    for mode in config.modes:
        cur = ideal_combo(combos_now[mode], config)
        series = [(h["label"], h.get(f"ideal|{mode}")) for h in history]
        seen = [(label, v) for label, v in series if v is not None]
        prev = seen[-2][1] if cur and len(seen) > 1 else (seen[-1][1] if not cur and seen else None)
        low = min(seen, key=lambda x: x[1]) if seen else None
        cheapest = combos_now[mode][0] if combos_now[mode] else None
        out[mode] = {
            "current": cur,
            "previous": prev,
            "low": low[1] if low else None,
            "low_label": low[0] if low else "",
            "cheapest": cheapest,
        }
    return out


def analyze(config: Config, quotes: list[dict], searches: list[dict]) -> dict[str, Any]:
    runs = best_by_run(quotes)
    checks = sorted({s["checked_at"] for s in searches})
    latest = checks[-1] if checks else None
    previous = checks[-2] if len(checks) > 1 else None
    best = runs.get(latest, {}) if latest else {}
    prev_best = runs.get(previous, {}) if previous else {}
    low: dict[Key, float] = {}
    low_when: dict[Key, str] = {}
    for when, rows in runs.items():
        if when == latest:
            continue
        for key, q in rows.items():
            if key not in low or _f(q["price"]) < low[key]:
                low[key], low_when[key] = _f(q["price"]), when
    history = []
    for when in checks:
        entry: dict[str, Any] = {"t": when, "label": local_time(when)}
        for mode in config.modes:
            c = combos(runs.get(when, {}), config, mode)
            entry[mode] = c[0]["price"] if c else None
            ideal = ideal_combo(c, config)
            entry[f"ideal|{mode}"] = ideal["price"] if ideal else None
            for key, q in runs.get(when, {}).items():
                if key[2] == mode:
                    entry[f"{key[0]}|{key[1]}|{mode}"] = _f(q["price"])
        history.append(entry)
    combos_now = {m: combos(best, config, m) for m in config.modes}
    ideal = ideal_summary(config, history, combos_now)
    found_alerts = alerts(prev_best, best, config.alert_drop_pct, low) if previous else []
    for mode, i in ideal.items():
        cur, prev = i["current"], i["previous"]
        if cur and prev and cur["price"] < prev * (1 - config.alert_drop_pct / 100):
            found_alerts.insert(0, f"⭐ Voo ideal ({'pontos' if mode == 'points' else 'dinheiro'}): "
                                   f"{fmt_price(prev, mode)} → {fmt_price(cur['price'], mode)}")
    return {
        "latest": latest,
        "best": best,
        "status": search_status(searches, latest) if latest else {},
        "combos": combos_now,
        "ideal": ideal,
        "alerts": found_alerts,
        "low": low,
        "low_when": low_when,
        "history": history,
        "checks": len(checks),
    }


STATUS_TEXT = {"no_direct": "sem voo direto", "no_offers": "sem oferta", "error": "falhou"}


def markdown_summary(config: Config, a: dict[str, Any]) -> str:
    if not a["latest"]:
        return "Nenhuma consulta registrada ainda."
    lines = [f"## LATAM {config.origin} ⇄ {config.destination} — consulta de {local_time(a['latest'])} (Brasília)", ""]
    if a["alerts"]:
        lines += ["**Alertas**", ""] + [f"- {m}" for m in a["alerts"]] + [""]
    for mode in config.modes:
        i = a["ideal"][mode]
        title = "Dinheiro" if mode == "cash" else "Pontos LATAM Pass"
        label = f"ida {day_label(config.outbound)} + volta {day_label(config.inbound)}"
        if i["current"]:
            cur = i["current"]
            lines.append(f"**⭐ Voo ideal ({label}) — {title}: {fmt_price(cur['price'], mode, cur['currency'])}"
                         f"{fmt_taxes(cur['taxes']) if mode == 'points' else ''}** ({cur['flights']})")
        else:
            lines.append(f"**⭐ Voo ideal ({label}) — {title}:** sem voo direto disponível nas duas datas.")
    lines.append("")
    for mode in config.modes:
        c = a["combos"][mode]
        title = "Dinheiro" if mode == "cash" else "Pontos LATAM Pass"
        if c:
            top = c[0]
            lines.append(f"**{title}:** melhor ida+volta {fmt_price(top['price'], mode, top['currency'])}"
                         f"{fmt_taxes(top['taxes']) if mode == 'points' else ''} — "
                         f"ida {day_label(top['out'])}, volta {day_label(top['in'])} ({top['flights']})")
        else:
            lines.append(f"**{title}:** nenhuma combinação ida+volta com voo direto disponível.")
    lines += ["", "| Trecho | Data | Dinheiro | Pontos |", "|---|---|---|---|"]
    for leg, _o, _d, day in config.legs():
        cells = []
        for mode in ("cash", "points"):
            q = a["best"].get((leg, day, mode))
            st = a["status"].get((leg, day, mode))
            if q:
                cells.append(fmt_price(_f(q["price"]), mode, q.get("currency", "")) + (fmt_taxes(_f(q.get("taxes"))) if mode == "points" else ""))
            elif mode not in config.modes:
                cells.append("")
            else:
                cells.append(STATUS_TEXT.get(st["status"], "—") if st else "—")
        lines.append(f"| {leg} | {day_label(day)} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines)


def write_dashboard(config: Config, a: dict[str, Any]) -> Path:
    def cell(leg: str, day: str, mode: str) -> str:
        q = a["best"].get((leg, day, mode))
        if not q:
            st = a["status"].get((leg, day, mode))
            return f'<td class="muted">{STATUS_TEXT.get(st["status"], "—") if st else "—"}</td>'
        price = _f(q["price"])
        low = a["low"].get((leg, day, mode))
        badge = ' <span class="badge">mínimo</span>' if low is None or price <= low else ""
        extra = html.escape(fmt_taxes(_f(q.get("taxes")))) if mode == "points" else ""
        return (f'<td><b>{html.escape(fmt_price(price, mode, q.get("currency", "")))}</b>{extra}{badge}'
                f'<div class="sub">{html.escape(q["flight"])} · {html.escape(q["brand"])} · '
                f'{html.escape(q["depart"][11:16])}</div></td>')

    ideal_days = {("ida", config.outbound), ("volta", config.inbound)}
    star = ' <span class="tag">ideal</span>'
    legs_rows = []
    for leg, o, d, day in config.legs():
        is_ideal = (leg, day) in ideal_days
        legs_rows.append(f"<tr{' class=ideal' if is_ideal else ''}><td>{leg} {o}→{d}</td>"
                         f"<td>{day_label(day)}{star if is_ideal else ''}</td>"
                         + "".join(cell(leg, day, m) for m in ("cash", "points") if m in config.modes) + "</tr>")
    combo_tables = []
    for mode in config.modes:
        rows = a["combos"][mode][:9]
        body = "".join(
            f"<tr{' class=ideal' if r['out'] == config.outbound and r['in'] == config.inbound else ''}>"
            f"<td>{day_label(r['out'])}</td><td>{day_label(r['in'])}"
            f"{star if r['out'] == config.outbound and r['in'] == config.inbound else ''}</td><td>{r['nights']}</td>"
            f"<td><b>{html.escape(fmt_price(r['price'], mode, r['currency']))}</b>"
            f"{html.escape(fmt_taxes(r['taxes'])) if mode == 'points' else ''}</td>"
            f"<td class='sub'>{html.escape(r['flights'])}</td></tr>"
            for r in rows
        ) or '<tr><td colspan="5" class="muted">Nenhuma combinação com voo direto nas duas pernas.</td></tr>'
        title = "Dinheiro" if mode == "cash" else "Pontos LATAM Pass"
        combo_tables.append(
            f"<section><h2>Ida + volta — {title}</h2><div class='scroll'><table><thead><tr><th>Ida</th><th>Volta</th>"
            f"<th>Noites</th><th>Total</th><th>Voos</th></tr></thead><tbody>{body}</tbody></table></div></section>"
        )
    cards = []
    for mode in config.modes:
        i = a["ideal"][mode]
        cur = i["current"]
        title = "Dinheiro" if mode == "cash" else "Pontos LATAM Pass"
        if not cur:
            cards.append(f"<div class='hero-item'><div class='sub'>{title}</div>"
                         f"<div class='big muted'>sem voo direto</div></div>")
            continue
        facts = []
        if i["previous"] is not None:
            delta = cur["price"] - i["previous"]
            if abs(delta) < 0.5:
                facts.append("igual à consulta anterior")
            else:
                arrow, cls = ("▼", "down") if delta < 0 else ("▲", "up")
                facts.append(f"<span class='{cls}'>{arrow} {html.escape(fmt_price(abs(delta), mode))}</span> "
                             "desde a consulta anterior")
        if i["low"] is not None:
            facts.append("menor valor já registrado" if cur["price"] <= i["low"]
                         else f"mínimo: {html.escape(fmt_price(i['low'], mode))} em {html.escape(i['low_label'])}")
        cheap = i["cheapest"]
        if cheap and cheap["price"] < cur["price"]:
            facts.append(f"{html.escape(fmt_price(cur['price'] - cheap['price'], mode))} acima da combinação mais "
                         f"barata ({day_label(cheap['out'])} + {day_label(cheap['in'])})")
        elif any(r["price"] == cur["price"] and r is not cur for r in a["combos"][mode]):
            facts.append("empatado com a combinação mais barata")
        elif cheap:
            facts.append("é a combinação mais barata agora")
        cards.append(
            f"<div class='hero-item'><div class='sub'>{title} · ida + volta</div>"
            f"<div class='big'>{html.escape(fmt_price(cur['price'], mode, cur['currency']))}"
            f"{html.escape(fmt_taxes(cur['taxes'])) if mode == 'points' else ''}</div>"
            f"<div class='sub'>{html.escape(cur['flights'])}</div>"
            + "".join(f"<div class='fact'>{f}</div>" for f in facts) + "</div>"
        )
    ideal_html = (f"<section class='hero'><h2>⭐ Voo ideal: ida {day_label(config.outbound)} + volta "
                  f"{day_label(config.inbound)}</h2><div class='hero-grid'>{''.join(cards)}</div></section>")
    mode_heads = "".join(f"<th>{'Dinheiro' if m == 'cash' else 'Pontos'}</th>" for m in ("cash", "points") if m in config.modes)
    alerts_html = "".join(f"<li>{html.escape(m)}</li>" for m in a["alerts"])
    page = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "__TITLE__": f"LATAM {config.origin} ⇄ {config.destination}",
        "__SUBTITLE__": (f"Voos diretos · ida {day_label(config.outbound)} e volta {day_label(config.inbound)} "
                         f"(±{config.flex_days} dia) · {config.adults} adulto(s) · {config.cabin}"),
        "__UPDATED__": local_time(a["latest"]) if a["latest"] else "—",
        "__CHECKS__": str(a["checks"]),
        "__ALERTS__": f"<ul class='alerts'>{alerts_html}</ul>" if alerts_html else "",
        "__IDEAL__": ideal_html,
        "__CHARTS__": "".join(
            f'<div><h2 class="sub">{"Dinheiro (R$)" if m == "cash" else "Pontos"}</h2>'
            f'<div class="chart"><canvas id="c-{m}"></canvas></div></div>' for m in config.modes),
        "__MODE_HEADS__": mode_heads,
        "__LEG_ROWS__": "".join(legs_rows),
        "__COMBOS__": "".join(combo_tables),
        "__DATA__": json.dumps({"history": a["history"], "modes": config.modes,
                                "idealLabel": f"Voo ideal ({day_label(config.outbound)} + {day_label(config.inbound)})",
                                "series": [f"{leg}|{day}|{m}" for leg, _o, _d, day in config.legs() for m in config.modes],
                                "labels": {f"{leg}|{day}": f"{leg} {day_label(day)}" for leg, _o, _d, day in config.legs()}},
                               ensure_ascii=False).replace("</", "<\\/"),
    }
    for k, v in replacements.items():
        page = page.replace(k, v)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(page, encoding="utf-8")
    return config.report_path

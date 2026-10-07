"""Coleta: busca cada trecho/data em dinheiro e em pontos e grava as tarifas de voos diretos."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config
from .fetch import FetchError, Fetcher
from .parse import is_points

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    checked_at: str
    quotes: list[dict] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)

    @property
    def failed(self) -> list[dict]:
        return [s for s in self.searches if s["status"] == "error"]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def run(config: Config, fetchers: Fetcher | dict[str, Fetcher], checked_at: str | None = None) -> RunResult:
    """``fetchers``: um por modo ({"cash": ..., "points": ...}) ou o mesmo para todos."""
    result = RunResult(checked_at=checked_at or now_utc())
    for leg, origin, dest, day in config.legs():
        for mode in config.modes:
            fetcher = fetchers[mode] if isinstance(fetchers, dict) else fetchers
            points = mode == "points"
            base = {"checked_at": result.checked_at, "leg": leg, "origin": origin,
                    "destination": dest, "date": day, "mode": mode}
            try:
                offers = fetcher.offers(origin, dest, day, points)
            except FetchError as exc:
                log.error("%s %s→%s %s (%s): %s", leg, origin, dest, day, mode, exc)
                result.searches.append({**base, "status": "error", "offers": 0, "detail": str(exc)[:300]})
                continue
            # Busca em pontos devolve pontos; em dinheiro, a moeda do país. Descarta o que não bate.
            offers = [o for o in offers if is_points(o["currency"]) == points or not o["currency"]]
            direct = [o for o in offers if o["stops"] == 0] if config.direct_only else offers
            status = "ok" if direct else ("no_direct" if offers else "no_offers")
            log.info("%s %s→%s %s (%s): %d tarifas, %d diretas", leg, origin, dest, day, mode, len(offers), len(direct))
            result.searches.append({**base, "status": status, "offers": len(offers), "detail": ""})
            result.quotes.extend({**base, **o} for o in direct)
    return result

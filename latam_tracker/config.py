"""Configuração da viagem monitorada (variáveis de ambiente com padrões da viagem GRU ⇄ LAX)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def date_window(center: str, flex: int) -> list[str]:
    """Datas de ``center - flex`` a ``center + flex`` (ISO)."""
    c = date.fromisoformat(center)
    return [(c + timedelta(days=d)).isoformat() for d in range(-flex, flex + 1)]


@dataclass
class Config:
    origin: str = "GRU"
    destination: str = "LAX"
    outbound: str = "2027-04-01"
    inbound: str = "2027-04-10"
    flex_days: int = 1
    adults: int = 1
    cabin: str = "Economy"  # Economy | Premium | Business (nomes usados no site)
    direct_only: bool = True
    modes: list[str] = field(default_factory=lambda: ["cash", "points"])
    cash_source: str = "google"  # google (Google Flights) | latam (site da LATAM)
    site_country: str = "br"
    site_lang: str = "pt"
    fetcher: str = "browser"  # browser (Playwright) | api (requisição direta à API do site)
    delay: float = 8.0
    timeout: float = 60.0
    data_dir: Path = Path("data/latam")
    report_path: Path = Path("docs/latam.html")
    debug_dir: Path | None = None
    ntfy_topic: str = ""
    alert_drop_pct: float = 3.0
    headless: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        debug = os.environ.get("LATAM_DEBUG_DIR", "").strip()
        return cls(
            origin=_env("LATAM_ORIGIN", "GRU").upper(),
            destination=_env("LATAM_DESTINATION", "LAX").upper(),
            outbound=_env("LATAM_OUTBOUND", "2027-04-01"),
            inbound=_env("LATAM_INBOUND", "2027-04-10"),
            flex_days=int(_env("LATAM_FLEX_DAYS", "1")),
            adults=int(_env("LATAM_ADULTS", "1")),
            cabin=_env("LATAM_CABIN", "Economy"),
            direct_only=_env("LATAM_DIRECT_ONLY", "1") not in ("0", "false", "no"),
            # Pontos fica desligado por padrão: o site da LATAM bloqueia servidores e exige login para pontos.
            modes=[m.strip() for m in _env("LATAM_MODES", "cash").split(",") if m.strip()],
            cash_source=_env("LATAM_CASH_SOURCE", "google"),
            fetcher=_env("LATAM_FETCHER", "browser"),
            delay=float(_env("LATAM_DELAY", "8")),
            timeout=float(_env("LATAM_TIMEOUT", "60")),
            data_dir=Path(_env("LATAM_DATA_DIR", "data/latam")),
            report_path=Path(_env("LATAM_REPORT", "docs/latam.html")),
            debug_dir=Path(debug) if debug else None,
            ntfy_topic=_env("LATAM_NTFY_TOPIC", ""),
            alert_drop_pct=float(_env("LATAM_ALERT_DROP_PCT", "3")),
            headless=_env("LATAM_HEADLESS", "1") not in ("0", "false", "no"),
        )

    def legs(self) -> list[tuple[str, str, str, str]]:
        """(trecho, origem, destino, data) de cada busca só de ida que compõe a viagem."""
        out = [("ida", self.origin, self.destination, d) for d in date_window(self.outbound, self.flex_days)]
        back = [("volta", self.destination, self.origin, d) for d in date_window(self.inbound, self.flex_days)]
        return out + back

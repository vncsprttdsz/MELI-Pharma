"""Consulta ao site da LATAM: abre a página de resultados e captura o JSON de ofertas.

Dois modos (``LATAM_FETCHER``):

- ``browser`` (padrão): Chromium via Playwright abre a mesma URL que o site usa ao buscar voos e
  intercepta a resposta de ``/bff/air-offers/.../offers/search``. É o que mais se parece com um
  usuário e passa pela proteção anti-robô na maioria das redes residenciais.
- ``api``: chama a mesma API direto com ``requests``. Mais leve (roda no Termux), mas costuma
  ser bloqueada pelo anti-robô.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from .config import Config

log = logging.getLogger(__name__)

BASE = "https://www.latamairlines.com"
API_PATH = "/bff/air-offers/v2/offers/search"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


class FetchError(RuntimeError):
    """Não foi possível obter a resposta de ofertas (bloqueio, timeout, layout novo...)."""


def search_page_url(config: Config, origin: str, dest: str, day: str, points: bool) -> str:
    q = {
        "origin": origin,
        "outbound": f"{day}T15:00:00.000Z",
        "destination": dest,
        "inbound": "null",
        "adt": config.adults,
        "chd": 0,
        "inf": 0,
        "trip": "OW",
        "cabin": config.cabin,
        "redemption": "true" if points else "false",
        "sort": "RECOMMENDED",
    }
    return f"{BASE}/{config.site_country}/{config.site_lang}/oferta-voos?{urlencode(q)}"


def api_params(config: Config, origin: str, dest: str, day: str, points: bool) -> dict[str, Any]:
    return {
        "sort": "RECOMMENDED",
        "cabinType": config.cabin,
        "origin": origin,
        "destination": dest,
        "inFlightDate": "null",
        "inFrom": "null",
        "inOfferId": "null",
        "outFlightDate": "null",
        "outFrom": day,
        "outOfferId": "null",
        "adult": config.adults,
        "child": 0,
        "infant": 0,
        "redemption": "true" if points else "false",
    }


def _looks_like_offers(payload: Any) -> bool:
    return isinstance(payload, dict) and ("content" in payload or "brands" in json.dumps(payload)[:200000])


class Fetcher:
    def __init__(self, config: Config):
        self.config = config
        self._last = 0.0

    def _wait(self) -> None:
        delay = self.config.delay * (1 + random.random() * 0.5)
        elapsed = time.monotonic() - self._last
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last = time.monotonic()

    def _dump(self, name: str, content: str) -> None:
        if not self.config.debug_dir:
            return
        self.config.debug_dir.mkdir(parents=True, exist_ok=True)
        (self.config.debug_dir / name).write_text(content, encoding="utf-8")

    def search(self, origin: str, dest: str, day: str, points: bool) -> Any:
        """JSON da busca só de ida ``origin → dest`` em ``day``."""
        raise NotImplementedError

    def offers(self, origin: str, dest: str, day: str, points: bool) -> list[dict[str, Any]]:
        """Tarifas reconhecidas na busca (todas, com ou sem escala)."""
        from .parse import extract_offers

        return extract_offers(self.search(origin, dest, day, points))

    def close(self) -> None:
        pass


def proxy_settings() -> dict[str, str] | None:
    """``LATAM_PROXY`` (ex.: ``http://usuario:senha@host:porta``) no formato do Playwright."""
    from urllib.parse import urlsplit

    raw = os.environ.get("LATAM_PROXY", "").strip()
    if not raw:
        return None
    u = urlsplit(raw)
    out = {"server": f"{u.scheme}://{u.hostname}:{u.port}" if u.port else f"{u.scheme}://{u.hostname}"}
    if u.username:
        out["username"] = u.username
        out["password"] = u.password or ""
    return out


class BrowserFetcher(Fetcher):
    """Navegador real. ``LATAM_ENGINE``: ``chromium`` (Playwright), ``patchright`` (Chromium com
    correções anti-detecção) ou ``camoufox`` (Firefox anti-detecção)."""

    def __init__(self, config: Config):
        super().__init__(config)
        self.engine = os.environ.get("LATAM_ENGINE", "chromium").strip() or "chromium"
        proxy = proxy_settings()
        self._closers = []
        try:
            if self.engine == "camoufox":
                from camoufox.sync_api import Camoufox

                kwargs = {"headless": config.headless, "humanize": True, "locale": "pt-BR", "os": "windows"}
                if proxy:
                    kwargs.update(proxy=proxy, geoip=True)
                cm = Camoufox(**kwargs)
                self._browser = cm.__enter__()
                self._closers.append(lambda: cm.__exit__(None, None, None))
                self._context = self._browser.new_context()
            else:
                if self.engine == "patchright":
                    from patchright.sync_api import sync_playwright
                else:
                    from playwright.sync_api import sync_playwright
                pw = sync_playwright().start()
                self._closers.append(pw.stop)
                launch = {"headless": config.headless, "proxy": proxy}
                if self.engine == "patchright":
                    launch["channel"] = os.environ.get("LATAM_BROWSER_CHANNEL") or None
                else:
                    # LATAM_BROWSER_PATH: usar um Chrome/Chromium já instalado em vez do baixado pelo Playwright
                    launch["executable_path"] = os.environ.get("LATAM_BROWSER_PATH") or None
                    launch["args"] = ["--disable-blink-features=AutomationControlled"]
                self._browser = pw.chromium.launch(**launch)
                ctx = {"locale": "pt-BR", "timezone_id": "America/Sao_Paulo", "viewport": {"width": 1366, "height": 860}}
                if self.engine == "chromium":
                    ctx["user_agent"] = UA
                self._context = self._browser.new_context(**ctx)
                if self.engine == "chromium":
                    self._context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except ImportError as exc:  # pragma: no cover
            raise FetchError(f"motor '{self.engine}' não instalado: {exc}") from exc
        self._closers[:0] = [self._context.close, self._browser.close]
        self._page = self._context.new_page()
        self._warm = False

    def _humanize(self) -> None:
        """Movimentos de mouse e rolagem: o script anti-robô do site avalia interação antes de liberar a API."""
        pg = self._page
        for _ in range(6):
            pg.mouse.move(200 + random.random() * 900, 150 + random.random() * 500, steps=8)
            pg.wait_for_timeout(200 + random.random() * 400)
        pg.mouse.wheel(0, 400 + random.random() * 400)
        pg.wait_for_timeout(800)
        pg.mouse.wheel(0, -300)

    def _warmup(self) -> None:
        if self._warm:
            return
        self._warm = True
        try:
            self._page.goto(f"{BASE}/{self.config.site_country}/{self.config.site_lang}", timeout=self.config.timeout * 1000)
            try:
                self._page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:  # noqa: BLE001
                pass
            self._humanize()
            self._page.wait_for_timeout(4000 + random.random() * 3000)
        except Exception as exc:  # noqa: BLE001 - só aquecimento de cookies
            log.warning("Falha ao abrir a página inicial: %s", exc)

    def _load(self, url: str, captured: list, statuses: list) -> None:
        self._page.goto(url, timeout=self.config.timeout * 1000, wait_until="domcontentloaded")
        deadline = time.monotonic() + self.config.timeout
        moved = False
        while not captured and time.monotonic() < deadline:
            if not moved:
                self._humanize()
                moved = True
            self._page.wait_for_timeout(1000)
            if statuses and all(st.startswith("403") for st in statuses) and time.monotonic() > deadline - self.config.timeout / 2:
                break
        # A página às vezes faz uma segunda chamada (ex.: reordenação); espera um pouco por ela.
        self._page.wait_for_timeout(1500)

    def search(self, origin: str, dest: str, day: str, points: bool) -> Any:
        self._warmup()
        self._wait()
        url = search_page_url(self.config, origin, dest, day, points)
        captured: list[Any] = []
        statuses: list[str] = []

        def on_response(resp):
            if "offers/search" not in resp.url:
                return
            statuses.append(f"{resp.status} {resp.url[:120]}")
            if resp.status != 200:
                return
            try:
                captured.append(resp.json())
            except Exception:  # noqa: BLE001
                pass

        self._page.on("response", on_response)
        try:
            self._load(url, captured, statuses)
            if not captured and statuses:
                # Primeira chamada barrada: com os cookies já validados, a segunda costuma passar.
                log.info("Oferta recusada (%s); tentando de novo em instantes", statuses[-1][:3])
                self._page.wait_for_timeout(6000 + random.random() * 4000)
                self._load(url, captured, statuses)
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"erro ao abrir {url}: {exc}") from exc
        finally:
            self._page.remove_listener("response", on_response)

        tag = f"{origin}-{dest}-{day}-{'pts' if points else 'brl'}"
        if not captured:
            html = self._page.content()
            self._dump(f"{tag}.html", f"<!-- {url} -->\n{html}")
            title = self._page.title()
            raise FetchError(
                f"nenhuma resposta de ofertas capturada (motor {self.engine}; título da página: {title!r}; "
                f"chamadas vistas: {statuses or 'nenhuma'})"
            )
        payload = max(captured, key=lambda p: len(json.dumps(p)))
        self._dump(f"{tag}.json", json.dumps(payload, ensure_ascii=False, indent=1))
        return payload

    def close(self) -> None:
        for closer in self._closers:
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


class ApiFetcher(Fetcher):
    def __init__(self, config: Config):
        super().__init__(config)
        try:
            # Imita a impressão digital TLS/HTTP2 do Chrome; requests puro é barrado mais fácil.
            from curl_cffi import requests as cffi

            self._s = cffi.Session(impersonate="chrome")
        except ImportError:
            import requests

            self._s = requests.Session()
            self._s.headers["User-Agent"] = UA
        self._s.headers.update({"Accept": "application/json, text/plain, */*", "Accept-Language": "pt-BR,pt;q=0.9"})
        if os.environ.get("LATAM_PROXY"):
            self._s.proxies = {"http": os.environ["LATAM_PROXY"], "https": os.environ["LATAM_PROXY"]}
        self._session_id = str(uuid.uuid4())
        self._warm = False

    def search(self, origin: str, dest: str, day: str, points: bool) -> Any:
        if not self._warm:
            self._warm = True
            try:
                self._s.get(f"{BASE}/{self.config.site_country}/{self.config.site_lang}", timeout=self.config.timeout)
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao abrir a página inicial: %s", exc)
        self._wait()
        referer = search_page_url(self.config, origin, dest, day, points)
        headers = {
            "Referer": referer,
            "x-latam-app-session-id": self._session_id,
            "x-latam-application-country": self.config.site_country.upper(),
            "x-latam-application-lang": self.config.site_lang,
            "x-latam-application-name": "web-air-offers",
            "x-latam-application-oc": self.config.site_country,
            "x-latam-client-name": "web-air-offers",
            "x-latam-request-id": str(uuid.uuid4()),
            "x-latam-track-id": str(uuid.uuid4()),
            "x-latam-search-identifier": hashlib.sha1(referer.encode()).hexdigest()[:16],
        }
        params = api_params(self.config, origin, dest, day, points)
        try:
            r = self._s.get(BASE + API_PATH, params=params, headers=headers, timeout=self.config.timeout)
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"erro de rede: {exc}") from exc
        tag = f"{origin}-{dest}-{day}-{'pts' if points else 'brl'}"
        self._dump(f"{tag}.txt", f"{r.status_code} {r.url}\n\n{r.text[:200000]}")
        if r.status_code != 200:
            raise FetchError(f"API respondeu {r.status_code} (provável bloqueio anti-robô; use LATAM_FETCHER=browser)")
        try:
            payload = r.json()
        except ValueError as exc:
            raise FetchError("API não devolveu JSON (provável página de verificação)") from exc
        if not _looks_like_offers(payload):
            raise FetchError("JSON sem ofertas reconhecíveis")
        return payload


def make_fetcher(config: Config, mode: str = "points") -> Fetcher:
    """Fonte de cada modo: dinheiro vem do Google Flights (``LATAM_CASH_SOURCE=latam`` usa o site da
    LATAM); pontos só existem no site da LATAM (``LATAM_FETCHER`` escolhe navegador ou API)."""
    if mode == "cash" and config.cash_source == "google":
        from .gflights import GoogleFlightsFetcher

        return GoogleFlightsFetcher(config)
    if config.fetcher == "api":
        return ApiFetcher(config)
    return BrowserFetcher(config)

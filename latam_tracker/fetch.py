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

    def close(self) -> None:
        pass


class BrowserFetcher(Fetcher):
    def __init__(self, config: Config):
        super().__init__(config)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise FetchError(
                "Playwright não instalado: pip install playwright && python -m playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=config.headless,
            # LATAM_BROWSER_PATH: usar um Chrome/Chromium já instalado em vez do baixado pelo Playwright
            executable_path=os.environ.get("LATAM_BROWSER_PATH") or None,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            user_agent=UA,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 860},
        )
        self._context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self._page = self._context.new_page()
        self._warm = False

    def _warmup(self) -> None:
        if self._warm:
            return
        self._warm = True
        try:
            self._page.goto(f"{BASE}/{self.config.site_country}/{self.config.site_lang}", timeout=self.config.timeout * 1000)
            self._page.wait_for_timeout(3000 + random.random() * 2000)
        except Exception as exc:  # noqa: BLE001 - só aquecimento de cookies
            log.warning("Falha ao abrir a página inicial: %s", exc)

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
            self._page.goto(url, timeout=self.config.timeout * 1000, wait_until="domcontentloaded")
            deadline = time.monotonic() + self.config.timeout
            while not captured and time.monotonic() < deadline:
                self._page.wait_for_timeout(1000)
            # A página às vezes faz uma segunda chamada (ex.: reordenação); espera um pouco por ela.
            self._page.wait_for_timeout(1500)
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
                f"nenhuma resposta de ofertas capturada (título da página: {title!r}; "
                f"chamadas vistas: {statuses or 'nenhuma'})"
            )
        payload = max(captured, key=lambda p: len(json.dumps(p)))
        self._dump(f"{tag}.json", json.dumps(payload, ensure_ascii=False, indent=1))
        return payload

    def close(self) -> None:
        for closer in (self._context.close, self._browser.close, self._pw.stop):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass


class ApiFetcher(Fetcher):
    def __init__(self, config: Config):
        super().__init__(config)
        import requests

        self._s = requests.Session()
        self._s.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )
        self._session_id = str(uuid.uuid4())
        self._warm = False

    def search(self, origin: str, dest: str, day: str, points: bool) -> Any:
        import requests

        if not self._warm:
            self._warm = True
            try:
                self._s.get(f"{BASE}/{self.config.site_country}/{self.config.site_lang}", timeout=self.config.timeout)
            except requests.RequestException as exc:
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
        except requests.RequestException as exc:
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


def make_fetcher(config: Config) -> Fetcher:
    if config.fetcher == "api":
        return ApiFetcher(config)
    return BrowserFetcher(config)

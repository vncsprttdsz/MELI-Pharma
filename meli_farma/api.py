"""Coleta pela API oficial do Mercado Livre (api.mercadolibre.com).

Autenticação: token de aplicativo obtido com ``grant_type=client_credentials`` a partir de
``MELI_CLIENT_ID`` / ``MELI_CLIENT_SECRET``. Se ``MELI_ACCESS_TOKEN`` estiver definido, ele é
usado diretamente. Alternativamente, ``MELI_REFRESH_TOKEN`` renova um token de usuário.

A busca (``/sites/MLB/search?official_store_id=...``) só permite navegar ~1000 resultados por
consulta, então a loja é dividida pelas categorias informadas em ``available_filters`` até
cada consulta caber no limite. O caminho completo de cada categoria vem de ``/categories/{id}``.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .parse import Product
from .scraper import PATH_SEP, CategoryCount, ScrapeResult

log = logging.getLogger(__name__)

API = "https://api.mercadolibre.com"
PAGE = 50


class ApiError(RuntimeError):
    pass


class MeliApi:
    def __init__(self, delay: float = 0.3, timeout: float = 30, retries: int = 4):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.token_info: str = "sem token"
        self._authenticate()

    # ------------------------------------------------------------ auth

    def _authenticate(self) -> None:
        token = os.environ.get("MELI_ACCESS_TOKEN")
        cid, secret = os.environ.get("MELI_CLIENT_ID"), os.environ.get("MELI_CLIENT_SECRET")
        refresh = os.environ.get("MELI_REFRESH_TOKEN")
        if not token and cid and secret:
            data = {"client_id": cid, "client_secret": secret}
            if refresh:
                data.update(grant_type="refresh_token", refresh_token=refresh)
            else:
                data.update(grant_type="client_credentials")
            resp = self.session.post(f"{API}/oauth/token", data=data, timeout=self.timeout)
            if resp.status_code != 200:
                raise ApiError(f"Falha ao obter token ({data['grant_type']}): HTTP {resp.status_code} {resp.text[:300]}")
            payload = resp.json()
            token = payload["access_token"]
            self.token_info = f"{data['grant_type']} ok, expira em {payload.get('expires_in')}s, escopo={payload.get('scope')}"
            if payload.get("refresh_token") and refresh and payload["refresh_token"] != refresh:
                # Refresh tokens do ML são de uso único: grava o novo para quem chamou salvar.
                out = os.environ.get("MELI_REFRESH_TOKEN_OUT")
                if out:
                    Path(out).write_text(payload["refresh_token"], encoding="utf-8")
                log.warning("Novo refresh token emitido; o anterior deixa de valer.")
        elif token:
            self.token_info = "MELI_ACCESS_TOKEN"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        log.info("Autenticação: %s", self.token_info)

    # ------------------------------------------------------------ http

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else API + path
        last = ""
        for attempt in range(1, self.retries + 1):
            time.sleep(self.delay * (1 + random.random() * 0.5))
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last = str(exc)
            else:
                if resp.status_code == 200:
                    return resp.json()
                last = f"HTTP {resp.status_code} {resp.text[:300]}"
                if resp.status_code in (400, 401, 403, 404):
                    break
            log.warning("%s (tentativa %d): %s", url, attempt, last)
            time.sleep(min(60, 2**attempt))
        raise ApiError(f"{url} {params or ''}: {last}")


class ApiCollector:
    def __init__(self, api: MeliApi, official_store_id: str, cache_path: Path, max_offset: int = 1000):
        self.api = api
        self.store = official_store_id
        self.max_offset = max_offset
        self.cache_path = cache_path
        self._cat_cache: dict[str, list[str]] = {}
        if cache_path.exists():
            self._cat_cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self.result = ScrapeResult(
            scraped_at=datetime.now(timezone.utc),
            listing_url=f"{API}/sites/MLB/search?official_store_id={official_store_id}",
        )

    # ------------------------------------------------------------ categorias

    def category_path(self, category_id: str) -> list[str]:
        if not category_id:
            return []
        if category_id not in self._cat_cache:
            try:
                data = self.api.get(f"/categories/{category_id}")
                self._cat_cache[category_id] = [c["name"] for c in data.get("path_from_root", [])]
            except ApiError as exc:
                log.warning("Categoria %s: %s", category_id, exc)
                self._cat_cache[category_id] = []
        return self._cat_cache[category_id]

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cat_cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8"
        )

    # ------------------------------------------------------------ busca

    def search(self, offset: int = 0, category: str | None = None, price: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"official_store_id": self.store, "offset": offset, "limit": PAGE}
        if category:
            params["category"] = category
        if price:
            params["price"] = price
        self.result.pages_fetched += 1
        return self.api.get("/sites/MLB/search", params)

    @staticmethod
    def _category_values(page: dict[str, Any]) -> list[dict[str, Any]]:
        for f in page.get("available_filters", []):
            if f.get("id") == "category":
                return f.get("values", [])
        return []

    def _to_product(self, r: dict[str, Any]) -> Product:
        brand = next(
            (a.get("value_name") or "" for a in r.get("attributes", []) if a.get("id") == "BRAND"), ""
        )
        path = self.category_path(r.get("category_id", ""))
        return Product(
            item_id=r["id"],
            title=r.get("title", ""),
            url=r.get("permalink", ""),
            price=r.get("price"),
            original_price=r.get("original_price"),
            currency=r.get("currency_id") or "BRL",
            catalog_product_id=r.get("catalog_product_id") or "",
            brand=brand,
            seller=str((r.get("seller") or {}).get("nickname") or ""),
            category_id=r.get("category_id", ""),
            category_name=path[-1] if path else "",
            category_path=PATH_SEP.join(path),
            free_shipping=(r.get("shipping") or {}).get("free_shipping"),
        )

    def _paginate(self, first: dict[str, Any], category: str | None, price: str | None = None) -> None:
        total = first.get("paging", {}).get("total", 0)
        page = first
        offset = 0
        while True:
            for r in page.get("results", []):
                if r["id"] not in self.result.products:
                    self.result.products[r["id"]] = self._to_product(r)
            offset += PAGE
            if offset >= min(total, self.max_offset) or not page.get("results"):
                break
            try:
                page = self.search(offset, category, price)
            except ApiError as exc:
                msg = f"Paginação interrompida (categoria={category}, offset={offset}): {exc}"
                log.error(msg)
                self.result.errors.append(msg)
                break

    def _crawl(self, category: str | None, depth: int) -> None:
        page = self.search(0, category)
        total = page.get("paging", {}).get("total", 0)
        if category:
            path = self.category_path(category)
            self.result.categories.append(CategoryCount(PATH_SEP.join(path), len(path), total))
        subs = [v for v in self._category_values(page) if v.get("id") != category]
        if total > self.max_offset and subs and depth < 8:
            for v in subs:
                self._crawl(v["id"], depth + 1)
            covered = sum(v.get("results", 0) for v in subs)
            if covered < total:
                self._paginate(page, category)
        elif total > self.max_offset:
            self._crawl_prices(category, 0.0, 100000.0)
        else:
            self._paginate(page, category)

    def _crawl_prices(self, category: str | None, lo: float, hi: float) -> None:
        """Divide uma consulta grande em faixas de preço até cada uma caber no limite."""
        price = f"{lo:.2f}-{hi:.2f}"
        page = self.search(0, category, price)
        total = page.get("paging", {}).get("total", 0)
        if total > self.max_offset and hi - lo > 0.02:
            mid = round((lo + hi) / 2, 2)
            self._crawl_prices(category, lo, mid)
            self._crawl_prices(category, round(mid + 0.01, 2), hi)
            return
        if total > self.max_offset:
            msg = f"Categoria {category} faixa {price} tem {total} itens (> {self.max_offset}); cobertura parcial."
            log.warning(msg)
            self.result.errors.append(msg)
        self._paginate(page, category, price)

    def run(self) -> ScrapeResult:
        first = self.search(0)
        self.result.total_reported = first.get("paging", {}).get("total")
        log.info("Loja %s: %s itens informados pela API", self.store, self.result.total_reported)
        # Registra a contagem por categoria que a própria API informa.
        for v in self._category_values(first):
            path = self.category_path(v["id"])
            self.result.categories.append(CategoryCount(PATH_SEP.join(path), len(path), v.get("results")))
        if (self.result.total_reported or 0) > self.max_offset:
            for v in self._category_values(first):
                self._crawl(v["id"], 1)
        self._paginate(first, None)
        # Remove contagens duplicadas (mesmo caminho registrado mais de uma vez).
        seen: dict[str, CategoryCount] = {}
        for c in self.result.categories:
            seen[c.path] = c
        self.result.categories = list(seen.values())
        self.save_cache()
        log.info("Coleta pela API: %d produtos únicos, %d requisições", len(self.result.products), self.result.pages_fetched)
        return self.result

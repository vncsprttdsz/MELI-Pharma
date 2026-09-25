"""Configuração do monitor. Valores podem ser sobrescritos por variáveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    # Página "vitrine" da loja oficial. Usada para descobrir o link da listagem completa.
    store_page_url: str = _env(
        "MELI_STORE_PAGE_URL", "https://www.mercadolivre.com.br/farmacia/mercadolivrefarma"
    )
    # Listagem completa da loja (filtro de loja oficial). Se a descoberta a partir da
    # vitrine falhar, esta URL é usada diretamente.
    store_listing_url: str = _env(
        "MELI_STORE_LISTING_URL", "https://lista.mercadolivre.com.br/_Loja_mercadolivrefarma"
    )
    # Id da loja oficial Mercado Livre Farma (visto no HTML da vitrine), usado pela API.
    official_store_id: str = _env("MELI_OFFICIAL_STORE_ID", "244622")
    # "api" (API oficial, precisa de MELI_CLIENT_ID/SECRET), "site" (HTML) ou "auto":
    # usa a API quando há credenciais.
    source: str = _env("MELI_SOURCE", "auto")
    # O Mercado Livre limita cada listagem a ~2000 resultados navegáveis. Categorias
    # acima deste limite são subdivididas nas subcategorias.
    listing_cap: int = int(_env("MELI_LISTING_CAP", "2000"))
    # Profundidade máxima de categorias a percorrer (1 = só categorias de primeiro nível
    # dentro da loja). Categorias maiores que o limite descem além disso, até max_depth_hard.
    category_depth: int = int(_env("MELI_CATEGORY_DEPTH", "2"))
    max_depth_hard: int = int(_env("MELI_MAX_DEPTH", "5"))
    max_pages_per_listing: int = int(_env("MELI_MAX_PAGES", "50"))
    # Intervalo entre requisições (segundos), com jitter aleatório de até +50%.
    delay: float = float(_env("MELI_DELAY", "1.5"))
    timeout: float = float(_env("MELI_TIMEOUT", "30"))
    retries: int = int(_env("MELI_RETRIES", "4"))
    user_agent: str = _env(
        "MELI_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    )
    # "requests" (padrão) ou "browser" (Playwright/Chromium, útil se houver bloqueio).
    fetcher: str = _env("MELI_FETCHER", "requests")
    data_dir: Path = field(default_factory=lambda: Path(_env("MELI_DATA_DIR", "data")))
    docs_dir: Path = field(default_factory=lambda: Path(_env("MELI_DOCS_DIR", "docs")))
    # Se definido, salva o HTML de cada página baixada aqui (depuração de parsing).
    debug_dir: Path | None = field(
        default_factory=lambda: Path(os.environ["MELI_DEBUG_DIR"])
        if os.environ.get("MELI_DEBUG_DIR")
        else None
    )

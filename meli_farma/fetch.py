"""Download de páginas com retentativas, intervalo entre requisições e detecção de bloqueio."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from pathlib import Path

import requests

from .config import Config

log = logging.getLogger(__name__)

# Sinais de que o Mercado Livre devolveu uma página de verificação em vez da listagem.
_BLOCK_URL_MARKERS = ("account-verification", "/gz/", "captcha", "/login")
_BLOCK_BODY_MARKERS = ("g-recaptcha", "hcaptcha", "px-captcha", "suspicious_traffic")


class BlockedError(RuntimeError):
    """O site respondeu com captcha/verificação; insistir não adianta."""


def block_reason(url: str, body: str) -> str | None:
    """Motivo pelo qual a resposta parece ser uma página de bloqueio (ou None)."""
    low_url = url.lower()
    for m in _BLOCK_URL_MARKERS:
        if m in low_url:
            return f"URL final contém '{m}' ({url})"
    low = body.lower()
    # Páginas de listagem legítimas podem carregar scripts de captcha; só considera
    # bloqueio se não houver nenhum sinal de conteúdo de listagem/loja.
    if "ui-search" in low or "poly-card" in low:
        return None
    for m in _BLOCK_BODY_MARKERS:
        if m in low:
            return f"página contém '{m}' e nenhum conteúdo de listagem"
    return None


def describe(url: str, status: int | str, body: str) -> str:
    """Resumo de uma resposta para o log (diagnóstico de bloqueio/parsing)."""
    import re

    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    title = " ".join(m.group(1).split())[:120] if m else "-"
    return f"status={status} url={url} bytes={len(body)} title={title!r}"


class Fetcher:
    def __init__(self, config: Config):
        self.config = config
        self._last = 0.0
        # Desligado pelo comando "diagnose", que quer ver a página mesmo se for bloqueio.
        self.check_blocks = True

    def _wait(self) -> None:
        delay = self.config.delay * (1 + random.random() * 0.5)
        elapsed = time.monotonic() - self._last
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last = time.monotonic()

    def _dump(self, url: str, body: str) -> None:
        if not self.config.debug_dir:
            return
        self.config.debug_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(url.encode()).hexdigest()[:12] + ".html"
        (self.config.debug_dir / name).write_text(f"<!-- {url} -->\n{body}", encoding="utf-8")

    def get(self, url: str) -> tuple[str, str]:
        """Retorna (url_final, html)."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class RequestsFetcher(Fetcher):
    def __init__(self, config: Config):
        super().__init__(config)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6",
            }
        )

    def get(self, url: str) -> tuple[str, str]:
        last_exc: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            self._wait()
            try:
                resp = self.session.get(url, timeout=self.config.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Erro de rede em %s (tentativa %d): %s", url, attempt, exc)
            else:
                log.debug(describe(resp.url, resp.status_code, resp.text))
                if resp.status_code == 200:
                    reason = self.check_blocks and block_reason(resp.url, resp.text)
                    if reason:
                        self._dump(url, resp.text)
                        raise BlockedError(
                            f"Página de verificação/captcha ao acessar {url}: {reason}; "
                            + describe(resp.url, resp.status_code, resp.text)
                        )
                    self._dump(url, resp.text)
                    return resp.url, resp.text
                if resp.status_code == 404:
                    raise requests.HTTPError(f"404 em {url}", response=resp)
                last_exc = requests.HTTPError(f"HTTP {resp.status_code} em {url}", response=resp)
                log.warning("HTTP %d em %s (tentativa %d)", resp.status_code, url, attempt)
            time.sleep(min(60, 2**attempt))
        assert last_exc is not None
        raise last_exc


class BrowserFetcher(Fetcher):
    """Renderiza com Chromium via Playwright. Mais lento, mas passa por mais proteções."""

    def __init__(self, config: Config):
        super().__init__(config)
        from playwright.sync_api import sync_playwright  # import opcional

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=config.user_agent, locale="pt-BR", viewport={"width": 1366, "height": 900}
        )
        self._page = self._context.new_page()

    def get(self, url: str) -> tuple[str, str]:
        last_exc: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            self._wait()
            try:
                self._page.goto(url, timeout=self.config.timeout * 1000, wait_until="domcontentloaded")
                self._page.wait_for_timeout(1500)
                body = self._page.content()
                final = self._page.url
            except Exception as exc:  # noqa: BLE001 - erros do Playwright variam
                last_exc = exc
                log.warning("Erro no navegador em %s (tentativa %d): %s", url, attempt, exc)
                time.sleep(min(60, 2**attempt))
                continue
            self._dump(url, body)
            log.debug(describe(final, "browser", body))
            reason = self.check_blocks and block_reason(final, body)
            if reason:
                raise BlockedError(
                    f"Página de verificação/captcha ao acessar {url}: {reason}; " + describe(final, "browser", body)
                )
            return final, body
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


def make_fetcher(config: Config) -> Fetcher:
    if config.fetcher == "browser":
        return BrowserFetcher(config)
    return RequestsFetcher(config)


class FileFetcher(Fetcher):
    """Serve páginas de um diretório local (testes / reprocessamento)."""

    def __init__(self, config: Config, pages: dict[str, Path]):
        super().__init__(config)
        self.pages = pages

    def _wait(self) -> None:
        pass

    def get(self, url: str) -> tuple[str, str]:
        if url not in self.pages:
            raise requests.HTTPError(f"404 em {url}")
        return url, self.pages[url].read_text(encoding="utf-8")

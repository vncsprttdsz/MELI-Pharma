"""Percorre a loja: descobre categorias, pagina as listagens e consolida os produtos."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config
from .fetch import BlockedError, Fetcher
from .parse import CategoryFilter, ListingPage, Product, find_store_listing_link, parse_listing

log = logging.getLogger(__name__)

PATH_SEP = " > "


@dataclass
class CategoryCount:
    path: str
    depth: int
    reported: int | None


@dataclass
class ScrapeResult:
    scraped_at: datetime
    listing_url: str
    total_reported: int | None = None
    products: dict[str, Product] = field(default_factory=dict)
    categories: list[CategoryCount] = field(default_factory=list)
    pages_fetched: int = 0
    errors: list[str] = field(default_factory=list)


class Scraper:
    def __init__(self, config: Config, fetcher: Fetcher):
        self.config = config
        self.fetcher = fetcher
        self._visited: set[str] = set()
        self.result: ScrapeResult | None = None

    # ------------------------------------------------------------ helpers

    def _fetch_listing(self, url: str) -> ListingPage:
        final, html = self.fetcher.get(url)
        assert self.result is not None
        self.result.pages_fetched += 1
        self._visited.add(url)
        self._visited.add(final)
        page = parse_listing(html, final)
        log.info(
            "%s -> %d produtos, total=%s, %d categorias",
            url, len(page.products), page.total, len(page.categories),
        )
        return page

    def _add(self, products: list[Product], path: list[str]) -> int:
        assert self.result is not None
        added = 0
        for p in products:
            if p.item_id in self.result.products:
                continue
            if path:
                p.category_path = PATH_SEP.join(path)
                p.category_name = path[-1]
            self.result.products[p.item_id] = p
            added += 1
        return added

    def _paginate(self, first: ListingPage, path: list[str]) -> None:
        assert self.result is not None
        page: ListingPage | None = first
        n = 0
        while page is not None:
            self._add(page.products, path)
            n += 1
            nxt = page.next_url
            if not nxt or nxt in self._visited or n >= self.config.max_pages_per_listing:
                break
            try:
                page = self._fetch_listing(nxt)
            except BlockedError:
                raise
            except Exception as exc:  # noqa: BLE001
                msg = f"Falha ao paginar {nxt}: {exc}"
                log.error(msg)
                self.result.errors.append(msg)
                break
            if not page.products:
                break

    @staticmethod
    def _subcategories(page: ListingPage, current: str) -> list[CategoryFilter]:
        subs = [c for c in page.categories if c.name.strip().lower() != current.strip().lower()]
        return subs

    def _crawl_category(self, cat: CategoryFilter, path: list[str], depth: int) -> None:
        """depth = profundidade desta categoria (1 = primeiro nível dentro da loja)."""
        assert self.result is not None
        full = path + [cat.name]
        self.result.categories.append(CategoryCount(PATH_SEP.join(full), depth, cat.results))
        if cat.url in self._visited:
            return
        try:
            page = self._fetch_listing(cat.url)
        except BlockedError:
            raise
        except Exception as exc:  # noqa: BLE001
            msg = f"Falha na categoria {PATH_SEP.join(full)}: {exc}"
            log.error(msg)
            self.result.errors.append(msg)
            return

        too_big = (cat.results or page.total or 0) > self.config.listing_cap
        want_deeper = depth < self.config.category_depth or too_big
        subs = self._subcategories(page, cat.name) if want_deeper else []
        if subs and depth < self.config.max_depth_hard:
            for sub in subs:
                self._crawl_category(sub, full, depth + 1)
            # Se as subcategorias não cobrem a categoria-mãe, pagina a mãe para pegar o
            # restante (produtos já vistos são ignorados).
            parent_total = cat.results or page.total or 0
            subs_total = sum(s.results or 0 for s in subs)
            if subs_total < parent_total and not too_big:
                self._paginate(page, full)
            else:
                self._add(page.products, full)
        else:
            if too_big:
                msg = (
                    f"Categoria {PATH_SEP.join(full)} tem {cat.results or page.total} produtos, "
                    f"acima do limite navegável ({self.config.listing_cap}); cobertura parcial."
                )
                log.warning(msg)
                self.result.errors.append(msg)
            self._paginate(page, full)

    # ------------------------------------------------------------ API

    def resolve_listing_url(self) -> str:
        try:
            final, html = self.fetcher.get(self.config.store_page_url)
            link = find_store_listing_link(html, final)
            if link:
                log.info("Listagem da loja descoberta na vitrine: %s", link)
                return link
            log.warning("Link da listagem não encontrado na vitrine; usando URL configurada.")
        except BlockedError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("Não foi possível abrir a vitrine (%s); usando URL configurada.", exc)
        return self.config.store_listing_url

    def run(self, listing_url: str | None = None) -> ScrapeResult:
        url = listing_url or self.resolve_listing_url()
        self.result = ScrapeResult(scraped_at=datetime.now(timezone.utc), listing_url=url)
        root = self._fetch_listing(url)
        self.result.total_reported = root.total

        if root.categories:
            for cat in root.categories:
                self._crawl_category(cat, [], 1)
        else:
            log.warning("Nenhum filtro de categoria encontrado; percorrendo a listagem geral.")

        # Complementa com a listagem geral (produtos sem categoria identificada).
        total = root.total or 0
        if not root.categories or (len(self.result.products) < total and total <= self.config.listing_cap):
            self._paginate(root, [])
        else:
            self._add(root.products, [])

        log.info(
            "Coleta concluída: %d produtos únicos (ML informa %s), %d páginas.",
            len(self.result.products), self.result.total_reported, self.result.pages_fetched,
        )
        return self.result

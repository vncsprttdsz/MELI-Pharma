"""Parsing das páginas de listagem do Mercado Livre.

O Mercado Livre muda o markup com frequência, então cada informação é extraída por
mais de um caminho: primeiro seletores HTML conhecidos (layout "poly-card" atual e o
layout "ui-search" antigo) e, como complemento, o JSON de estado embutido na página.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

_ITEM_ID_RE = re.compile(r"\b(MLB)-?(\d{6,})", re.I)
_PRODUCT_ID_RE = re.compile(r"/p/(MLB\d{5,})", re.I)
_CATEGORY_TITLES = {"categorias", "categoria", "categories", "category"}


@dataclass
class Product:
    item_id: str
    title: str
    url: str
    price: float | None = None
    original_price: float | None = None
    currency: str = "BRL"
    catalog_product_id: str = ""
    brand: str = ""
    seller: str = ""
    category_id: str = ""
    category_name: str = ""
    category_path: str = ""
    free_shipping: bool | None = None
    rating: float | None = None
    reviews: int | None = None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CategoryFilter:
    name: str
    url: str
    results: int | None = None
    category_id: str = ""


@dataclass
class ListingPage:
    url: str
    products: list[Product] = field(default_factory=list)
    total: int | None = None
    categories: list[CategoryFilter] = field(default_factory=list)
    next_url: str | None = None
    breadcrumb: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- utilidades


def parse_int(text: str | None) -> int | None:
    if text is None:
        return None
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def parse_brl(fraction: str | None, cents: str | None = None) -> float | None:
    """'1.234' + '90' -> 1234.90"""
    whole = parse_int(fraction)
    if whole is None:
        return None
    c = parse_int(cents) or 0
    return round(whole + c / 100, 2)


def parse_price_text(text: str | None) -> float | None:
    """'R$ 1.234,90' -> 1234.90"""
    if not text:
        return None
    m = re.search(r"(\d[\d.]*)(?:,(\d{1,2}))?", text)
    if not m:
        return None
    return parse_brl(m.group(1), (m.group(2) or "0").ljust(2, "0"))


def extract_item_id(url: str) -> str:
    """Id do anúncio (MLB123...). Em links de catálogo (/p/MLB...) o id vem no parâmetro wid."""
    qs = parse_qs(urlparse(url).query)
    for key in ("wid", "item_id"):
        if qs.get(key):
            m = _ITEM_ID_RE.search(qs[key][0])
            if m:
                return f"MLB{m.group(2)}"
    path = urlparse(url).path
    if not _PRODUCT_ID_RE.search(path):
        m = _ITEM_ID_RE.search(path)
        if m:
            return f"MLB{m.group(2)}"
    return ""


def extract_product_id(url: str) -> str:
    m = _PRODUCT_ID_RE.search(urlparse(url).path)
    return m.group(1).upper() if m else ""


def canonical_url(url: str) -> str:
    """Remove parâmetros de rastreamento e âncoras."""
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc}{p.path}" if p.netloc else url


def _text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _first(root: Tag, *selectors: str) -> Tag | None:
    for sel in selectors:
        el = root.select_one(sel)
        if el is not None:
            return el
    return None


# ---------------------------------------------------------------- HTML: produtos


def _money(el: Tag | None) -> float | None:
    if el is None:
        return None
    frac = el.select_one(".andes-money-amount__fraction")
    if frac is not None:
        return parse_brl(_text(frac), _text(el.select_one(".andes-money-amount__cents")))
    label = el.get("aria-label") or ""
    if label:
        m = re.search(r"(\d[\d.]*)\s*reais(?:\s*com\s*(\d+)\s*centavos)?", label)
        if m:
            return parse_brl(m.group(1), (m.group(2) or "0").rjust(2, "0"))
    return parse_price_text(_text(el))


def _parse_card(card: Tag, base_url: str) -> Product | None:
    link = _first(
        card,
        "a.poly-component__title",
        ".poly-component__title a",
        "a.ui-search-item__group__element",
        "a.ui-search-link",
        "h2 a",
        "h3 a",
        "a[href]",
    )
    if link is None or not link.get("href"):
        return None
    href = urljoin(base_url, link["href"])
    title_el = _first(card, ".poly-component__title", ".ui-search-item__title", "h2", "h3")
    title = _text(title_el) or _text(link)

    item_id = extract_item_id(href)
    product_id = extract_product_id(href)
    if not item_id:
        # Alguns cards trazem o id em atributos de dados.
        for attr in ("data-item-id", "data-id", "id"):
            m = _ITEM_ID_RE.search(str(card.get(attr) or ""))
            if m:
                item_id = f"MLB{m.group(2)}"
                break
    if not item_id and not product_id:
        return None

    current = _first(
        card,
        ".poly-price__current .andes-money-amount",
        ".ui-search-price__second-line .andes-money-amount",
        ".ui-search-price__part--medium",
        ".andes-money-amount:not(.andes-money-amount--previous)",
    )
    previous = _first(card, "s.andes-money-amount--previous", ".andes-money-amount--previous")

    shipping = _text(_first(card, ".poly-component__shipping", ".ui-search-item__shipping"))
    rating = _text(_first(card, ".poly-reviews__rating", ".ui-search-reviews__rating-number"))
    reviews = _text(_first(card, ".poly-reviews__total", ".ui-search-reviews__amount"))

    return Product(
        item_id=item_id or product_id,
        title=title,
        url=canonical_url(href),
        price=_money(current),
        original_price=_money(previous),
        catalog_product_id=product_id,
        brand=_text(_first(card, ".poly-component__brand", ".ui-search-item__brand-discoverability")),
        seller=_text(_first(card, ".poly-component__seller", ".ui-search-official-store-label")),
        free_shipping=("grátis" in shipping.lower()) if shipping else None,
        rating=float(rating.replace(",", ".")) if re.fullmatch(r"\d+(?:[.,]\d+)?", rating) else None,
        reviews=parse_int(reviews),
    )


def _html_products(soup: BeautifulSoup, base_url: str) -> list[Product]:
    cards = soup.select("li.ui-search-layout__item")
    if not cards:
        cards = soup.select("div.poly-card") or soup.select("div.ui-search-result__wrapper")
    products = []
    for card in cards:
        p = _parse_card(card, base_url)
        if p is not None:
            products.append(p)
    return products


# ---------------------------------------------------------------- JSON embutido


def _embedded_json(soup: BeautifulSoup) -> list[Any]:
    """Extrai blobs JSON de estado (ex.: __PRELOADED_STATE__) presentes na página."""
    blobs: list[Any] = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not raw or len(raw) < 50:
            continue
        stype = (script.get("type") or "").lower()
        candidates: list[str] = []
        if "json" in stype:
            candidates.append(raw)
        else:
            for marker in ("__PRELOADED_STATE__", "__NORDIC_RENDERING_CTX__", "_n.ctx.r="):
                idx = raw.find(marker)
                if idx >= 0:
                    brace = raw.find("{", idx)
                    if brace >= 0:
                        candidates.append(raw[brace:])
        for cand in candidates:
            try:
                obj, _ = json.JSONDecoder().raw_decode(cand.strip())
            except ValueError:
                continue
            blobs.append(obj)
    return blobs


def _walk(obj: Any) -> Iterator[dict]:
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _polycard_to_product(card: dict) -> Product | None:
    meta = card.get("metadata") or {}
    raw_url = meta.get("url") or meta.get("permalink") or ""
    if raw_url and not raw_url.startswith("http"):
        raw_url = "https://" + raw_url.lstrip("/")
    item_id = str(meta.get("id") or "") or extract_item_id(raw_url)
    if not item_id:
        return None
    p = Product(
        item_id=item_id,
        title="",
        url=canonical_url(raw_url) if raw_url else "",
        catalog_product_id=str(meta.get("product_id") or "") or extract_product_id(raw_url),
        category_id=str(meta.get("category_id") or ""),
    )
    for comp in card.get("components") or []:
        ctype = comp.get("type")
        if ctype == "title":
            p.title = (comp.get("title") or {}).get("text", "") or p.title
        elif ctype == "price":
            price = comp.get("price") or {}
            cur = price.get("current_price") or {}
            prev = price.get("previous_price") or {}
            if cur.get("value") is not None:
                p.price = float(cur["value"])
                p.currency = cur.get("currency") or p.currency
            if prev.get("value") is not None:
                p.original_price = float(prev["value"])
        elif ctype == "brand":
            p.brand = (comp.get("brand") or {}).get("text", "") or p.brand
        elif ctype == "seller":
            p.seller = re.sub(r"\{[^}]*\}", "", (comp.get("seller") or {}).get("text", "")).strip()
        elif ctype == "shipping":
            txt = json.dumps(comp.get("shipping") or {}, ensure_ascii=False).lower()
            p.free_shipping = "grátis" in txt or "free" in txt
    return p


def _json_products(blobs: list[Any]) -> list[Product]:
    products: dict[str, Product] = {}
    for blob in blobs:
        for node in _walk(blob):
            card = node.get("polycard")
            if isinstance(card, dict) and isinstance(card.get("metadata"), dict):
                p = _polycard_to_product(card)
                if p and p.item_id not in products:
                    products[p.item_id] = p
    return list(products.values())


def _json_total(blobs: list[Any]) -> int | None:
    for blob in blobs:
        for node in _walk(blob):
            paging = node.get("paging")
            if isinstance(paging, dict) and isinstance(paging.get("total"), int):
                return paging["total"]
    return None


def _json_categories(blobs: list[Any], base_url: str) -> list[CategoryFilter]:
    for blob in blobs:
        for node in _walk(blob):
            if node.get("id") != "category":
                continue
            values = node.get("values") or node.get("entries") or []
            out = []
            for v in values:
                if not isinstance(v, dict):
                    continue
                url = v.get("url") or v.get("target") or ""
                name = v.get("name") or v.get("label") or ""
                if isinstance(name, dict):
                    name = name.get("text", "")
                if not url or not name:
                    continue
                out.append(
                    CategoryFilter(
                        name=str(name),
                        url=urljoin(base_url, url),
                        results=v.get("results") if isinstance(v.get("results"), int) else parse_int(v.get("results")),
                        category_id=str(v.get("id") or ""),
                    )
                )
            if out:
                return out
    return []


# ---------------------------------------------------------------- HTML: metadados


def _html_total(soup: BeautifulSoup) -> int | None:
    el = _first(
        soup,
        ".ui-search-search-result__quantity-results",
        ".ui-search-search-result .quantity-results",
    )
    if el is not None:
        return parse_int(_text(el))
    m = re.search(r"([\d.]+)\s+resultados", soup.get_text(" ", strip=True)[:5000])
    return parse_int(m.group(1)) if m else None


def _html_categories(soup: BeautifulSoup, base_url: str) -> list[CategoryFilter]:
    for block in soup.select(".ui-search-filter-dl, section.ui-search-filter-groups > div"):
        title = _text(_first(block, ".ui-search-filter-dt-title", "h3", "h2")).strip().lower()
        if title not in _CATEGORY_TITLES:
            continue
        out = []
        for li in block.select("li"):
            a = li.select_one("a[href]")
            if a is None:
                continue
            name = _text(_first(li, ".ui-search-filter-name")) or _text(a)
            count = parse_int(_text(_first(li, ".ui-search-filter-results")))
            if not name or name.lower().startswith(("mostrar", "ver ")):
                continue
            name = re.sub(r"\s*\(\d[\d.]*\)\s*$", "", name)
            out.append(CategoryFilter(name=name, url=urljoin(base_url, a["href"]), results=count))
        if out:
            return out
    return []


def _html_next(soup: BeautifulSoup, base_url: str) -> str | None:
    el = _first(
        soup,
        "li.andes-pagination__button--next:not(.andes-pagination__button--disabled) a[href]",
        "a.andes-pagination__link[title='Seguinte']",
        "link[rel=next]",
    )
    if el is not None and el.get("href"):
        return urljoin(base_url, el["href"])
    return None


def _html_breadcrumb(soup: BeautifulSoup) -> list[str]:
    crumbs = [_text(el) for el in soup.select(".andes-breadcrumb__item")]
    return [c for c in crumbs if c]


# ---------------------------------------------------------------- API pública


def parse_listing(html: str, url: str) -> ListingPage:
    soup = BeautifulSoup(html, "lxml")
    blobs = _embedded_json(soup)

    html_products = _html_products(soup, url)
    json_products = {p.item_id: p for p in _json_products(blobs)}
    products: list[Product] = []
    seen: set[str] = set()
    for p in html_products:
        extra = json_products.get(p.item_id)
        if extra:
            for f in ("price", "original_price", "category_id", "brand", "seller", "catalog_product_id"):
                if not getattr(p, f) and getattr(extra, f):
                    setattr(p, f, getattr(extra, f))
        products.append(p)
        seen.add(p.item_id)
    for pid, p in json_products.items():
        if pid not in seen and p.title:
            products.append(p)
            seen.add(pid)

    return ListingPage(
        url=url,
        products=products,
        total=_html_total(soup) or _json_total(blobs),
        categories=_html_categories(soup, url) or _json_categories(blobs, url),
        next_url=_html_next(soup, url),
        breadcrumb=_html_breadcrumb(soup),
    )


def find_store_listing_link(html: str, base_url: str) -> str | None:
    """Na vitrine da loja, encontra o link para a listagem com todos os produtos."""
    soup = BeautifulSoup(html, "lxml")
    links = [urljoin(base_url, a["href"]) for a in soup.select("a[href]")]
    candidates = [
        link.split("#")[0]
        for link in links
        if any(p in link for p in ("_Loja_", "_Tienda_", "official_store"))
    ]
    # Prefere o link da própria loja de farmácia, caso a vitrine aponte para outras lojas.
    for link in candidates:
        if "farma" in link.lower():
            return link
    return candidates[0] if candidates else None

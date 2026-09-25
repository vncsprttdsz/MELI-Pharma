"""Gera HTML sintético no formato das listagens do Mercado Livre."""

from __future__ import annotations

import json

import pytest

BASE = "https://lista.mercadolivre.com.br"


def card(item_id: str, title: str, price: str, cents: str = "", previous: str = "", catalog: bool = False) -> str:
    num = item_id.removeprefix("MLB")
    href = (
        f"https://www.mercadolivre.com.br/produto/p/MLB9{num}?wid={item_id}&sid=search"
        if catalog
        else f"https://produto.mercadolivre.com.br/MLB-{num}-produto-_JM#position=1"
    )
    prev = (
        f'<s class="andes-money-amount andes-money-amount--previous"><span class="andes-money-amount__fraction">{previous}</span></s>'
        if previous
        else ""
    )
    cents_html = f'<span class="andes-money-amount__cents">{cents}</span>' if cents else ""
    return f"""
<li class="ui-search-layout__item">
  <div class="poly-card">
    <span class="poly-component__brand">Marca X</span>
    <h3 class="poly-component__title-wrapper"><a class="poly-component__title" href="{href}">{title}</a></h3>
    <span class="poly-component__seller">Por Mercado Livre Farma</span>
    <div class="poly-reviews"><span class="poly-reviews__rating">4.8</span><span class="poly-reviews__total">(1.234)</span></div>
    <div class="poly-component__price">
      {prev}
      <div class="poly-price__current">
        <span class="andes-money-amount" role="img"><span class="andes-money-amount__fraction">{price}</span>{cents_html}</span>
      </div>
    </div>
    <div class="poly-component__shipping">Frete grátis</div>
  </div>
</li>"""


def listing(cards: list[str], total: int, categories: list[tuple[str, str, int]] = (), next_url: str | None = None,
            breadcrumb: list[str] = (), embedded: dict | None = None) -> str:
    cats = ""
    if categories:
        lis = "".join(
            f'<li class="ui-search-filter-container"><a class="ui-search-link" href="{url}">'
            f'<span class="ui-search-filter-name">{name}</span><span class="ui-search-filter-results">({n})</span></a></li>'
            for name, url, n in categories
        )
        cats = f'<div class="ui-search-filter-dl"><h3 class="ui-search-filter-dt-title">Categorias</h3><ul>{lis}</ul></div>'
    nxt = (
        f'<li class="andes-pagination__button andes-pagination__button--next"><a href="{next_url}" title="Seguinte">Seguinte</a></li>'
        if next_url
        else '<li class="andes-pagination__button andes-pagination__button--next andes-pagination__button--disabled"><a>Seguinte</a></li>'
    )
    crumbs = "".join(f'<li class="andes-breadcrumb__item"><a>{c}</a></li>' for c in breadcrumb)
    script = f"<script>window.__PRELOADED_STATE__ = {json.dumps(embedded)};</script>" if embedded else ""
    return f"""<!doctype html><html><head><title>Farma</title></head><body>
<ol class="andes-breadcrumb">{crumbs}</ol>
<aside><div class="ui-search-search-result"><span class="ui-search-search-result__quantity-results">{total:,} resultados</span></div>
{cats}</aside>
<ol class="ui-search-layout">{''.join(cards)}</ol>
<ul class="andes-pagination">{nxt}</ul>
{script}
</body></html>""".replace(f"{total:,}", f"{total:,}".replace(",", "."))


@pytest.fixture
def make_card():
    return card


@pytest.fixture
def make_listing():
    return listing

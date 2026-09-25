"""Coleta ponta a ponta sobre uma loja simulada + gravação + relatório."""

from datetime import datetime, timezone

import pytest

from meli_farma.config import Config
from meli_farma.fetch import Fetcher
from meli_farma.report import build_dashboard_data, compare, markdown_summary, write_dashboard
from meli_farma.scraper import Scraper
from meli_farma.storage import Storage, read_csv

L = "https://lista.mercadolivre.com.br"
STORE = "https://www.mercadolivre.com.br/farmacia/mercadolivrefarma"


class DictFetcher(Fetcher):
    def __init__(self, config, pages):
        super().__init__(config)
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise RuntimeError(f"404 {url}")
        return url, self.pages[url]


def build_site(card, listing, *, removed=False, new_price=None):
    """Loja com Medicamentos (> Analgésicos [2 páginas], Vitaminas) e Beleza."""
    analg_p1 = [card("MLB1000001", "Dipirona", "10"), card("MLB1000002", "Paracetamol", new_price or "8", "50")]
    analg_p2 = [] if removed else [card("MLB1000003", "Ibuprofeno", "15")]
    vit = [card("MLB1000004", "Vitamina C", "30")]
    bel = [card("MLB1000005", "Protetor solar", "59", "90", previous="79")]
    if removed:
        bel.append(card("MLB1000006", "Hidratante", "25"))
    total_analg = len(analg_p1) + len(analg_p2)
    total_med = total_analg + 1
    total = total_med + len(bel)
    return {
        STORE: f'<a href="{L}/_Loja_mercadolivrefarma">Ver todos os produtos</a>',
        f"{L}/_Loja_mercadolivrefarma": listing(
            analg_p1 + vit,
            total=total,
            categories=[("Medicamentos", f"{L}/medicamentos/_Loja_mercadolivrefarma", total_med),
                        ("Beleza", f"{L}/beleza/_Loja_mercadolivrefarma", len(bel))],
        ),
        f"{L}/medicamentos/_Loja_mercadolivrefarma": listing(
            analg_p1 + analg_p2 + vit,
            total=total_med,
            categories=[("Analgésicos", f"{L}/analgesicos/_Loja_mercadolivrefarma", total_analg),
                        ("Vitaminas", f"{L}/vitaminas/_Loja_mercadolivrefarma", 1)],
        ),
        f"{L}/analgesicos/_Loja_mercadolivrefarma": listing(
            analg_p1, total=total_analg,
            next_url=f"{L}/analgesicos/_Desde_3_Loja_mercadolivrefarma" if analg_p2 else None,
        ),
        f"{L}/analgesicos/_Desde_3_Loja_mercadolivrefarma": listing(analg_p2, total=total_analg),
        f"{L}/vitaminas/_Loja_mercadolivrefarma": listing(vit, total=1),
        f"{L}/beleza/_Loja_mercadolivrefarma": listing(bel, total=len(bel)),
    }


@pytest.fixture
def config(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path / "data"
    cfg.docs_dir = tmp_path / "docs"
    cfg.delay = 0
    cfg.category_depth = 2
    return cfg


def scrape(config, pages, when):
    result = Scraper(config, DictFetcher(config, pages)).run()
    result.scraped_at = when
    return result


def test_scraper_assigns_categories(config, make_card, make_listing):
    result = scrape(config, build_site(make_card, make_listing), datetime.now(timezone.utc))
    assert result.total_reported == 5
    assert result.listing_url.endswith("/_Loja_mercadolivrefarma")
    cats = {p.item_id: p.category_path for p in result.products.values()}
    assert cats == {
        "MLB1000001": "Medicamentos > Analgésicos",
        "MLB1000002": "Medicamentos > Analgésicos",
        "MLB1000003": "Medicamentos > Analgésicos",
        "MLB1000004": "Medicamentos > Vitaminas",
        "MLB1000005": "Beleza",
    }
    assert {c.path: c.reported for c in result.categories} == {
        "Medicamentos": 4, "Medicamentos > Analgésicos": 3, "Medicamentos > Vitaminas": 1, "Beleza": 1,
    }
    assert result.errors == []


def test_depth_one_does_not_descend(config, make_card, make_listing):
    config.category_depth = 1
    result = scrape(config, build_site(make_card, make_listing), datetime.now(timezone.utc))
    assert {p.category_path for p in result.products.values()} <= {"Medicamentos", "Beleza"}


def test_storage_history_and_report(config, make_card, make_listing):
    storage = Storage(config.data_dir)
    d1 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    d2 = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
    storage.save(scrape(config, build_site(make_card, make_listing), d1))
    storage.save(scrape(config, build_site(make_card, make_listing, removed=True, new_price="9"), d2))
    # Rodar de novo no mesmo dia substitui, não duplica.
    storage.save(scrape(config, build_site(make_card, make_listing, removed=True, new_price="9"), d2))

    runs = read_csv(config.data_dir / "history" / "runs.csv")
    assert [(r["date"], r["products_scraped"], r["ml_reported_total"]) for r in runs] == [
        ("2026-09-01", "5", "5"), ("2026-09-02", "5", "5"),
    ]
    cats = {(r["date"], r["category"]): r for r in read_csv(config.data_dir / "history" / "categories.csv")}
    assert cats[("2026-09-01", "Medicamentos")]["products"] == "4"
    assert cats[("2026-09-02", "Medicamentos")]["products"] == "3"
    assert cats[("2026-09-02", "Beleza")]["products"] == "2"
    assert cats[("2026-09-01", "Medicamentos > Analgésicos")]["depth"] == "2"
    assert cats[("2026-09-01", "Beleza")]["discounted"] == "1"

    master = {r["item_id"]: r for r in read_csv(config.data_dir / "products.csv")}
    assert master["MLB1000003"]["active"] == "0" and master["MLB1000003"]["last_seen"] == "2026-09-01"
    assert master["MLB1000006"]["first_seen"] == "2026-09-02" and master["MLB1000006"]["active"] == "1"

    diff = compare(storage)
    assert [r["item_id"] for r in diff.added] == ["MLB1000006"]
    assert [r["item_id"] for r in diff.removed] == ["MLB1000003"]
    assert [(r["item_id"], r["old_price"], r["new_price"]) for r in diff.price_changes] == [
        ("MLB1000002", 8.5, 9.5)
    ]

    summary = markdown_summary(storage)
    assert "Produtos coletados:** 5 (+0 vs 2026-09-01)" in summary
    assert "| Medicamentos | 3 | -1 |" in summary

    data = build_dashboard_data(storage)
    assert data["last"] == "2026-09-02" and len(data["products"]) == 5
    assert data["changes"]["added_n"] == 1
    assert [s["name"] for s in data["history"]["1"]["series"]] == ["Medicamentos", "Beleza"]
    out = write_dashboard(storage, config.docs_dir)
    html = out.read_text(encoding="utf-8")
    assert "/*__DATA__*/null" not in html and "Vitamina C" in html

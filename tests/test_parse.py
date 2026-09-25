from meli_farma.parse import (
    extract_item_id,
    find_store_listing_link,
    parse_brl,
    parse_listing,
    parse_price_text,
)


def test_price_helpers():
    assert parse_brl("1.234", "90") == 1234.90
    assert parse_brl("15") == 15.0
    assert parse_price_text("R$ 1.234,9") == 1234.90
    assert parse_price_text("sem preço") is None


def test_extract_item_id():
    assert extract_item_id("https://produto.mercadolivre.com.br/MLB-123456789-dipirona-_JM") == "MLB123456789"
    assert extract_item_id("https://www.mercadolivre.com.br/x/p/MLB1234567?wid=MLB555666777&sid=a") == "MLB555666777"
    # Link de catálogo sem wid não é id de anúncio.
    assert extract_item_id("https://www.mercadolivre.com.br/x/p/MLB1234567") == ""


def test_parse_listing_html(make_card, make_listing):
    html = make_listing(
        [
            make_card("MLB1000001", "Dipirona 500mg 10 comprimidos", "12", "90", previous="15"),
            make_card("MLB1000002", "Protetor Solar FPS 50", "1.049", catalog=True),
        ],
        total=1234,
        categories=[("Medicamentos", "https://lista.mercadolivre.com.br/medicamentos/_Loja_x", 1000)],
        next_url="https://lista.mercadolivre.com.br/_Desde_49_Loja_x",
    )
    page = parse_listing(html, "https://lista.mercadolivre.com.br/_Loja_x")
    assert page.total == 1234
    assert page.next_url == "https://lista.mercadolivre.com.br/_Desde_49_Loja_x"
    assert [(c.name, c.results) for c in page.categories] == [("Medicamentos", 1000)]
    a, b = page.products
    assert a.item_id == "MLB1000001"
    assert a.title == "Dipirona 500mg 10 comprimidos"
    assert a.price == 12.90 and a.original_price == 15.0
    assert a.url == "https://produto.mercadolivre.com.br/MLB-1000001-produto-_JM"
    assert a.free_shipping is True and a.rating == 4.8 and a.reviews == 1234
    assert a.brand == "Marca X"
    assert b.item_id == "MLB1000002" and b.catalog_product_id == "MLB91000002"
    assert b.price == 1049.0


def test_parse_listing_last_page_has_no_next(make_card, make_listing):
    page = parse_listing(make_listing([make_card("MLB1000001", "A", "1")], total=1), "https://x/")
    assert page.next_url is None


def test_embedded_json_fills_gaps_and_adds_items(make_card, make_listing):
    state = {
        "pageState": {
            "initialState": {
                "paging": {"total": 2},
                "results": [
                    {"polycard": {"metadata": {"id": "MLB1000001", "category_id": "MLB264201"}, "components": []}},
                    {
                        "polycard": {
                            "metadata": {"id": "MLB2000002", "url": "produto.mercadolivre.com.br/MLB-2000002-vitamina-_JM"},
                            "components": [
                                {"type": "title", "title": {"text": "Vitamina C"}},
                                {"type": "price", "price": {"current_price": {"value": 29.9, "currency": "BRL"}}},
                            ],
                        }
                    },
                ],
                "available_filters": [
                    {"id": "category", "values": [{"id": "MLB1", "name": "Suplementos", "results": 7, "url": "/suplementos/_Loja_x"}]}
                ],
            }
        }
    }
    html = make_listing([make_card("MLB1000001", "Dipirona", "10")], total=2, embedded=state)
    html = html.replace("ui-search-filter-dl", "sem-filtro")  # força categorias via JSON
    page = parse_listing(html, "https://lista.mercadolivre.com.br/_Loja_x")
    ids = {p.item_id: p for p in page.products}
    assert ids["MLB1000001"].category_id == "MLB264201"
    assert ids["MLB2000002"].title == "Vitamina C" and ids["MLB2000002"].price == 29.9
    assert ids["MLB2000002"].url == "https://produto.mercadolivre.com.br/MLB-2000002-vitamina-_JM"
    assert page.categories[0].name == "Suplementos"
    assert page.categories[0].url == "https://lista.mercadolivre.com.br/suplementos/_Loja_x"


def test_find_store_listing_link():
    html = """<a href="https://lista.mercadolivre.com.br/_Loja_outra">x</a>
              <a href="https://lista.mercadolivre.com.br/_Loja_mercadolivrefarma#D[A:farma]">Ver todos</a>"""
    assert find_store_listing_link(html, "https://www.mercadolivre.com.br/") == (
        "https://lista.mercadolivre.com.br/_Loja_mercadolivrefarma"
    )
    assert find_store_listing_link("<a href='/ajuda'>x</a>", "https://x/") is None


def test_block_reason():
    from meli_farma.fetch import block_reason

    assert block_reason("https://www.mercadolivre.com.br/gz/account-verification?go=x", "")
    assert block_reason("https://lista.mercadolivre.com.br/x", "<div class='g-recaptcha'></div>")
    # Listagem normal que por acaso carrega script de captcha não é bloqueio.
    assert block_reason("https://lista.mercadolivre.com.br/x", "<li class='ui-search-layout__item'></li> g-recaptcha") is None

"""Coleta pela API com respostas simuladas."""

from meli_farma.api import ApiCollector


def item(i, cat, price=None):
    price = price if price is not None else float(i * 3)
    return {
        "id": f"MLB{i}", "title": f"Produto {i}", "permalink": f"https://produto.mercadolivre.com.br/MLB-{i}",
        "price": price, "original_price": price * 2 if i % 2 else None, "currency_id": "BRL",
        "category_id": cat, "shipping": {"free_shipping": True},
        "attributes": [{"id": "BRAND", "value_name": "Marca"}],
    }


CATS = {"C1": ["Saúde", "Medicamentos"], "C2": ["Beleza", "Protetor"]}
ITEMS = {"C1": [item(i, "C1") for i in range(1, 8)], "C2": [item(i, "C2", 20.0) for i in range(8, 11)]}


class FakeApi:
    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.startswith("/categories/"):
            cid = path.rsplit("/", 1)[1]
            return {"path_from_root": [{"name": n} for n in CATS[cid]]}
        cat = params.get("category")
        pool = ITEMS[cat] if cat else ITEMS["C1"] + ITEMS["C2"]
        if params.get("price"):
            lo, hi = map(float, params["price"].split("-"))
            pool = [r for r in pool if lo <= r["price"] <= hi]
        off, lim = params["offset"], params["limit"]
        filters = [] if cat else [{"id": "category", "values": [
            {"id": "C1", "name": "Medicamentos", "results": 7}, {"id": "C2", "name": "Protetor", "results": 3}]}]
        return {"paging": {"total": len(pool)}, "results": pool[off: off + lim], "available_filters": filters}


def test_collector_splits_by_category(tmp_path, monkeypatch):
    monkeypatch.setattr("meli_farma.api.PAGE", 2)
    api = FakeApi()
    col = ApiCollector(api, "244622", tmp_path / "cache.json", max_offset=4)
    result = col.run()
    assert result.total_reported == 10
    assert len(result.products) == 10
    p = result.products["MLB1"]
    assert p.category_path == "Saúde > Medicamentos" and p.category_name == "Medicamentos"
    assert p.price == 3.0 and p.original_price == 6.0 and p.brand == "Marca" and p.free_shipping
    counts = {c.path: c.reported for c in result.categories}
    assert counts == {"Saúde > Medicamentos": 7, "Beleza > Protetor": 3}
    # C1 (7 itens) excede o limite de 4 e não tem subcategorias: é dividida por faixa de preço.
    assert any((params or {}).get("price") for _, params in api.calls)
    assert result.errors == []
    assert (tmp_path / "cache.json").exists()
    assert sum(1 for path, _ in api.calls if path.startswith("/categories/")) == 2

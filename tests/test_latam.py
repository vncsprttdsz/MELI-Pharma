"""Tracker LATAM: parser do JSON de ofertas, coleta simulada, análise e dashboard."""

from latam_tracker.config import Config, date_window
from latam_tracker.fetch import FetchError, Fetcher, search_page_url
from latam_tracker.parse import extract_offers
from latam_tracker.report import analyze, markdown_summary, write_dashboard
from latam_tracker.storage import Storage
from latam_tracker.tracker import run


def offer(code, stops, prices, currency="BRL", taxes=None, depart="2027-04-01T23:05:00"):
    brands = []
    for name, amount in prices:
        price = {"amount": amount, "currency": currency}
        if taxes is not None:
            price["taxes"] = taxes
        brands.append({"id": name[:2].upper(), "brandText": name, "price": price})
    return {
        "summary": {
            "flightCode": code,
            "stopQuantity": stops,
            "duration": 715,
            "origin": {"iataCode": "GRU", "departure": depart},
            "destination": {"iataCode": "LAX", "arrival": "2027-04-02T07:00:00"},
            "brands": brands,
        },
        "itinerary": [{"flight": {"airlineCode": "LA", "flightNumber": 8180}}],
    }


def payload(*offers):
    return {"content": list(offers), "currencyCode": "BRL"}


def test_extract_offers_reads_flights_brands_and_stops():
    rows = extract_offers(payload(
        offer("LA8180", 0, [("Light", 2500), ("Standard", 2900)]),
        offer("LA8084+LA2464", 1, [("Light", 1900)]),
    ))
    assert len(rows) == 3
    direct = [r for r in rows if r["stops"] == 0]
    assert {r["brand"] for r in direct} == {"Light", "Standard"}
    assert direct[0]["flight"] == "LA8180" and direct[0]["currency"] == "BRL"
    assert direct[0]["depart"].startswith("2027-04-01T23:05")


def test_extract_offers_points_with_taxes_and_fallbacks():
    data = {"data": {"offers": [{"summary": {"stops": [], "brands": [{"name": "Light", "points": "45.000",
                                                                       "taxes": "312,50"}]},
                                 "itinerary": [{"flight": {"airlineCode": "LA", "flightNumber": 8181}}]}]}}
    [r] = extract_offers(data)
    assert r["price"] == 45000 and r["currency"] == "PTS" and r["taxes"] == 312.5
    assert r["stops"] == 0 and r["flight"] == "LA8181"


def test_search_url_and_window():
    cfg = Config()
    assert date_window("2027-04-01", 1) == ["2027-03-31", "2027-04-01", "2027-04-02"]
    url = search_page_url(cfg, "GRU", "LAX", "2027-04-01", True)
    assert "/br/pt/oferta-voos?" in url and "redemption=true" in url and "trip=OW" in url


class FakeFetcher(Fetcher):
    """Voo direto só ter/qui/sáb na ida e qua/qui/dom na volta, como a operação real."""

    def __init__(self, config, cash_shift=0, fail=()):
        super().__init__(config)
        self.cash_shift = cash_shift
        self.fail = set(fail)

    def search(self, origin, dest, day, points):
        if (day, points) in self.fail:
            raise FetchError("bloqueado")
        direct_days = {"2027-04-01", "2027-04-11", "2027-04-09"}
        conn = offer("LA8064+LA2470", 1, [("Light", 99999 if points else 1500)],
                     currency="PTS" if points else "BRL")
        if day not in direct_days:
            return payload(conn)
        base = int(day[-2:]) * 100
        if points:
            d = offer("LA8180", 0, [("Light", 40000 + base), ("Full", 90000)], currency="PTS", taxes=350.0)
        else:
            d = offer("LA8180", 0, [("Light", 3000 + base + self.cash_shift), ("Standard", 3600 + base)])
        return payload(d, conn)


def test_run_analyze_and_dashboard(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", report_path=tmp_path / "docs" / "latam.html", delay=0)
    storage = Storage(cfg.data_dir)

    r1 = run(cfg, FakeFetcher(cfg), checked_at="2026-10-07T12:00Z")
    assert len(r1.searches) == 12
    assert all(q["stops"] == 0 for q in r1.quotes)
    assert {s["status"] for s in r1.searches} == {"ok", "no_direct"}
    storage.save(r1.quotes, r1.searches)

    r2 = run(cfg, FakeFetcher(cfg, cash_shift=-500, fail={("2027-03-31", True)}), checked_at="2026-10-07T18:00Z")
    assert len(r2.failed) == 1
    storage.save(r2.quotes, r2.searches)

    a = analyze(cfg, storage.quotes(), storage.searches())
    assert a["latest"] == "2026-10-07T18:00Z" and a["checks"] == 2
    cash = a["combos"]["cash"]
    # ida 01/04 (3100-500) + volta 09/04 (3900-500)
    assert cash[0]["out"] == "2027-04-01" and cash[0]["in"] == "2027-04-09" and cash[0]["price"] == 6000
    pts = a["combos"]["points"][0]
    assert pts["price"] == 40100 + 40900 and pts["taxes"] == 700
    assert any("⬇️" in m and "dinheiro" in m for m in a["alerts"])
    assert not any("pontos" in m for m in a["alerts"])

    md = markdown_summary(cfg, a)
    assert "R$ 6.000" in md and "sem voo direto" in md and "falhou" in md
    page = write_dashboard(cfg, a).read_text(encoding="utf-8")
    assert "__" not in page.replace("__proto__", "")
    assert "81.000 pts" in page and "LA8180" in page


def test_google_flights_fetcher_keeps_only_latam(monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("fli")
    from datetime import datetime
    from types import SimpleNamespace as NS

    from latam_tracker.gflights import GoogleFlightsFetcher

    def leg(code, num, dep, arr):
        return NS(airline=NS(name=code), flight_number=num,
                  departure_datetime=datetime.fromisoformat(dep), arrival_datetime=datetime.fromisoformat(arr))

    results = [
        NS(price=4321.0, currency="BRL", stops=0, duration=740,
           legs=[leg("LA", "8180", "2027-04-01T23:05", "2027-04-02T07:00")]),
        NS(price=3000.0, currency="BRL", stops=0, duration=700,
           legs=[leg("DL", "104", "2027-04-01T22:00", "2027-04-02T06:00")]),
        NS(price=None, currency="BRL", stops=0, duration=740, legs=[]),
    ]
    f = GoogleFlightsFetcher(Config(delay=0))
    seen = {}
    f._client = NS(search=lambda filters, **kw: seen.update(kw) or results)
    [row] = f.offers("GRU", "LAX", "2027-04-01", False)
    assert seen["currency"] == "BRL"
    assert row["flight"] == "LA8180" and row["price"] == 4321.0 and row["stops"] == 0
    assert row["depart"].startswith("2027-04-01T23:05")

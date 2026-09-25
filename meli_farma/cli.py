"""Linha de comando: ``python -m meli_farma {scrape,report,summary}``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Config
from .fetch import BlockedError, block_reason, describe, make_fetcher
from .report import markdown_summary, write_dashboard
from .scraper import Scraper
from .storage import Storage


def _publish_summary(text: str) -> None:
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def _use_api(args: argparse.Namespace, config: Config) -> bool:
    source = args.source or config.source
    if source == "auto":
        return bool(os.environ.get("MELI_CLIENT_ID") or os.environ.get("MELI_ACCESS_TOKEN"))
    return source == "api"


def cmd_scrape(args: argparse.Namespace, config: Config) -> int:
    if _use_api(args, config):
        from .api import ApiCollector, ApiError, MeliApi

        try:
            api = MeliApi(delay=min(config.delay, 0.5), timeout=config.timeout, retries=config.retries)
            result = ApiCollector(
                api, config.official_store_id, config.data_dir / "categories_cache.json"
            ).run()
        except ApiError as exc:
            logging.error("Erro na API: %s", exc)
            return 2
    else:
        if args.browser:
            config.fetcher = "browser"
        fetcher = make_fetcher(config)
        try:
            result = Scraper(config, fetcher).run(listing_url=args.url)
        except BlockedError as exc:
            logging.error("%s. Tente MELI_FETCHER=browser ou rodar a partir de outra rede.", exc)
            return 2
        finally:
            fetcher.close()

    if not result.products:
        logging.error("Nenhum produto coletado; nada foi salvo. Rode com MELI_DEBUG_DIR=debug para inspecionar o HTML.")
        return 1
    storage = Storage(config.data_dir)
    date = storage.save(result)
    logging.info("Snapshot salvo: %s", storage.snapshot_path(date))
    if not args.no_report:
        write_dashboard(storage, config.docs_dir)
        _publish_summary(markdown_summary(storage))
    return 0


def cmd_diagnose_api(args: argparse.Namespace, config: Config) -> int:
    """Testa as credenciais e a busca da loja na API, sem salvar nada."""
    import json

    from .api import ApiCollector, ApiError, MeliApi

    try:
        api = MeliApi(timeout=config.timeout, retries=2)
    except ApiError as exc:
        print("ERRO na autenticação:", exc)
        return 2
    print("autenticação:", api.token_info)
    try:
        me = api.get("/users/me")
        print("usuário do token:", me.get("id"), me.get("nickname"))
    except ApiError as exc:
        print("/users/me:", exc)
    for label, params in (
        ("loja", {"official_store_id": config.official_store_id, "limit": 3}),
        ("vendedor", {"seller_id": args.seller_id, "limit": 3}),
    ):
        try:
            page = api.get("/sites/MLB/search", params)
        except ApiError as exc:
            print(f"busca por {label}: ERRO {exc}")
            continue
        print(f"busca por {label}: total={page.get('paging', {}).get('total')}")
        for r in page.get("results", []):
            print(f"   {r.get('id')} | {r.get('title', '')[:70]} | {r.get('price')} | cat={r.get('category_id')}")
        for f in page.get("available_filters", []):
            if f.get("id") == "category":
                print("   categorias:", json.dumps(
                    [(v.get("name"), v.get("results")) for v in f.get("values", [])], ensure_ascii=False)[:1500])
    if args.full:
        collector = ApiCollector(api, config.official_store_id, config.data_dir / "categories_cache.json")
        result = collector.run()
        print(f"coleta completa: {len(result.products)} produtos, total informado={result.total_reported}, "
              f"{result.pages_fetched} requisições, {len(result.errors)} avisos")
    return 0


def cmd_diagnose(args: argparse.Namespace, config: Config) -> int:
    """Baixa a vitrine e a listagem e mostra o que o parser enxerga (sem salvar nada)."""
    import re

    from .parse import find_store_listing_link, parse_listing

    if args.browser:
        config.fetcher = "browser"
    fetcher = make_fetcher(config)
    fetcher.check_blocks = False
    urls = args.url if args.url else [config.store_page_url, config.store_listing_url]
    try:
        for url in urls:
            print(f"\n=== {url}")
            try:
                final, html = fetcher.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"ERRO: {exc}")
                continue
            print(describe(final, "ok", html))
            print("bloqueio:", block_reason(final, html) or "não detectado")
            for marker in ("poly-card", "ui-search-layout__item", "ui-search-filter-dl",
                           "__PRELOADED_STATE__", "andes-money-amount", "g-recaptcha", "captcha"):
                print(f"  {marker}: {html.count(marker)}")
            links = sorted(set(re.findall(r'href="([^"]+)"', html)))
            interesting = [l for l in links if re.search(r"lista\.mercadolivre|_Loja_|official_store|/farmacia", l)]
            print(f"links: {len(links)} total, {len(interesting)} relevantes")
            for link in interesting[:25]:
                print("  ", link[:200])
            print("listagem descoberta:", find_store_listing_link(html, final))
            page = parse_listing(html, final)
            print(f"parser: {len(page.products)} produtos, total={page.total}, "
                  f"{len(page.categories)} categorias, próxima={page.next_url}")
            for c in page.categories[:15]:
                print(f"   cat: {c.name} ({c.results}) {c.url[:120]}")
            for p in page.products[:5]:
                print(f"   prod: {p.item_id} | {p.title[:70]} | {p.price} | {p.url[:90]}")
            if not page.products:
                text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
                print("texto visível (início):", " ".join(text.split())[:800])
            if args.deep:
                _deep_report(html)
    finally:
        fetcher.close()
    return 0


def _deep_report(html: str) -> None:
    """Detalhes da estrutura da página, para adaptar o parser a um layout desconhecido."""
    import re
    from collections import Counter

    classes = Counter()
    for attr in re.findall(r'class="([^"]+)"', html):
        for c in attr.split():
            classes[c] += 1
    keys = ("card", "item", "product", "price", "title", "result", "carousel", "grid", "pagination", "filter", "tab")
    print("classes relevantes (top 60):")
    for c, n in [(c, n) for c, n in classes.most_common() if any(k in c.lower() for k in keys)][:60]:
        print(f"   {n:4d} {c}")
    item_links = sorted(set(re.findall(r'href="([^"]*MLB-?\d{6,}[^"]*)"', html)))
    print(f"links com id MLB: {len(item_links)}")
    for link in item_links[:8]:
        print("   ", link[:180])
    other = sorted(set(l for l in re.findall(r'href="([^"]+)"', html)
                       if re.search(r"farma|_Loja_|official|/loja/|page=|_Desde_|_NoIndex", l, re.I)))
    print(f"links farma/loja/paginação: {len(other)}")
    for link in other[:40]:
        print("   ", link[:180])
    for marker in ('"polycard"', '"results"', '"paging"', '"total"', '"official_store_id"', '"category_id"',
                   '"available_filters"', '"pagination"', '"items"', "window.__", "_n.ctx"):
        idx = html.find(marker)
        ctx = html[max(0, idx - 80): idx + 220].replace("\n", " ") if idx >= 0 else ""
        print(f"  {marker}: {html.count(marker)}  {ctx[:300]!r}" if idx >= 0 else f"  {marker}: 0")
    for sid in re.findall(r'official_store_id["=:\s]+"?(\d+)', html)[:5]:
        print("   official_store_id =", sid)
    i = html.find("andes-money-amount")
    if i >= 0:
        start = html.rfind("<a ", 0, i)
        start = max(start - 1500, 0) if start >= 0 else max(i - 2500, 0)
        print("HTML em volta do primeiro preço:")
        print(html[start: i + 1500])


def cmd_report(args: argparse.Namespace, config: Config) -> int:
    storage = Storage(config.data_dir)
    out = write_dashboard(storage, config.docs_dir)
    logging.info("Dashboard gerado em %s", out)
    return 0


def cmd_summary(args: argparse.Namespace, config: Config) -> int:
    _publish_summary(markdown_summary(Storage(config.data_dir)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meli-farma", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scrape", help="coleta os produtos e atualiza histórico e dashboard")
    p.add_argument("--url", help="URL da listagem da loja (pula a descoberta pela vitrine)")
    p.add_argument("--browser", action="store_true", help="usa Chromium via Playwright")
    p.add_argument("--no-report", action="store_true", help="não regera o dashboard")
    p.add_argument("--source", choices=["auto", "api", "site"], help="API oficial ou HTML do site (padrão: auto)")
    p.set_defaults(func=cmd_scrape)

    p = sub.add_parser("diagnose", help="mostra o que o scraper vê na vitrine e na listagem")
    p.add_argument("--url", action="append", help="URL(s) a diagnosticar (pode repetir)")
    p.add_argument("--deep", action="store_true", help="mostra classes, links e trechos do HTML")
    p.add_argument("--browser", action="store_true", help="usa Chromium via Playwright")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("diagnose-api", help="testa credenciais e busca da loja na API oficial")
    p.add_argument("--seller-id", default="2565839818")
    p.add_argument("--full", action="store_true", help="também roda a coleta completa (sem salvar)")
    p.set_defaults(func=cmd_diagnose_api)

    p = sub.add_parser("report", help="regera docs/index.html a partir dos dados salvos")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("summary", help="imprime o resumo da última coleta em Markdown")
    p.set_defaults(func=cmd_summary)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return args.func(args, Config())


if __name__ == "__main__":
    raise SystemExit(main())

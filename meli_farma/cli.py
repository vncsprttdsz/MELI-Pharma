"""Linha de comando: ``python -m meli_farma {scrape,report,summary}``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Config
from .fetch import BlockedError, make_fetcher
from .report import markdown_summary, write_dashboard
from .scraper import Scraper
from .storage import Storage


def _publish_summary(text: str) -> None:
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def cmd_scrape(args: argparse.Namespace, config: Config) -> int:
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
    p.set_defaults(func=cmd_scrape)

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

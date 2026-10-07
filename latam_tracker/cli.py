"""Linha de comando: ``python -m latam_tracker {run,report,summary,diagnose}``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .config import Config
from .fetch import FetchError, make_fetcher
from .notify import notify
from .parse import extract_offers
from .report import analyze, markdown_summary, write_dashboard
from .storage import Storage
from .tracker import run


def _publish_summary(text: str) -> None:
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def _analysis(config: Config) -> dict:
    storage = Storage(config.data_dir)
    return analyze(config, storage.quotes(), storage.searches())


def cmd_run(args: argparse.Namespace, config: Config) -> int:
    try:
        fetcher = make_fetcher(config)
    except FetchError as exc:
        logging.error("%s", exc)
        return 2
    try:
        result = run(config, fetcher)
    finally:
        fetcher.close()
    if len(result.failed) == len(result.searches):
        logging.error("Todas as buscas falharam; nada foi salvo. Rode com LATAM_DEBUG_DIR=debug para inspecionar.")
        return 1
    Storage(config.data_dir).save(result.quotes, result.searches)
    a = _analysis(config)
    write_dashboard(config, a)
    _publish_summary(markdown_summary(config, a))
    if a["alerts"]:
        notify(config, f"LATAM {config.origin}⇄{config.destination}", "\n".join(a["alerts"]))
    return 3 if result.failed else 0


def cmd_report(args: argparse.Namespace, config: Config) -> int:
    path = write_dashboard(config, _analysis(config))
    print(f"Dashboard gravado em {path}")
    return 0


def cmd_summary(args: argparse.Namespace, config: Config) -> int:
    _publish_summary(markdown_summary(config, _analysis(config)))
    return 0


def cmd_diagnose(args: argparse.Namespace, config: Config) -> int:
    """Uma busca só, mostrando o que foi capturado e as tarifas reconhecidas (inclui voos com escala)."""
    config.debug_dir = config.debug_dir or __import__("pathlib").Path("debug")
    origin, dest = (config.destination, config.origin) if args.back else (config.origin, config.destination)
    day = args.date or (config.inbound if args.back else config.outbound)
    fetcher = make_fetcher(config)
    try:
        payload = fetcher.search(origin, dest, day, args.points)
    except FetchError as exc:
        print(f"FALHOU: {exc}\n(arquivos de depuração em {config.debug_dir}/)")
        return 1
    finally:
        fetcher.close()
    offers = extract_offers(payload)
    print(f"{origin}→{dest} {day} ({'pontos' if args.points else 'dinheiro'}): {len(offers)} tarifas reconhecidas")
    for o in sorted(offers, key=lambda o: o["price"]):
        print(f"  {o['flight']:<16} {o['depart'][:16]:<16} escalas={o['stops']} {o['brand']:<12} "
              f"{o['price']:>10,.0f} {o['currency']} taxas={o['taxes']}")
    if not offers:
        print("JSON capturado (início):\n" + json.dumps(payload, ensure_ascii=False)[:2000])
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="latam_tracker", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="consulta a LATAM, grava o histórico, gera o dashboard e avisa quedas de preço")
    r.add_argument("--fetcher", choices=["browser", "api"])
    r.add_argument("--headed", action="store_true", help="mostra a janela do navegador")
    sub.add_parser("report", help="só regera docs/latam.html")
    sub.add_parser("summary", help="resumo da última consulta em Markdown")
    d = sub.add_parser("diagnose", help="uma busca isolada para conferir se a coleta funciona")
    d.add_argument("--date", help="AAAA-MM-DD (padrão: data central)")
    d.add_argument("--back", action="store_true", help="trecho de volta")
    d.add_argument("--points", action="store_true", help="busca em pontos")
    d.add_argument("--fetcher", choices=["browser", "api"])
    d.add_argument("--headed", action="store_true")
    args = p.parse_args(argv)
    config = Config.from_env()
    if getattr(args, "fetcher", None):
        config.fetcher = args.fetcher
    if getattr(args, "headed", False):
        config.headless = False
    return {"run": cmd_run, "report": cmd_report, "summary": cmd_summary, "diagnose": cmd_diagnose}[args.cmd](args, config)


if __name__ == "__main__":
    sys.exit(main())

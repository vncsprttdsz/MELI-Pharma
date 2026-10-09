"""Linha de comando: ``python -m latam_tracker {run,report,summary,diagnose}``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Config
from .fetch import FetchError, make_fetcher
from .notify import notify
from .report import alert_message, analyze, markdown_summary, write_dashboard
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
    fetchers = {}
    try:
        for mode in config.modes:
            fetchers[mode] = make_fetcher(config, mode)
        result = run(config, fetchers)
    except FetchError as exc:
        logging.error("%s", exc)
        return 2
    finally:
        for f in fetchers.values():
            f.close()
    if len(result.failed) == len(result.searches):
        logging.error("Todas as buscas falharam; nada foi salvo. Rode com LATAM_DEBUG_DIR=debug para inspecionar.")
        return 1
    Storage(config.data_dir).save(result.quotes, result.searches)
    a = _analysis(config)
    write_dashboard(config, a)
    _publish_summary(markdown_summary(config, a))
    if a["alerts"]:
        notify(config, f"✈️ LATAM {config.origin}⇄{config.destination}: preço caiu", alert_message(config, a))
    return 3 if result.failed else 0


def cmd_report(args: argparse.Namespace, config: Config) -> int:
    path = write_dashboard(config, _analysis(config))
    print(f"Dashboard gravado em {path}")
    return 0


def cmd_test_notify(args: argparse.Namespace, config: Config) -> int:
    """Manda uma mensagem de teste pelos canais configurados (WhatsApp/ntfy)."""
    if not (config.whatsapp_phone and config.whatsapp_apikey) and not config.ntfy_topic:
        logging.error("Nenhum canal configurado (LATAM_WHATSAPP_PHONE + LATAM_WHATSAPP_APIKEY ou LATAM_NTFY_TOPIC).")
        return 2
    a = _analysis(config)
    body = alert_message(config, a) if a["latest"] else "Ainda sem consultas registradas."
    ok = notify(config, "✈️ Teste do monitor LATAM", body)
    return 0 if ok else 1


def cmd_summary(args: argparse.Namespace, config: Config) -> int:
    _publish_summary(markdown_summary(config, _analysis(config)))
    return 0


def cmd_diagnose(args: argparse.Namespace, config: Config) -> int:
    """Uma busca só, mostrando o que foi capturado e as tarifas reconhecidas (inclui voos com escala)."""
    config.debug_dir = config.debug_dir or __import__("pathlib").Path("debug")
    origin, dest = (config.destination, config.origin) if args.back else (config.origin, config.destination)
    day = args.date or (config.inbound if args.back else config.outbound)
    try:
        fetcher = make_fetcher(config, "points" if args.points else "cash")
        try:
            offers = fetcher.offers(origin, dest, day, args.points)
        finally:
            fetcher.close()
    except FetchError as exc:
        print(f"FALHOU: {exc}\n(arquivos de depuração em {config.debug_dir}/)")
        return 1
    print(f"{origin}→{dest} {day} ({'pontos' if args.points else 'dinheiro'}): {len(offers)} tarifas reconhecidas")
    for o in sorted(offers, key=lambda o: o["price"]):
        print(f"  {o['flight']:<16} {o['depart'][:16]:<16} escalas={o['stops']} {o['brand']:<12} "
              f"{o['price']:>10,.0f} {o['currency']} taxas={o['taxes']}")
    return 0 if offers else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="latam_tracker", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="consulta a LATAM, grava o histórico, gera o dashboard e avisa quedas de preço")
    r.add_argument("--fetcher", choices=["browser", "api"])
    r.add_argument("--headed", action="store_true", help="mostra a janela do navegador")
    sub.add_parser("report", help="só regera docs/latam.html")
    sub.add_parser("summary", help="resumo da última consulta em Markdown")
    sub.add_parser("test-notify", help="envia uma mensagem de teste no WhatsApp/ntfy")
    d = sub.add_parser("diagnose", help="uma busca isolada para conferir se a coleta funciona")
    d.add_argument("--date", help="AAAA-MM-DD (padrão: data central)")
    d.add_argument("--back", action="store_true", help="trecho de volta")
    d.add_argument("--points", action="store_true", help="busca em pontos")
    d.add_argument("--fetcher", choices=["browser", "api"])
    d.add_argument("--source", choices=["google", "latam"], help="fonte do preço em dinheiro")
    d.add_argument("--headed", action="store_true")
    args = p.parse_args(argv)
    config = Config.from_env()
    if getattr(args, "fetcher", None):
        config.fetcher = args.fetcher
    if getattr(args, "source", None):
        config.cash_source = args.source
    if getattr(args, "headed", False):
        config.headless = False
    return {"run": cmd_run, "report": cmd_report, "summary": cmd_summary, "test-notify": cmd_test_notify, "diagnose": cmd_diagnose}[args.cmd](args, config)


if __name__ == "__main__":
    sys.exit(main())

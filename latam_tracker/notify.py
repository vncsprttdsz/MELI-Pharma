"""Avisos de queda de preço via ntfy.sh (app gratuito para Android/iOS) e notificação do Termux."""

from __future__ import annotations

import logging
import shutil
import subprocess

from .config import Config

log = logging.getLogger(__name__)


def notify(config: Config, title: str, message: str) -> None:
    if config.ntfy_topic:
        try:
            import requests

            requests.post(
                "https://ntfy.sh/",
                json={"topic": config.ntfy_topic, "title": title, "message": message, "tags": ["airplane"]},
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001 - aviso não pode derrubar a coleta
            log.warning("Falha ao enviar ntfy: %s", exc)
    if shutil.which("termux-notification"):
        subprocess.run(["termux-notification", "--id", "7202", "--title", title, "--content", message], check=False)

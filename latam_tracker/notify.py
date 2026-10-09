"""Avisos de queda de preço: WhatsApp (CallMeBot), ntfy.sh e notificação do Termux."""

from __future__ import annotations

import logging
import shutil
import subprocess

from .config import Config

log = logging.getLogger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def send_whatsapp(config: Config, text: str) -> bool:
    """Envia ``text`` para o próprio WhatsApp via CallMeBot (grátis, só para o seu número)."""
    import requests

    phone = "".join(ch for ch in config.whatsapp_phone if ch.isdigit())
    try:
        r = requests.get(CALLMEBOT_URL, params={"phone": phone, "text": text, "apikey": config.whatsapp_apikey},
                         timeout=30)
    except requests.RequestException as exc:
        log.warning("Falha ao enviar WhatsApp: %s", exc)
        return False
    # O CallMeBot responde 200 mesmo em alguns erros; o corpo diz se a mensagem foi enfileirada.
    body = r.text.lower()
    if r.status_code != 200 or "error" in body or "apikey is invalid" in body:
        log.warning("CallMeBot recusou a mensagem (HTTP %s): %s", r.status_code, r.text[:300])
        return False
    log.info("WhatsApp enviado")
    return True


def notify(config: Config, title: str, message: str) -> bool:
    """Manda o aviso por todos os canais configurados. True se ao menos um funcionou."""
    sent = False
    if config.whatsapp_phone and config.whatsapp_apikey:
        sent |= send_whatsapp(config, f"*{title}*\n{message}")
    if config.ntfy_topic:
        try:
            import requests

            requests.post(
                "https://ntfy.sh/",
                json={"topic": config.ntfy_topic, "title": title, "message": message, "tags": ["airplane"]},
                timeout=20,
            ).raise_for_status()
            sent = True
        except Exception as exc:  # noqa: BLE001 - aviso não pode derrubar a coleta
            log.warning("Falha ao enviar ntfy: %s", exc)
    if shutil.which("termux-notification"):
        subprocess.run(["termux-notification", "--id", "7202", "--title", title, "--content", message], check=False)
        sent = True
    return sent

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
        # Formato da documentação do CallMeBot: DDI com "+" (ex.: +5511999998888). A apikey vai sem espaços.
        r = requests.get(CALLMEBOT_URL, params={"phone": "+" + phone, "text": text,
                                                "apikey": config.whatsapp_apikey.strip()},
                         timeout=30)
    except requests.RequestException as exc:
        log.warning("Falha ao enviar WhatsApp: %s", exc)
        return False
    # O CallMeBot responde 203 quando aceita a mensagem ("Message to: ... Text to send: ...") e às vezes
    # 2xx também em erros; o corpo diz se deu certo. O log mascara o número e a apikey.
    import re

    text_only = " ".join(re.sub(r"<[^>]+>", " ", r.text).split())
    for secret in filter(None, (config.whatsapp_phone, phone, config.whatsapp_apikey)):
        text_only = text_only.replace(secret, "***")
    # O corpo repete a mensagem enviada ("Text to send: ..."); só o que vem depois dela diz o resultado.
    status_part = text_only.split("Text to send:", 1)[-1].lower()
    status_part = status_part.replace(text.lower(), "")
    markers = ("apikey is invalid", "invalid apikey", "not activated", "error", "paused", "blocked")
    hit = next((k for k in markers if k in status_part[-400:]), None)
    if not 200 <= r.status_code < 300 or hit:
        log.warning("CallMeBot recusou a mensagem (HTTP %s, motivo: %s). Fim da resposta: %s",
                    r.status_code, hit or "status HTTP", text_only[-400:])
        return False
    log.info("WhatsApp enviado. Resposta: %s", text_only[-200:])
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

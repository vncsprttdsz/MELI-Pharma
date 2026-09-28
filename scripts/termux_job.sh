#!/data/data/com.termux/files/usr/bin/bash
# Chamado pelo agendador do Android. Dispara a coleta em segundo plano e retorna logo,
# porque o Android encerra jobs agendados que passam de ~10 minutos.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
nohup bash "$REPO/scripts/termux_run.sh" >> "$HOME/meli-farma.log" 2>&1 &

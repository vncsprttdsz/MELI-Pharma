#!/data/data/com.termux/files/usr/bin/bash
# Configuração única no Termux (Android). Rode de dentro do repositório clonado:
#   bash scripts/termux_setup.sh
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Instalando pacotes"
pkg update -y
pkg install -y python git termux-api
pkg install -y python-lxml || echo "(python-lxml indisponível; o parser embutido será usado)"
pip install --upgrade requests beautifulsoup4

echo "==> Configurando git"
git -C "$REPO" config user.name  >/dev/null || git -C "$REPO" config user.name "Coletor MELI Farma (celular)"
git -C "$REPO" config user.email >/dev/null || git -C "$REPO" config user.email "coletor@users.noreply.github.com"
git -C "$REPO" config credential.helper store
git -C "$REPO" config pull.rebase true

chmod +x "$REPO"/scripts/termux_*.sh

echo "==> Agendando a coleta diária (a cada 24h, com internet)"
termux-job-scheduler --job-id 7101 --period-ms 86400000 --persisted true --network any \
  --script "$REPO/scripts/termux_job.sh"
termux-job-scheduler --pending

echo
echo "Pronto. Para testar agora:   bash $REPO/scripts/termux_run.sh"
echo "Log das coletas:             tail -n 50 ~/meli-farma.log"

#!/usr/bin/env bash
# Consulta a LATAM + commit + push, para rodar de um computador em casa (Linux/macOS/WSL) via cron:
#   7 5,11,15,20 * * *  bash /caminho/flights/scripts/latam_run.sh >> ~/latam.log 2>&1
# No Termux use LATAM_FETCHER=api (não há Chromium para o Playwright no Android).
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
echo "===== $(date '+%F %T') início"
git pull --rebase --quiet || echo "aviso: git pull falhou, seguindo com a cópia local"
python3 -m latam_tracker run
code=$?
if [ "$code" = 0 ] || [ "$code" = 3 ]; then
  git add data/latam docs/latam.html
  if ! git diff --cached --quiet; then
    git commit --quiet -m "latam: consulta de $(date '+%F %H:%M') (local)"
    for i in 1 2 3; do git pull --rebase --quiet && git push --quiet && break; sleep $((i * 15)); done
  fi
else
  echo "consulta falhou (código $code)"
fi
echo "===== $(date '+%F %T') fim"

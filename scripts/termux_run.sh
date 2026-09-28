#!/data/data/com.termux/files/usr/bin/bash
# Coleta + commit + push. Pode ser rodado manualmente a qualquer momento.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$HOME/.meli-farma.lock"
cd "$REPO" || exit 1

if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  echo "$(date '+%F %T') coleta já em andamento; saindo."
  exit 0
fi
echo $$ > "$LOCK"
command -v termux-wake-lock >/dev/null && termux-wake-lock
cleanup() { rm -f "$LOCK"; command -v termux-wake-unlock >/dev/null && termux-wake-unlock; }
trap cleanup EXIT

echo "===== $(date '+%F %T') início da coleta"
git pull --quiet || echo "aviso: git pull falhou, seguindo com a cópia local"

if MELI_SOURCE=site python -m meli_farma scrape; then
  git add data docs
  if git diff --cached --quiet; then
    echo "sem mudanças para commitar"
  else
    git commit --quiet -m "dados: coleta de $(date +%F) (celular)"
    for i in 1 2 3; do
      git push --quiet && break
      echo "push falhou (tentativa $i); tentando de novo"
      sleep $((i * 20)); git pull --quiet
    done
  fi
  command -v termux-notification >/dev/null && termux-notification --id 7101 \
    --title "MELI Farma" --content "Coleta de $(date +%F) concluída"
else
  echo "coleta falhou (código $?)"
  command -v termux-notification >/dev/null && termux-notification --id 7101 \
    --title "MELI Farma" --content "Coleta falhou — veja ~/meli-farma.log"
fi
echo "===== $(date '+%F %T') fim"

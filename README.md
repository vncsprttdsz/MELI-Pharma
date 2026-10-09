# Tracker de preços LATAM (GRU ⇄ LAX)

Roda no GitHub Actions 4x por dia e guarda o preço **em dinheiro** dos **voos diretos da LATAM** de uma
viagem com datas flexíveis. Padrão: ida GRU→LAX em 01/04/2027 e volta LAX→GRU em 10/04/2027, ±1 dia em
cada perna, 1 adulto, econômica.

- **Dinheiro:** vem do **Google Flights** (filtrado para voos LATAM sem escala, em R$). O site da LATAM
  responde 403 a partir dos servidores do GitHub, mas o Google Flights não.
- **Pontos:** desligado. A busca em pontos no site da LATAM exige login no LATAM Pass e também é bloqueada
  a partir do GitHub. O código continua aqui (`LATAM_MODES=cash,points`) para uso com proxy residencial
  (`LATAM_PROXY`) ou num computador próprio (`scripts/latam_run.sh`). Fora do site da LATAM, as opções
  encontradas foram buscadores manuais (EconoMilha, TKMilhas), alertas do Flypass.ai e a API paga da
  Buscamilhas.

São 6 buscas só de ida por consulta (3 datas de ida + 3 de volta). As combinações ida+volta são a soma
das duas pernas; comprar ida e volta juntas pode sair mais barato.

## Uso

```bash
pip install -r requirements.txt
python -m latam_tracker diagnose                         # 1 busca (ida 01/04) no Google Flights
python -m latam_tracker diagnose --back --date 2027-04-11
python -m latam_tracker run                              # consulta tudo, grava histórico, gera docs/latam.html
python -m latam_tracker summary                          # resumo em Markdown da última consulta
python -m latam_tracker test-notify                      # mensagem de teste no WhatsApp/ntfy
```

`run` sai com código 3 quando parte das buscas falhou (o resto é salvo).

## Agendamento

`.github/workflows/latam.yml` roda 4x/dia (05h, 11h, 15h e 20h de Brasília) e commita `data/latam/` e
`docs/latam.html`. Também pode ser disparado em **Actions → Preços LATAM GRU-LAX → Run workflow** (com
opção "Só diagnosticar"). `.github/workflows/latam-probe.yml` testa as formas de acesso ao site da LATAM
(Chromium, Chrome, Patchright, Camoufox, API); em 07/10/2026 todas receberam 403.

## Alertas no WhatsApp

Quando o preço cai, o tracker manda uma mensagem para o seu WhatsApp pelo
[CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/), que é gratuito e só envia para o seu
próprio número. Ele avisa quando:

- o **voo ideal** (ida + volta nas datas centrais) cai mais de `LATAM_ALERT_DROP_PCT` (3%) desde a consulta anterior;
- o preço de alguma data cai mais de 3% ou atinge o menor valor já registrado.

Configuração (uma vez):

1. Salve o número do bot do CallMeBot nos contatos (confira o número atual no site, ele muda de vez em quando) e
   mande para ele pelo WhatsApp: `I allow callmebot to send me messages`.
2. Ele responde com a sua **apikey**.
3. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   - `LATAM_WHATSAPP_PHONE`: seu número com DDI e DDD, ex.: `5511999998888`
   - `LATAM_WHATSAPP_APIKEY`: a apikey recebida
4. Teste em **Actions → Preços LATAM GRU-LAX → Run workflow**, marcando "Só enviar uma mensagem de teste".

Também dá para receber pelo app **ntfy** (secret `LATAM_NTFY_TOPIC`), sozinho ou junto com o WhatsApp.

## Dados

| Arquivo | Conteúdo |
|---|---|
| `data/latam/quotes.csv` | uma linha por consulta × trecho × data × modo × voo direto × tarifa (Light, Standard...) |
| `data/latam/searches.csv` | uma linha por busca: `ok`, `no_direct` (só voos com escala), `no_offers` ou `error` |
| `docs/latam.html` | dashboard: voo ideal, gráfico do histórico (total por padrão; ida, volta e melhor combinação no seletor), combinações e tarifas por data |

Para ver o dashboard no navegador: **Settings → Pages → Deploy from a branch →
`claude/meli-farma-scraping-monitor-xjxte3` / `docs`**. Ele fica em
<https://vncsprttdsz.github.io/flights/latam.html> (a raiz redireciona para ele).

## Configuração

| Variável | Padrão | |
|---|---|---|
| `LATAM_ORIGIN` / `LATAM_DESTINATION` | `GRU` / `LAX` | |
| `LATAM_OUTBOUND` / `LATAM_INBOUND` | `2027-04-01` / `2027-04-10` | datas centrais |
| `LATAM_FLEX_DAYS` | `1` | dias para mais/menos em cada perna |
| `LATAM_ADULTS` | `1` | |
| `LATAM_CABIN` | `Economy` | `Premium`, `Business` |
| `LATAM_MODES` | `cash` | `cash,points` liga pontos (site da LATAM; exige login e acesso não bloqueado) |
| `LATAM_CASH_SOURCE` | `google` | `latam` = preço em dinheiro pelo site da LATAM |
| `LATAM_ENGINE` | `chromium` | navegador do site da LATAM: `patchright`, `camoufox` |
| `LATAM_PROXY` | — | proxy (ex.: residencial) para o site da LATAM |
| `LATAM_DIRECT_ONLY` | `1` | `0` guarda também voos com escala |
| `LATAM_FETCHER` | `browser` | site da LATAM: `api` = chamada direta sem navegador |
| `LATAM_DELAY` | `8` | segundos entre buscas (+ até 50% aleatório) |
| `LATAM_HEADLESS` | `1` | `0` abre a janela do navegador |
| `LATAM_BROWSER_PATH` | — | Chrome/Chromium já instalado |
| `LATAM_DEBUG_DIR` | — | salva o JSON/HTML de cada busca |
| `LATAM_WHATSAPP_PHONE` / `LATAM_WHATSAPP_APIKEY` | — | WhatsApp via CallMeBot |
| `LATAM_NTFY_TOPIC` | — | tópico do ntfy para alertas |
| `LATAM_DASHBOARD_URL` | página do GitHub Pages | link enviado nos avisos |
| `LATAM_ALERT_DROP_PCT` | `3` | queda mínima (%) para alertar |

## Limitações

- O Google Flights é acessado pela API interna (biblioteca [`fli`](https://github.com/punitarani/fli)); pode
  mudar sem aviso. O preço costuma ser o mesmo do site da LATAM, mas não é garantido.
- O modo pelo site da LATAM (`LATAM_CASH_SOURCE=latam` ou pontos) usa a API de ofertas do site
  (`/bff/air-offers/v2/offers/search`), que não é pública. Ele **nunca coletou dados reais**: a LATAM
  responde 403 a partir do GitHub, e a busca em pontos exige login no LATAM Pass.
- Preço em pontos é registrado com as taxas em R$ quando o site as informa na busca.
- Consultas automatizadas podem violar os termos de uso do site; mantenha poucas consultas por dia.

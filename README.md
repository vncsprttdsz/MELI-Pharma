# MELI Farma — monitor de produtos

Coleta diária dos produtos da loja oficial
[Mercado Livre Farma](https://www.mercadolivre.com.br/farmacia/mercadolivrefarma) para acompanhar:

- a **quantidade de produtos listados** ao longo do tempo;
- a **lista de produtos** com **preço** (e preço "de", quando há desconto);
- a **categoria** de cada produto (ex.: `Medicamentos > Analgésicos`) e a evolução da oferta por categoria;
- produtos **novos**, **removidos** e com **preço alterado** entre uma coleta e outra.

O resultado vira um dashboard estático em `docs/index.html` (pode ser publicado no GitHub Pages).

## Fontes de dados

O coletor tem dois modos (`MELI_SOURCE=site|api`, padrão `site`):

- **API oficial** (`api.mercadolibre.com`): **hoje não funciona para esta loja** — a busca por loja/vendedor
  responde 403 ("Searching another user items is restricted") mesmo com token. Mantido para o caso de o
  acesso ser liberado. Busca os itens da loja oficial `244622`
  com token de aplicativo. Precisa dos secrets `MELI_CLIENT_ID` e `MELI_CLIENT_SECRET`
  (veja [Configurar a API](#configurar-a-api)). A categoria de cada produto é o caminho completo da
  categoria do anúncio (ex.: `Saúde > Medicamentos > Analgésicos`).
- **HTML do site** (padrão): não precisa de cadastro, mas o Mercado Livre exige login para acessos a
  partir de servidores, então roda de uma conexão residencial/móvel — veja
  [Coleta diária no celular](#coleta-diária-no-celular-termux).

## Configurar a API

1. Entre em <https://developers.mercadolivre.com.br/devcenter> com sua conta do Mercado Livre e crie
   uma aplicação (nome e descrição livres; URI de redirect pode ser a URL deste repositório;
   escopo de leitura).
2. Copie o **App ID** (Client ID) e a **Secret Key**.
3. No GitHub: **Settings → Secrets and variables → Actions → New repository secret** e crie
   `MELI_CLIENT_ID` e `MELI_CLIENT_SECRET`.
4. Em **Actions → Coleta diária → Run workflow**, marque "Só testar a API" para validar.

Localmente: `MELI_CLIENT_ID=... MELI_CLIENT_SECRET=... python -m meli_farma diagnose-api`.

## Como funciona (modo HTML)

1. Abre a vitrine da loja e descobre o link da listagem completa (`lista.mercadolivre.com.br/_Loja_mercadolivrefarma`).
   Se não achar, usa `MELI_STORE_LISTING_URL`.
2. Lê o filtro **Categorias** da listagem e entra em cada categoria (e nas subcategorias, até `MELI_CATEGORY_DEPTH`).
   A categoria do produto é o caminho de filtros em que ele foi encontrado.
3. Pagina cada listagem e extrai id (`MLB…`), título, preço, preço anterior, marca, frete grátis, avaliação.
   O parser usa os seletores HTML atuais (`poly-card`), o layout antigo (`ui-search`) e o JSON embutido na página
   como alternativa, porque o Mercado Livre muda o markup com frequência.
4. O Mercado Livre só deixa navegar ~2.000 resultados por listagem. Categorias maiores que isso são subdivididas
   automaticamente; se ainda assim passarem do limite, a coleta registra um aviso de cobertura parcial.

## Dados gerados

| Arquivo | Conteúdo |
|---|---|
| `data/snapshots/AAAA-MM-DD.csv.gz` | todos os produtos da coleta do dia |
| `data/history/runs.csv` | uma linha por coleta: produtos coletados, total informado pelo ML, páginas, erros |
| `data/history/categories.csv` | por dia e categoria (todos os níveis): nº de produtos, total informado pelo ML, preço médio/mediano/mín/máx, nº com desconto |
| `data/products.csv` | cadastro de todo produto já visto: primeira e última data, se está ativo, último preço |
| `data/history/last_run_errors.json` | avisos da última coleta |
| `docs/index.html` | dashboard |

Rodar mais de uma vez no mesmo dia substitui os dados daquele dia.

## Uso

```bash
pip install -r requirements.txt
python -m latam_tracker diagnose                         # 1 busca (ida 01/04) no Google Flights
python -m latam_tracker diagnose --back --date 2027-04-11
python -m latam_tracker run                              # consulta tudo, grava histórico, gera docs/latam.html
python -m latam_tracker summary                          # resumo em Markdown da última consulta
```

`run` sai com código 3 quando parte das buscas falhou (o resto é salvo).

## Agendamento

`.github/workflows/latam.yml` roda 4x/dia (05h, 11h, 15h e 20h de Brasília) e commita `data/latam/` e
`docs/latam.html`. Também pode ser disparado em **Actions → Preços LATAM GRU-LAX → Run workflow** (com
opção "Só diagnosticar"). `.github/workflows/latam-probe.yml` testa as formas de acesso ao site da LATAM
(Chromium, Chrome, Patchright, Camoufox, API); em 07/10/2026 todas receberam 403.

## Alertas no celular

Instale o app **ntfy** (Android/iOS), assine um tópico com nome difícil de adivinhar (ex.:
`latam-lax-8f3k2`) e crie o secret `LATAM_NTFY_TOPIC` com esse nome (ou exporte a variável no cron local).
Você recebe um aviso quando o preço de uma data cai mais de `LATAM_ALERT_DROP_PCT` (3%) em relação à
consulta anterior ou atinge o menor valor já registrado.

## Dados

| Arquivo | Conteúdo |
|---|---|
| `data/latam/quotes.csv` | uma linha por consulta × trecho × data × modo × voo direto × tarifa (Light, Standard...) |
| `data/latam/searches.csv` | uma linha por busca: `ok`, `no_direct` (só voos com escala), `no_offers` ou `error` |
| `docs/latam.html` | dashboard: melhor tarifa por data, ranking ida+volta e gráfico do histórico |

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
| `LATAM_NTFY_TOPIC` | — | tópico do ntfy para alertas |
| `LATAM_ALERT_DROP_PCT` | `3` | queda mínima (%) para alertar |

## Limitações

- O Google Flights é acessado pela API interna (biblioteca [`fli`](https://github.com/punitarani/fli)); pode
  mudar sem aviso. O preço costuma ser o mesmo do site da LATAM, mas não é garantido.
- A API de ofertas do site (`/bff/air-offers/v2/offers/search`) não é pública: o parser
  (`latam_tracker/parse.py`) foi escrito para o formato conhecido e é tolerante a variações, mas **ainda
  não foi validado contra o site real**. Na primeira execução rode `diagnose` e, se vier 0 tarifas,
  confira o JSON salvo em `debug/`.
- Preço em pontos é registrado com as taxas em R$ quando o site as informa na busca.
- Consultas automatizadas podem violar os termos de uso do site; mantenha poucas consultas por dia.

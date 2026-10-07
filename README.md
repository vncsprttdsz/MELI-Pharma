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

## Uso local

```bash
pip install -r requirements.txt
python -m meli_farma scrape          # coleta + atualiza histórico + dashboard
python -m meli_farma report          # só regera docs/index.html
python -m meli_farma summary         # resumo da última coleta em Markdown
```

Se o site responder com captcha/verificação, tente pelo navegador headless:

```bash
pip install playwright && python -m playwright install chromium
python -m meli_farma scrape --browser
```

### Configuração (variáveis de ambiente)

| Variável | Padrão | |
|---|---|---|
| `MELI_STORE_PAGE_URL` | vitrine da loja | página usada para descobrir a listagem |
| `MELI_STORE_LISTING_URL` | `https://lista.mercadolivre.com.br/_Loja_mercadolivrefarma` | listagem usada se a descoberta falhar |
| `MELI_CATEGORY_DEPTH` | `2` | até que nível de subcategoria descer |
| `MELI_DELAY` | `1.5` | segundos entre requisições (+ até 50% aleatório) |
| `MELI_MAX_PAGES` | `50` | máximo de páginas por listagem |
| `MELI_FETCHER` | `requests` | `browser` para usar Playwright |
| `MELI_DEBUG_DIR` | — | salva o HTML de cada página baixada (útil quando o parsing quebra) |

## Coleta diária no celular (Termux)

A listagem da loja exige login quando acessada a partir de servidores (inclusive o GitHub
Actions), mas abre normalmente de uma conexão residencial ou móvel. Por isso a coleta diária
roda num Android com [Termux](https://f-droid.org/packages/com.termux/):

1. Instale **Termux** e **Termux:API** pelo F-Droid (as versões da Play Store estão desatualizadas).
2. Crie um token do GitHub em **Settings → Developer settings → Fine-grained tokens**, com acesso
   só a este repositório e permissão **Contents: Read and write**.
3. No Termux:
   ```bash
   pkg install -y git
   git clone https://github.com/vncsprttdsz/MELI-Pharma.git
   cd MELI-Pharma
   bash scripts/termux_setup.sh
   bash scripts/termux_run.sh     # primeira coleta; pede usuário e token (como senha) no push
   ```
4. Nas configurações do Android, desative a otimização de bateria para Termux e Termux:API.

`termux_setup.sh` instala as dependências e agenda `termux_job.sh` para rodar a cada 24h (com
internet). Cada execução coleta, commita `data/` e `docs/` e faz push. Log: `~/meli-farma.log`.

## GitHub Actions

`.github/workflows/scrape.yml` roda só manualmente (**Actions → Coleta diária → Run workflow**), com
opções de diagnóstico do site e da API. O agendamento diário foi removido porque o acesso a partir
dos servidores do GitHub é bloqueado.

Para publicar o dashboard: **Settings → Pages → Deploy from a branch → `main` / `docs`**.

## Testes

```bash
pip install pytest
python -m pytest
```

Os testes usam páginas HTML sintéticas no formato das listagens do Mercado Livre (`tests/conftest.py`).

## Limitações

- O scraper ainda não foi validado contra o site real. Na primeira execução, confira o resumo e, se vier 0 produtos
  ou categorias vazias, rode com `MELI_DEBUG_DIR=debug` e ajuste os seletores em `meli_farma/parse.py`.
- IPs de datacenter (como os do GitHub Actions) podem ser bloqueados pelo Mercado Livre. Nesse caso use `--browser`
  ou rode a coleta de uma máquina própria (ex.: cron local) e faça push dos dados.
- Um produto que aparece em mais de uma categoria fica com a primeira em que foi encontrado.

---

# Tracker de preços LATAM (GRU ⇄ LAX)

Módulo separado (`latam_tracker/`) que consulta o site da LATAM algumas vezes por dia e guarda o
preço **em dinheiro e em pontos LATAM Pass** dos **voos diretos** de uma viagem com datas flexíveis.
Padrão: ida GRU→LAX em 01/04/2027 e volta LAX→GRU em 10/04/2027, ±1 dia em cada perna, 1 adulto, econômica.

São 12 buscas só de ida por consulta (3 datas de ida + 3 de volta, × dinheiro/pontos). As combinações
ida+volta são a soma das duas pernas.

> Hoje a LATAM opera GRU–LAX direto só **3x por semana** (ida ter/qui/sáb; volta qua/qui/dom). Nas
> datas de 2027 isso daria voo direto só em **qui 01/04** (ida) e **dom 11/04** (volta); as outras datas
> aparecem como "sem voo direto" até a malha de abril/2027 mudar. Vale considerar ampliar a janela
> (`LATAM_FLEX_DAYS=2` inclui ter 30/03 e sáb 03/04 na ida e qui 08/04 na volta).

## Uso

```bash
pip install -r requirements.txt playwright
python -m playwright install chromium

python -m latam_tracker diagnose            # 1 busca (ida, dinheiro) para ver se a coleta funciona
python -m latam_tracker diagnose --points --back --date 2027-04-11
python -m latam_tracker run                 # consulta tudo, grava histórico, gera docs/latam.html
python -m latam_tracker summary             # resumo em Markdown da última consulta
```

`run` sai com código 3 quando parte das buscas falhou (o resto é salvo).

## Agendamento

- **Computador em casa (recomendado):** `scripts/latam_run.sh` no cron, 4x/dia (instruções no topo do
  script). Consulta, commita `data/latam/` e `docs/latam.html` e faz push.
- **GitHub Actions** (`.github/workflows/latam.yml`): só manual (**Actions → Preços LATAM GRU-LAX → Run
  workflow**, com opção "Só diagnosticar"). O agendamento está desligado porque, no teste de 07/10/2026,
  a LATAM respondeu **403** à API de ofertas a partir dos servidores do GitHub (anti-robô).
- No celular (Termux) não há Chromium para o Playwright; dá para tentar `LATAM_FETCHER=api`, que chama a
  API do site direto, mas ela costuma ser barrada sem os cookies que o navegador gera.

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
| `LATAM_MODES` | `cash,points` | |
| `LATAM_DIRECT_ONLY` | `1` | `0` guarda também voos com escala |
| `LATAM_FETCHER` | `browser` | `api` = chamada direta sem navegador |
| `LATAM_DELAY` | `8` | segundos entre buscas (+ até 50% aleatório) |
| `LATAM_HEADLESS` | `1` | `0` abre a janela do navegador |
| `LATAM_BROWSER_PATH` | — | Chrome/Chromium já instalado |
| `LATAM_DEBUG_DIR` | — | salva o JSON/HTML de cada busca |
| `LATAM_NTFY_TOPIC` | — | tópico do ntfy para alertas |
| `LATAM_ALERT_DROP_PCT` | `3` | queda mínima (%) para alertar |

## Limitações

- A API de ofertas do site (`/bff/air-offers/v2/offers/search`) não é pública: o parser
  (`latam_tracker/parse.py`) foi escrito para o formato conhecido e é tolerante a variações, mas **ainda
  não foi validado contra o site real**. Na primeira execução rode `diagnose` e, se vier 0 tarifas,
  confira o JSON salvo em `debug/`.
- Preço em pontos é registrado com as taxas em R$ quando o site as informa na busca.
- Consultas automatizadas podem violar os termos de uso do site; mantenha poucas consultas por dia.

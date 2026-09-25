# MELI Farma — monitor de produtos

Coleta diária dos produtos da loja oficial
[Mercado Livre Farma](https://www.mercadolivre.com.br/farmacia/mercadolivrefarma) para acompanhar:

- a **quantidade de produtos listados** ao longo do tempo;
- a **lista de produtos** com **preço** (e preço "de", quando há desconto);
- a **categoria** de cada produto (ex.: `Medicamentos > Analgésicos`) e a evolução da oferta por categoria;
- produtos **novos**, **removidos** e com **preço alterado** entre uma coleta e outra.

O resultado vira um dashboard estático em `docs/index.html` (pode ser publicado no GitHub Pages).

## Como funciona

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

## Agendamento (GitHub Actions)

`.github/workflows/scrape.yml` roda todo dia às 06:07 (Brasília), commita `data/` e `docs/` no repositório e escreve
o resumo da coleta na página do job. Também dá para rodar manualmente em **Actions → Coleta diária → Run workflow**
(com a opção de usar o navegador). Para usar o navegador sempre, crie a variável de repositório `MELI_FETCHER=browser`.

Se a coleta falhar, o HTML baixado fica disponível como artefato `debug-html` por 7 dias.

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

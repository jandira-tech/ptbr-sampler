# Bibliography — ptbr-sampler data sources

The statistical assumptions in this repository are grounded in the following
primary sources. Each entry gives the publisher, coverage, and a stable URL.
For the complete audit that flagged each assumption and rated how well the
current data match external evidence, see
`deep-research-report(4).md` at the repository root.

## IBGE — Brazilian Institute of Geography and Statistics

### 1. Nomes no Brasil — 2022 Census release (IBGE, 2025)

Second edition of the *Nomes no Brasil* project, the first to include both
given names **and surnames** and to expose rankings by sex, period of birth,
initial letter, and locality (Brazil / Federation Unit / Municipality) drawn
from the 2022 Census full-population name register.

- Announcement (PT):
  <https://www.ibge.gov.br/novo-portal-destaques/44658-no-dia-4-11-2025-o-ibge-lanca-o-censo-demografico-2022-nomes-no-brasil-2.html>
- Announcement (EN):
  <https://www.ibge.gov.br/en/highlights/44662-on-november-4-2025-ibge-will-release-2022-population-census-names-in-brazil.html>
- News release (PT):
  <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/44929-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil>
- News release (EN):
  <https://agenciadenoticias.ibge.gov.br/en/agencia-news/2184-news-agency/news/44956-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil-2>
- Interactive site: <https://www.ibge.gov.br/apps/nomes/>
- Census landing page: <https://censo2022.ibge.gov.br/>

Headline statistics quoted in this repository:

| Statistic | Value | Scope |
|---|---:|---|
| `Silva` presence in full population | 16.76% | Brazil |
| `Santos` presence | 43.38% | Sergipe |
| `Silva` presence | 35.75% | Alagoas |
| `Silva` presence | 34.23% | Pernambuco |
| Distinct surnames surveyed | > 200,000 | Brazil |

See `docs/sources/ibge-nomes-no-brasil-2022.md` for the full extraction.

### 2. IBGE Nomes API (v2, based on 2010 Census)

Decade-of-birth frequencies for given names with `sexo=M|F` and
`localidade=BR|<codigo_IBGE>` filters. Still the authoritative machine-readable
endpoint until the 2022-based tables replace it.

- API reference: <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2>
- Ranking endpoint:
  `https://servicodados.ibge.gov.br/api/v2/censos/nomes/ranking?sexo=F&localidade=35`
- Name endpoint:
  `https://servicodados.ibge.gov.br/api/v2/censos/nomes/{nome}?sexo=M&localidade=33`

### 3. Nomes no Brasil — 2010 Census release (IBGE, 2016)

Legacy name-frequency publication used as the primary benchmark prior to the
2022 release. Organises frequencies "up to 1929" and by decade from 1930
onward. Basis for the nine `ateXXXX` buckets still used in
`ptbr_sampler/data/names_data.json`.

- IBGE news release (PT):
  <https://agenciadenoticias.ibge.gov.br/agencia-sala-de-imprensa/2013-agencia-de-noticias/releases/9747-ibge-revela-a-origem-dos-nomes-mais-comuns-dos-brasileiros>

### 4. Estimativas da População — 1 July 2024 (IBGE)

Official resident-population estimates for Brazil, Federation Units, and
municipalities as of 1 July 2024. Used to derive the population-weighted
location draws in `ptbr_sampler/data/locations_data.json`.

- News release (PT):
  <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/41111-populacao-estimada-do-pais-chega-a-212-6-milhoes-de-habitantes-em-2024>
- DOU PDF (canonical per-municipality table):
  <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf>
- Landing page:
  <https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html>

Key reference values used in the location sampler:

| State | Population 2024 | Share |
|---|---:|---:|
| São Paulo | 45,973,194 | 21.6% |
| Minas Gerais | 21,322,691 | 10.0% |
| Rio de Janeiro | 17,219,679 | 8.1% |
| Roraima | 716,793 | 0.3% |
| Amapá | 802,837 | 0.4% |
| Acre | 880,631 | 0.4% |

See `docs/sources/ibge-estimativas-populacao-2024.md` for the full extraction.

## Arpen-Brasil — Civil Registry

### 5. Arpen-Brasil — 2024 Annual Ranking

Nationwide civil-registry ranking of the most-registered newborn names in
Brazil during 2024, published by the *Associação Nacional dos Registradores de
Pessoas Naturais*. Complements IBGE's whole-population view with a
newborn-cohort benchmark.

- Press release:
  <https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/>

See `docs/sources/arpen-2024-rankings.md` for the full extraction.

## Ecosystem tools

### 6. `censobr` (IPEA)

R/Python package distributing microdata from the 2022 Brazilian Census via
Parquet/Arrow. Useful as a ground-truth cross-check when rebuilding
`state × decade × sex` name tables.

- <https://ipeagit.github.io/censobr/>

### 7. `geobr` (IPEA)

Official spatial datasets for Brazil, used for plotting sampled addresses
against IBGE boundaries during validation.

- <https://ipeagit.github.io/geobr/>

## Repository's own deep-research audit

`deep-research-report(4).md` (committed at the repo root) is the statistical
audit that produced this bibliography. It lists every assumption in the
sampler, rates it against the sources above, and prescribes the architectural
changes now implemented under `ptbr_sampler/sampling/`.

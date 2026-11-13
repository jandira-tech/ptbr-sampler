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
- Interactive site: <https://www.ibge.gov.br/apps/nomes/> / <https://censo2022.ibge.gov.br/nomes/>
- Technical Note Liv102228 (confidentiality thresholds `< 20` national/decade, `< 15` UF, `< 10` municipality):
  <https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf>
- Pinned public Parquet compilation (`olob0/ibge-nomes-no-brasil-2022`, commit `05efb85c92af43da2ed4ed088d1e0c9f17160e65`):
  <https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022>
- Pre-ingested runtime dataset mirror for `ptbr-sampler` `0.3.0`:
  <https://huggingface.co/datasets/arthrod/ptbr-sampler-data>
- Census landing page: <https://censo2022.ibge.gov.br/>

Headline statistics quoted in this repository:

| Statistic | Value | Scope |
|---|---:|---|
| Resident population (`state.parquet`) | 203,080,756 | Brazil (1 Aug 2022) |
| `Silva` person-level presence (`q_Silva = 10.20%` token-slot share) | 16.76% | Brazil |
| `Santos` person-level presence (`q_Santos = 6.41%` token-slot share) | 43.38% | Sergipe |
| `Silva` person-level presence | 35.75% | Alagoas |
| `Silva` person-level presence | 34.23% | Pernambuco |
| Distinct given names (`>= 20` nationally) | 128,458 | Brazil (`99.8207%` sex-observed mass) |
| Distinct surnames (`>= 20` nationally) | 201,601 | Brazil |

See `docs/sources/ibge-nomes-no-brasil-2022.md` and `docs/sources/ibge-nomes-2022-availability.md` for the full extraction, censoring decomposition, and SHA-256 manifest.

### 2. IBGE Nomes API (v2, based on 2010 Census — Historical `census_year=2010` Only)

Decade-of-birth frequencies for given names with `sexo=M|F` and
`localidade=BR|<codigo_IBGE>` filters. Retained in `ptbr-sampler` `0.3.0`
strictly for opt-in historical reproduction (`census_year=2010` /
`--census-year 2010`); superseded as the default by the 2022 Census tables
above.

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

### 8. `genero-nomes` (Brasil.IO / Álvaro Justen / @turicas — Historical `census_year=2010` Only)

Per-name male/female frequency table built from the public IBGE 2010 Nomes API
(per-name endpoint walked across the full long tail), licensed under
`CC-BY-SA-4.0`. Powers the legacy `census_year=2010` `period × sex` first-name
partitions (`parquet/first_names/period=<P>/sex=<S>/`); **not used** in the
default `census_year=2022` pipeline (`99.8207%` directly observed IBGE 2022
empirical sex mass).

- Dataset files: <https://brasil.io/dataset/genero-nomes/files/>
- Direct download: <https://data.brasil.io/dataset/genero-nomes/nomes.csv.gz>
- Methodology + scraper: <https://github.com/turicas/genero-nomes>
- Brasil.IO methodology blog post:
  <https://blog.brasil.io/2019/05/31/classificando-nomes-por-genero-usando-dados-publicos/index.html>
- Local source page: `docs/sources/genero-nomes.md`

### 9. Gemini gender classifications (`gemini-3.1-flash-lite-preview` — Historical `census_year=2010` Only)

Gap-fill source for the ~8.1 % of `(name, period)` cells in legacy 2010
`names_data.json` absent from `genero-nomes` (mostly civil-registry typos and
spelling variants). LLM-derived, **not** empirical IBGE data, and **never used
in `census_year=2022`** (`0.0%` LLM mass in 2022). Every legacy 2010 Parquet
row this source contributes is tagged with `source =
'gemini-3.1-flash-lite-preview'` and `count_* = 0` so reviewers can audit and
filter back to the empirical-only subset.

- Model docs: <https://ai.google.dev/gemini-api/docs/models>
- API key: <https://aistudio.google.com/apikey>
- Local methodology + audit-trail spec: `docs/sources/gemini-gender-classifications.md`

## Algorithmic, Numerical, & Statistical Methodology References

### 10. Discrete Alias Sampling, Compensated Floating-Point Arithmetic, & Multiple-Testing GoF

- **Walker, A. J. (1977).** "An Efficient Method for Generating Discrete Random Variables with General Distributions." *ACM Transactions on Mathematical Software (TOMS)*, 3(3), 253–256. <https://doi.org/10.1145/355744.355749>
- **Vose, M. D. (1991).** "A Linear Algorithm for Generating Random Numbers with a Given Distribution." *IEEE Transactions on Software Engineering*, 17(9), 972–975. <https://doi.org/10.1109/32.92917>
- **Kahan, W. (1965).** "Pracniques: Further Remarks on Reducing Truncation Errors." *Communications of the ACM*, 8(1), 40. <https://doi.org/10.1145/363707.363723>
- **Shewchuk, J. R. (1997).** "Adaptive Precision Floating-Point Arithmetic and Fast Robust Geometric Predicates." *Discrete & Computational Geometry*, 18(3), 305–363. <https://doi.org/10.1007/PL00009321> (exact floating-point summation underlying Python's `math.fsum`).
- **Pearson, K. (1900).** "On the Criterion that a Given System of Deviations from the Probable in the Case of a Correlated System of Variables is Such that it Can be Reasonably Supposed to have Arisen from Random Sampling." *Philosophical Magazine*, Series 5, 50(302), 157–175. <https://doi.org/10.1080/14786440009463897>
- **Cochran, W. G. (1952).** "The $\chi^2$ Test of Goodness of Fit." *The Annals of Mathematical Statistics*, 23(3), 315–345. <https://doi.org/10.1214/aoms/1177729380> ($E_j \ge 5$ expected-count criterion for tail-pooled multinomial bins).
- **Holm, S. (1979).** "A Simple Sequentially Rejective Multiple Test Procedure." *Scandinavian Journal of Statistics*, 6(2), 65–70. <https://www.jstor.org/stable/4615733>

## Repository's own deep-research audit & technical report

- [`docs/technical-report.md`](../technical-report.md): comprehensive monograph covering project evolution (`0.1.0` → `0.2.0` → `0.3.0`), mathematical derivations, IBGE `Liv102228` censoring decomposition, Kahan-compensated Walker–Vose alias tables, Faker/RNG stream isolation, Hugging Face runtime caching, and four-layer statistical validation.
- `deep-research-report(4).md` (committed at the repo root): initial statistical audit from the `0.2.x` cycle that flagged legacy sampling assumptions and motivated the `0.3.0` modernization.

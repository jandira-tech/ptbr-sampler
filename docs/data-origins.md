# Data origins

This document tracks — **per data type** — where each bundled dataset came
from, what it represents, and which file inside the installed package carries
it. It complements `docs/sources/bibliography.md` (which catalogues the
*external* references) with an inventory of the *local* files and the
provenance of each one.

The same information is exposed at runtime through the `ptbr sources`
command (see `ptbr_sampler/cli.py`).

---

## 1. First names

- **File(s):**
  - `ptbr_sampler/data/names_data.json` (legacy JSON, still loaded by default).
  - `ptbr_sampler/data/parquet/first_names/period=<period>/part.parquet` (Parquet
    layout materialised by `python -m scripts.ingest_to_parquet`).
- **Origin:** IBGE *Nomes no Brasil*, 2010 Census release (2016), exposed
  through the public Names API (`/api/v2/censos/nomes`). Frequencies are
  published "up to 1929" and then by decade from 1930 onward.
- **Dimensions bundled today:** `period` ∈ {`ate1930`, `ate1940`, `ate1950`,
  `ate1960`, `ate1970`, `ate1980`, `ate1990`, `ate2000`, `ate2010`}.
- **Missing dimensions (planned):** `uf` and `sex`. The 2022 Census release
  (2025) adds both — the Parquet layout already carries those partition keys
  ready to receive the drop-in.
- **Primary source URL:** <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2>
- **Release behind the 2022 upgrade:** <https://www.ibge.gov.br/apps/nomes/>
- **See also:** `docs/sources/ibge-nomes-no-brasil-2022.md`.

## 2. Surnames

- **File(s):**
  - `ptbr_sampler/data/surnames_data.json` (national pooled distribution;
    ~86k entries including a `top_40` convenience subset).
  - `ptbr_sampler/data/parquet/surnames/scope=national/part.parquet`.
- **Origin:** derived from the 2010-era IBGE name records plus civil-registry
  frequencies; the national distribution is consistent with what IBGE now
  publishes for the 2022 Census (`Silva` 16.76%, `Santos` ~11%).
- **Dimensions bundled today:** `scope=national`.
- **Missing dimensions (planned):** `uf` and `period`. These are the
  partitions where IBGE 2022 data shows the largest regional variation
  (`Santos` 43.38% in Sergipe, `Silva` 35.75% in Alagoas, `Silva` 34.23% in
  Pernambuco) — the feature that the `deep-research-report(4).md` audit
  flagged as the single biggest realism gap.
- **Primary source URL:** <https://www.ibge.gov.br/apps/nomes/>
- **See also:** `docs/sources/ibge-nomes-no-brasil-2022.md`.

## 3. Middle names (second given names)

- **File(s):**
  - `ptbr_sampler/data/middle_names.json` (raw extraction with contamination).
  - `ptbr_sampler/data/parquet/middle_names/part.parquet` (cleaned against
    the given-name whitelist).
- **Origin:** civil-registry extraction cleaned through a pipeline that
  IBGE's *Nomes no Brasil* does not directly sanction — IBGE's dissemination
  variable is "first name only". The Arpen-Brasil 2024 ranking is the
  closest public benchmark but measures newborn flow, not population stock.
- **Dimensions bundled today:** none — a single national Bernoulli "has
  second name?" rate (~31%) plus a multinomial over ~1,200 second tokens.
- **Data quality note:** the raw JSON mixes second given names with
  surnames (`Araújo`, `Borges`, `Bezerra`, …), the administrative token
  `Cancelado`, and a bare hyphen. Ingestion filters these through
  `ptbr_sampler/sampling/vocabulary.py` (given-name whitelist + canonical
  surname blocklist). 302 of 1,187 tokens (26%) are dropped during
  ingestion.
- **Benchmark:** <https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/>
- **See also:** `docs/sources/arpen-2024-rankings.md`.

## 4. States (Federation Units)

- **File(s):**
  - `ptbr_sampler/data/locations_data.json` (state + city weights).
  - `ptbr_sampler/data/parquet/states/part.parquet`.
- **Origin:** IBGE *Estimativas da População*, 1 July 2024 reference date.
  State totals cover the 26 UFs plus the Federal District; shares are
  normalised against the 212.6 million Brazil-wide population figure.
- **Dimensions bundled today:** 27 rows (state name + UF abbreviation +
  population + share).
- **Primary source URL:** <https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html>
- **Canonical PDF:** <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf>
- **See also:** `docs/sources/ibge-estimativas-populacao-2024.md`.

## 5. Cities

- **File(s):** `ptbr_sampler/data/cities_with_ceps.json` (~28 MB; contains
  municipal name, UF, population share within the state, DDD, and the CEP
  range span per municipality).
- **Origin:**
  - Municipal **population** shares — IBGE *Estimativas da População 2024*
    (same release as the states table, propagated to municipal level).
  - **CEP ranges** — Correios / ViaCEP published prefix bands. Per-address
    resolution is optional and goes through `ptbr_sampler/utils/cep_wrapper.py`.
  - **DDD codes** — Anatel public regional allocation.
- **Dimensions bundled today:** `city_name`, `city_uf`,
  `population_percentage_state`, `cep_range_begins`, `cep_range_ends`,
  `ddd` (where known).
- **Benchmarks:**
  - IBGE estimates: <https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html>
  - Correios CEP: <https://buscacepinter.correios.com.br/>
  - ViaCEP API (runtime enrichment): <https://viacep.com.br/>

## 6. Surname-prefix probabilities (`da`, `de`, `dos`, `e`, `d'`, …)

- **File(s):** hard-coded in `ptbr_sampler/br_name_class.py` under
  `BrazilianNameSampler.SURNAME_PREFIXES`.
- **Origin:** convention + linguistic review of the Portuguese surname
  connectives (`dos Santos`, `da Silva`, `do Nascimento`, `de Souza`, …).
  These weights are *authorial* — they encode a style prior rather than an
  empirical measurement, and should be read as tunable.
- **Data quality note:** `_apply_prefix` intentionally keeps these draws
  on Python's stdlib `random` so tests that seed `random.seed(...)` remain
  deterministic. Swapping to an empirical table would be a behaviour
  change.

## 7. Document generators (CPF, RG, PIS, CNPJ, CEI)

- **File(s):** algorithmic — see `ptbr_sampler/document_sampler.py`,
  `ptbr_sampler/br_rg_class.py`, and `ptbr_sampler/utils/{cpf,pis,cnpj,cei}.py`.
- **Origin:** public document-validation specifications (Receita Federal for
  CPF/CNPJ, Dataprev for PIS, INSS for CEI, SSP state secretariats for RG).
  Only the check-digit rules are implemented; the output digits are
  **synthetic** — no real identity is referenced.
- **RG state specifics:** issuer format varies by state. Per-state rules
  live in `ptbr_sampler/br_rg_class.py`. Format references are drawn from
  the official SSP ID-card samples published by each state secretariat.
- **Safety note:** generators are for realistic-looking fake data only. The
  digits are not valid against a real person's identity.

## 8. Addresses (street, neighbourhood, building number)

- **File(s):** `ptbr_sampler/utils/address_for_offline.py` — string corpora
  for street prefixes, neighbourhoods, and formatting rules.
- **Origin:** provider corpora consolidated from open Brazilian Faker-style
  datasets plus editorial curation. Used as a fallback when
  `--make-api-call` is not set or when the ViaCEP API cannot resolve a
  given CEP.
- **When the API is active:** address fields are reconciled against the
  ViaCEP response (<https://viacep.com.br>) and only fall back to the
  offline corpus when a field is missing.

## 9. Phone numbers

- **File(s):** `ptbr_sampler/utils/phone.py`.
- **Origin:** Anatel DDD allocation. The DDD is looked up from the sampled
  city; the subscriber digits are synthetic (Brazilian-mobile prefix 9 +
  eight synthetic digits).
- **Primary reference:** <https://www.anatel.gov.br/consumidor/tudo-sobre-telefonia-fixa/codigos-de-area>

---

Run `ptbr sources` to see the same inventory in the terminal, with live
existence checks against the installed package.

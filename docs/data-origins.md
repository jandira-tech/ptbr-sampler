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
- **Missing dimensions (planned, blocked on data ingest):** `uf` and `sex`.
  The 2022 Census release (2025) adds both — the Parquet layout already
  carries those partition keys ready to receive the drop-in. Until those
  raw exports land under `ptbr_sampler/data/raw/ibge_nomes_2022/`, the
  sampler does **not** claim UF- or sex-conditioned first-name realism.
  This is a data-availability limitation, not a code limitation.
- **Time-horizon caveat:** the latest bucket is `UNTIL_2010` (`ate2010`).
  Recent cohorts (people born 2011–2024) are *not* faithfully represented
  by this distribution. Whole-population realism here matches IBGE's stock
  data; for newborn-flow realism cross-check against the Arpen 2024
  ranking documented in `docs/sources/arpen-2024-rankings.md`. Extending
  to 2022-Census-conditioned buckets requires the IBGE 2022 export.
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
- **Missing dimensions (planned, blocked on data ingest):** `uf` and
  `period`. These are the partitions where IBGE 2022 data shows the
  largest regional variation (`Santos` 43.38% in Sergipe, `Silva` 35.75% in
  Alagoas, `Silva` 34.23% in Pernambuco) — the feature that the
  `deep-research-report(4).md` audit flagged as the single biggest realism
  gap. Until the IBGE 2022 surname export is ingested, surname realism is
  pooled-national.
- **About `top_40`:** the JSON payload also exposes a curated 40-row
  subset under the `top_40` key, used when callers pass `top_40=True`.
  This is a **historical-data convenience mode**: at the time the legacy
  extract was built, only the top 40 surnames were reliably published, so
  the subset was preserved for callers that explicitly want the
  fast-and-narrow path. It is **not** more realistic than the full
  ~86k-entry table — the full table tracks the empirical distribution
  more faithfully. `top_40` is kept for now, but should be re-evaluated
  once IBGE 2022 surname data is ingested (see `todo.md` task 7).
- **Two-surname realism note:** the most common Brazilian-civil-naming
  convention is **at least two surnames** (one from each parental line).
  The default sampler returns two surnames; `with_only_one_surname=True`
  is a compatibility / convenience override and should not be read as
  the realistic default. See README "Known realism gaps".
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
  second name?" rate plus a multinomial over ~1,200 second tokens.
- **`percentage_with_second = 30.99%` provenance:** computed directly from
  the raw extract — the JSON payload reports
  `total_people = 5,293,204`, `total_with_second_names = 1,640,514`, and
  `1,640,514 / 5,293,204 = 30.99%`. So the rate **is** grounded in the
  extract, but the extract itself is the authorial pipeline (not IBGE),
  so the figure should be read as "empirical for this corpus" rather
  than as a population-level statistic. If a stronger empirical source
  becomes available, this default should be revisited (see `todo.md`
  task 10). Read it as a transparent estimate, not as an IBGE-published
  fact.
- **Cleaning pipeline:** the raw JSON mixes second given names with
  surnames (`Araújo`, `Borges`, `Bezerra`, …), the administrative token
  `Cancelado`, and a bare hyphen. Ingestion filters these through
  `ptbr_sampler/sampling/vocabulary.py` (given-name whitelist + canonical
  surname blocklist). 302 of 1,187 tokens (26%) are dropped during
  ingestion. The cleaning logic is reproducible:

  1. Build a given-name whitelist from `names_data.json` (every name that
     appears in any IBGE-derived first-name period).
  2. Build a canonical-surname blocklist from `surnames_data.json`.
  3. Run `python -m scripts.ingest_to_parquet` — middle-name rows
     surviving the whitelist + blocklist filter are written to
     `ptbr_sampler/data/parquet/middle_names/part.parquet`.
  4. Pass `--skip-middle-names-filter` to `ingest_to_parquet` to bypass
     the cleanup and inspect the raw distribution.
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

## Download-and-rebuild walkthrough

This is the single explicit first-step workflow (`todo.md` task 1 + 11):
how to start from zero and produce the Parquet layout the sampler reads.

```bash
# 1. Inventory: which datasets are present locally and what powers them?
python -m scripts.download_datasets

# 2. (If anything is missing) fetch it from the source URL printed above
#    and drop it under the indicated raw_local_path. The script does NOT
#    silently scrape IBGE/Arpen — terms-of-use and rate limits make
#    interactive download the right default.

# 3. Rebuild the partitioned Parquet layout from the JSON sources:
python -m scripts.ingest_to_parquet

# 4. Re-run the smoke and statistical tests:
uv run --extra test pytest -q
```

| Dataset | Source URL | Raw local path | Powers | Status |
|---|---|---|---|---|
| IBGE Nomes API v2 (first names by period) | <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2> | `ptbr_sampler/data/names_data.json` | `parquet/first_names/period=<x>/` | bundled |
| IBGE Nomes no Brasil 2022 (first names + surnames by UF, sex) | <https://www.ibge.gov.br/apps/nomes/> | `ptbr_sampler/data/raw/ibge_nomes_2022/` | future `surnames/uf=<UF>/` and `first_names/uf=<UF>/sex=<>/` | **not bundled** |
| IBGE Estimativas da População 2024 | <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf> | `ptbr_sampler/data/locations_data.json` | `parquet/states/` | bundled |
| Arpen-Brasil 2024 newborn ranking | <https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/> | `ptbr_sampler/data/raw/arpen_2024/` | benchmark only | **not bundled** |
| Surnames national | <https://www.ibge.gov.br/apps/nomes/> | `ptbr_sampler/data/surnames_data.json` | `parquet/surnames/scope=national/` | bundled |
| Middle names raw extract | authorial pipeline | `ptbr_sampler/data/middle_names.json` | `parquet/middle_names/` | bundled |
| Cities + CEP ranges + DDD | <https://buscacepinter.correios.com.br/> | `ptbr_sampler/data/cities_with_ceps.json` | states+city draws | bundled |

The `[MISS]` rows in `python -m scripts.download_datasets` are
informational, not a failure: the sampler runs end-to-end with the
bundled datasets only. Adding the missing rows is what unlocks
UF-conditioned realism (see "Known realism gaps" in the README).

---

Run `ptbr sources` to see the same inventory in the terminal, with live
existence checks against the installed package.

# Data origins (`ptbr-sampler` `0.3.0`)

This document tracks — **per data type and census vintage** — where each dataset came from, what estimand it represents, and how `ptbr-sampler` `0.3.0` resolves it at runtime. It complements [`docs/sources/bibliography.md`](sources/bibliography.md) and [`THIRD_PARTY_NOTICES.md`](https://github.com/jandira-tech/ptbr-sampler/blob/main/THIRD_PARTY_NOTICES.md), and powers the `ptbr sources` and `ptbr datasets` CLI commands.

---

## Runtime Delivery Model (`< 150 KiB` Wheel + Hugging Face Hub)

Starting in **`0.3.0`**, heavy Parquet and JSON payloads are **excluded from the Python wheel** so `pip install ptbr-sampler` / `uv add ptbr-sampler` downloads under `150 KiB` (bundling only `ptbr_sampler/data/dataset_manifest.json`). At runtime, `ptbr_sampler/datasets.py` resolves any required artifact in strict order:

1. `PTBR_SAMPLER_DATA_DIR/<relpath>` (air-gapped / pre-baked container directory),
2. Local git checkout `ptbr_sampler/data/<relpath>` when present (zero network I/O during local development and repository test runs),
3. Revision-addressed local cache `~/.cache/ptbr-sampler/<hf_revision>/<relpath>` (customizable via `PTBR_SAMPLER_CACHE_DIR` or `$XDG_CACHE_HOME`),
4. Lazy HTTPS download from [`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data) at the immutable 40-character commit SHA pinned in `dataset_manifest.json`, verified against per-file SHA-256 digests under an `fcntl.flock` cross-process lock before atomic `os.replace`.

Set `PTBR_SAMPLER_OFFLINE=1` to forbid network egress (raising a deterministic `RuntimeError` if a partition is uncached), and pre-warm Docker images or CI runners with:

```bash
ptbr datasets prefetch --census-year 2022   # or --all-vintages
ptbr datasets status --verify
```

---

## 1. First names — Default `census_year=2022` vs. Historical `census_year=2010`

### 1A. Primary default (`census_year=2022`, `TimePeriod.ALL`)

- **Runtime partitions (`parquet/census_year=2022/`):**
  - `first_names/scope=national/part.parquet` (`128,458` rows; total occurrences `190,383,184` = `93.7475%` of Brazil's `203,080,756` residents)
  - `first_names/sex=M/part.parquet` (`60,954` rows; `92,287,140` occurrences) and `first_names/sex=F/part.parquet` (`73,361` rows; `97,754,764` occurrences)
  - `first_names/period=<period>/part.parquet` (`10` survivor birth cohorts from `ate1940` through `ate2020` and `2020_2022`; `221,524` rows total)
  - `first_names/uf=<UF>/part.parquet` (`27` Federation Units; `379,474` rows total; UF disclosure threshold `>= 15`)
  - `sex_prior/scope=national/part.parquet` (`128,458` rows with nullable `count_male`/`count_female`, `residual_unassigned`, `censoring_regime`, and exact empirical rates $\hat{p}_{\text{obs}}(i) = N_{i,\text{obs}} / N_i$)
- **Origin:** IBGE *Censo Demográfico 2022 — Nomes no Brasil* (reference date 1 August 2022; [Technical Note Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf)), ingested from Gabriel Lobo's public compilation [`olob0/ibge-nomes-no-brasil-2022`](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022) pinned at `05efb85c92af43da2ed4ed088d1e0c9f17160e65`.
- **Disclosure thresholds (Liv102228):** IBGE suppresses cells `< 20` nationally and national-by-decade, `< 15` per UF, and `< 10` per municipality.
- **Five sex-coverage metrics (`census_year=2022`):**
  1. *Vocabulary lookup coverage:* `123,733 / 128,458` (`96.32%`) given-name types have at least one non-null sex count.
  2. *Directly observed empirical mass:* **`99.8207%`** (`190,041,904 / 190,383,184`).
  3. *Deduced exact-zero mass:* **`55,210`** single-null names satisfy $N - N_{\text{obs}} = 0$ (`one_null_exact_zero`).
  4. *LLM-assigned uncalibrated mass:* **`0.0%`** (neither `genero-nomes` nor Gemini is used in `2022`).
  5. *Suppressed / excluded mass:* **`341,280`** occurrences (**`0.1793%`** = `232,758` `one_null_suppressed_positive` + `108,522` `both_null_suppressed`).
- **Conditioning modes:**
  - `conditioning_mode='strict'` (default): serves only observed 1D marginals (`national`, `national × sex`, `national × cohort`, `UF`). Joint combinations (`UF × sex`, `cohort × sex`, `UF × cohort`) raise `ValueError` rather than silently dropping dimensions.
  - `conditioning_mode='estimated'` (explicit opt-in): builds `UF × sex` (`time_period=ALL`) and `cohort × sex` (`uf=None`) lazily in memory via Bayes' rule using the 2022 national sex prior. `UF × cohort` remains rejected in all modes.
- **Cohort boundary alignment:** Legacy 2010 keys use upper endpoints (`ate2010` = `2000–2009`), whereas `olob0` `name_by_decade` uses decade starts (`decade=2000` = `2000–2009`, `decade=2010` = `2010–2019` → `TimePeriod.UNTIL_2020`, `decade=2020` → `TimePeriod.PERIOD_2020_2022`, and `decade=1930` = `<= 1939` → `TimePeriod.UNTIL_1940`).

### 1B. Historical opt-in (`census_year=2010`, `TimePeriod.UNTIL_2010`)

- **Runtime artifacts:** `names_data.json` + `parquet/first_names/period=ate*/part.parquet`, plus optional `parquet/sex_prior/scope=national/part.parquet` and `parquet/first_names/period=ate*/sex=*/part.parquet`.
- **Origin:** IBGE 2010 Census Nomes API v2 (`ate1930`..`ate2010`), paired with [`brasil.io/genero-nomes`](sources/genero-nomes.md) (`91.9%` `(name, period)` cell match) and [Gemini `gemini-3.1-flash-lite-preview`](sources/gemini-gender-classifications.md) (`8.1%` cell gap-fill tagged with `source='gemini-3.1-flash-lite-preview'` and `count_* = 0`).

---

## 2. Surnames

- **Primary `census_year=2022` partitions:**
  - `parquet/census_year=2022/surnames/scope=national/part.parquet` (`201,601` surnames, `333,496,261` total surname tokens; $q_{\text{Silva}} = 10.2040\%$ token-slot share vs. `16.76%` person-level presence).
  - `parquet/census_year=2022/surnames/uf=<UF>/part.parquet` (`27` UFs, `449,093` rows total, threshold `>= 15`), used automatically whenever UF conditioning is active in `census_year=2022` (capturing regional concentrations such as `Santos` in Sergipe and `Silva` in Alagoas/Pernambuco).
- **Two-surname slot assembly:** In `census_year=2022` with `with_only_one_surname=False` (default), slot 2 is resampled conditional on $s_2 \neq s_1$ so identical stems (`"Maria da Silva Silva"`) are never emitted. When `top_40=True` in `census_year=2022`, `AliasTable.top_k(40)` slices the active 2022 national or UF surname table directly.
- **Historical `census_year=2010` artifacts:** `surnames_data.json` and `parquet/surnames/scope=national/part.parquet` (~86k pooled national entries plus legacy `top_40`).

---

## 3. Middle names (second given names)

- **Artifacts:** `middle_names.json` and `parquet/middle_names/part.parquet` (cleaned through `ptbr_sampler/sampling/vocabulary.py`, dropping surname leakage, `'Cancelado'`, and `'-'`).
- **Provenance & caveat:** IBGE *Nomes no Brasil* (both 2010 and 2022) disseminates **only the first recorded given name**. Both `middle_names.json` and `percentage_with_second = 30.99%` (`1,640,514 / 5,293,204`) come from an authorial civil-registry corpus rather than IBGE census stock.

---

## 4. States & Cities (Geography Vintage Boundary)

- **States (`2024` geography vs. `2022` Census denominators):**
  - `locations_data.json` and `parquet/states/part.parquet`: IBGE *Estimativas da População* (1 July 2024, `212.6M` inhabitants) used by `BrazilianLocationSampler`.
  - `parquet/census_year=2022/states/part.parquet`: exact 2022 Census UF resident denominators (`203,080,756` total) from `state.parquet` for demographic cross-table auditing.
- **Cities, CEP spans, and DDDs:** `cities_with_ceps.json` combines IBGE 2024 municipal population shares, Correios / ViaCEP postal-code prefix spans, and Anatel DDD area codes. Because geography reflects 2024 municipal estimates while default names reflect 2022 Census stock, `ptbr-sampler` documents this mixed reference date explicitly.

---

## 5. Surname connectives, synthetic documents, offline addresses, phones, & `Faker`

- **Surname connectives (`da`, `de`, `dos`, `e`, …):** authorial style priors in `BrazilianNameSampler.SURNAME_PREFIXES` (`ptbr_sampler/br_name_class.py`).
- **Documents (CPF, RG, PIS, CNPJ, CEI):** check-digit algorithms in `ptbr_sampler/document_sampler.py`, `ptbr_sampler/br_rg_class.py`, and `ptbr_sampler/utils/` (modulo-11 variants for CPF, CNPJ, and PIS; base-10 digit-sum folding for CEI; 27 state-specific formatting masks and issuing authorities such as `SSP-SP` and `DETRAN-RJ` for RG); purely synthetic, never referencing real individuals.
- **Offline addresses & phones:** `ptbr_sampler/utils/address_for_offline.py` and `ptbr_sampler/utils/phone.py` (Anatel DDD + synthetic 9-digit mobile subscriber numbers).
- **`Faker` provider & `rng=` determinism:** `ptbr_sampler.faker` (`PTBRProvider`, `install_ptbr`) and `rng=random.Random(...)` consume the exact same runtime Parquet and JSON artifacts above without duplicating data or mutating global RNG state.
- **License boundary:** Repository software is MIT-licensed (`LICENSE`, `Copyright (c) 2026 Jandira Tech`); public statistical and third-party dataset terms remain governed by their respective notices in [`THIRD_PARTY_NOTICES.md`](https://github.com/jandira-tech/ptbr-sampler/blob/main/THIRD_PARTY_NOTICES.md).

---

## Maintainer Download, Ingest, Audit, & Publish Workflow

```bash
# 1. Fetch and SHA-256-verify the pinned Census 2022 Parquet snapshot (8.23 MiB; skips valid cached files unless --overwrite is passed)
python -m scripts.download_datasets --fetch-ibge-2022

# 2. (Optional, legacy 2010 sex prior) Fetch brasil.io/genero-nomes
python -m scripts.download_datasets --fetch-genero-nomes

# 3. Materialize float64 Parquet partitions for both census_year=2022 and legacy 2010
python -m scripts.ingest_to_parquet

# 4. Run deterministic raw + cross-table statistical audit
python -m scripts.audit_datasets \
  --raw-dir ptbr_sampler/data/raw/ibge_nomes_2022 \
  --parquet-dir ptbr_sampler/data/parquet/census_year=2022

# 5. Refresh local dataset_manifest.json (or --publish to arthrod/ptbr-sampler-data)
python -m scripts.publish_hf_dataset --manifest-only
```

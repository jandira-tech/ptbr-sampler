# `ptbr-sampler` `0.3.0`: Census 2022 Default, Hugging Face Runtime Datasets, and Statistical Methodology Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Incorporating Gabriel Lobo's Census 2022 compilation (`olob0/ibge-nomes-no-brasil-2022`), bumping the package to `0.3.0` with Census 2022 as the primary default, and deploying runtime datasets to Hugging Face so the Python wheel carries zero dataset bloat are accepted requirements; statistical validation governs capability promotion, censoring accounting, and ingestion correctness.

**Goal:** Release `ptbr-sampler` `0.3.0` with IBGE Census 2022 (`census_year=2022`, `TimePeriod.ALL`) as the primary default, deploy all runtime Parquet and geography datasets to a pinned Hugging Face Dataset repository (`arthrod/ptbr-sampler-data`) fetched lazily and SHA-256-verified at runtime (`< 150 KiB` pure-Python wheel), preserve explicit `census_year=2010` historical opt-in, and enforce four-layer statistical validation.

**Architecture:** Retain the `PyArrow` + `AliasTable` + `PartitionStore` sampling engine, extending it with: (1) versioned partition layouts (`parquet/census_year=2022/` as primary default and `parquet/` for `census_year=2010` opt-in), (2) a pure-stdlib runtime dataset resolver (`ptbr_sampler/datasets.py`) backed by a tiny packaged `ptbr_sampler/data/dataset_manifest.json` (~`16 KiB`, pinned to an immutable 40-character Hugging Face commit SHA and per-file SHA-256 digests) that downloads partitions on first touch into a cross-process-locked user cache (`~/.cache/ptbr-sampler/<hf_revision>/`) while keeping local git checkouts zero-network, and (3) a strict separation between **observed marginals** (`conditioning_mode='strict'`), **lazy in-memory Bayes conditional estimates** (`conditioning_mode='estimated'`), and **authorial naming conventions**.

**Tech Stack:** Python `>=3.12`, standard library (`urllib`, `hashlib`, `math`, `fcntl`), `numpy>=2.0`, `pyarrow>=17.0`, `typer>=0.15.0`, `rich>=14.0.0`, `pytest>=8.3`, `scipy>=1.14` (test-only extra), and `huggingface-hub>=0.26` (dev-only extra used exclusively by `scripts/publish_hf_dataset.py`; zero new runtime dependencies).

---

## Accepted `0.3.0` Scope & Empirical Ground Truth

`ptbr-sampler` bumps from `0.2.0` to **`0.3.0`**, switching the default vintage across Python (`sample()`, `BrazilianNameSampler.from_parquet()`, `BrazilianNameSampler.from_bundled_parquet()`) and CLI (`ptbr generate`) to [Gabriel Lobo's Census 2022 compilation (`olob0/ibge-nomes-no-brasil-2022`)](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022) at pinned revision `05efb85c92af43da2ed4ed088d1e0c9f17160e65`, while retaining `census_year=2010` (`--census-year 2010`) as an explicit historical opt-in and deploying the built runtime dataset tree to Hugging Face (`arthrod/ptbr-sampler-data`) so the wheel excludes all heavy data files.

Direct inspection of the pinned upstream Census 2022 revision establishes five reproducible Parquet tables (`8,630,643` bytes = `8.23 MiB` total):

| Upstream file | Bytes | Rows | SHA-256 | Schema & observed statistical grain |
| --- | ---: | ---: | --- | --- |
| `name_ranking.parquet` | `1,738,567` | `330,059` | `635691d3ce52eb59c242ecb886dbaab62b4b42e6bed4b4f1766f8c6725636c64` | `(name_text: str, name_type: str, frequency: int32, percentage: float64, rank: int32)` — `128,458` `given` ($\sum = 190,383,184$), `201,601` `surname` ($\sum = 333,496,261$) |
| `name_detail.parquet` | `2,250,879` | `330,058` | `91518f2d0d1da8e438ab9f557127da06633e186914aecb717f1bbf7bfb6b2943` | `(name_text: str, name_type: str, letter_rank: int32, male_count: int32?, female_count: int32?, median_age: float64?)` — missing `('perl', 'surname')` due to IBGE WAF rule |
| `name_by_decade.parquet` | `910,784` | `221,524` | `9f852814bf42a47358841c054a70939c763c4fc70c7e38564ad44fb94b7fbdef` | `(name_text: str, name_type: str, decade: int16, frequency: int32)` — marginal 2022 survivor counts for `given` across `decade` $\in \{1930, 1940, \dots, 2020\}$ ($\sum = 186,340,745$) |
| `name_by_state.parquet` | `3,729,128` | `828,567` | `5588f012d43bb38b07691044010eb7e96cb2bfc359dd3b53a6c3b0ea46f1504e` | `(name_text: str, name_type: str, state_code: uint8, frequency: int32, percentage: float64)` — `379,474` `given`, `449,093` `surname`; `state_code` is integer IBGE UF code `11..53` |
| `state.parquet` | `1,285` | `27` | `5d4aa2a4faf4cdef421f2563de63cd8298b58113779774045a29b9e13ddebc55` | `(code: uint8, abbreviation: str, name: str, region_code: uint8, population: int32)` — exact 2022 Census UF resident denominators ($\sum = 203,080,756$) |

---

## Statistical Methodology & Estimand Specification

Every transformation, API contract, and test in this plan enforces six statistical rules grounded in the empirical structure of the pinned IBGE 2022 release ([IBGE Technical Note Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf)):

### 1. Target-Population & Estimand Taxonomy
Do not conflate distinct demographic estimands in code, provenance metadata, or validation benchmarks:
1. **2022 Census resident stock** ($N_{\text{pop}, 2022} = 203,080,756$, reference date 1 August 2022): target of `census_year=2022` with `TimePeriod.ALL`.
2. **2022 Census birth-cohort survivor marginals** (`name_by_decade.parquet`): counts of residents alive on 1 August 2022 partitioned by decade of birth. Early cohorts reflect differential longevity (e.g., female survival advantage), not historical birth-registry incidence at birth.
3. **2010 Census birth-cohort survivor marginals** (`names_data.json` / legacy `parquet/first_names/period=ate*`): historical compatibility vintage (`census_year=2010`).
4. **Civil-registry birth flows** (Arpen top-50 rankings): annual newborn registration flow, truncated at rank 50 and incompatible as a goodness-of-fit target for full-population stock.
5. **Geography population vintage**: bundled `locations_data.json` / `cities_with_ceps.json` use IBGE 2024 population estimates (`212.6M`), whereas `state.parquet` carries exact 2022 Census UF denominators (`203,080,756`). Document this mixed-vintage boundary rather than claiming unified 2022/2024 joint microdata.

### 2. Disclosure-Threshold Censoring & Exact Sex-Count Conservation
IBGE suppresses cells with count $< 20$ nationally (including national-by-decade), $< 15$ per UF, and $< 10$ per municipality:
- **National given-name coverage:** $\eta_{\text{nat}} = 190,383,184 / 203,080,756 = 0.937475$ (`93.75%`); the remaining `6.25%` (`12,697,572` residents) carry given names with national frequency $< 20$. Note that `name_ranking.percentage` is `100 * frequency / 203,080,756` (summing to `93.7475%`, **not** `100%`), so sampling weights must always be normalized from `frequency` over observed support.
- **Exact conservation law in `name_detail`:** Across all `10,582` given names where both `male_count` and `female_count` are non-null ($\ge 20$), $N - (N_M + N_F) = 0$ holds **identically for every row** ($\min = 0, \max = 0$). Across all `113,151` single-null rows, the residual $R = N - N_{\text{obs}}$ satisfies $0 \le R \le 19$ with zero exceptions:
  - `both_observed` (`10,582` names): both $N_M \ge 20$ and $N_F \ge 20$ observed; $p_M = N_M / N$, $p_F = N_F / N$.
  - `one_null_exact_zero` (`55,210` names): $R = N - N_{\text{obs}} = 0$, proving deductively that the suppressed opposite-sex count is **exact zero** ($p_{\text{obs}} = 1.0, p_{\text{null}} = 0.0$ with zero uncertainty).
  - `one_null_suppressed_positive` (`57,941` names, residual sum `232,758`): $1 \le N - N_{\text{obs}} \le 19$. Never record the `NULL` cell as an observed zero, and never reconstruct or impute IBGE's withheld `< 20` minority-sex count! In strict observed sex tables (`first_names/sex=M` and `sex=F`), include only directly published `male_count` (`60,954` rows, mass `92,287,140`) and `female_count` (`73,361` rows, mass `97,754,764`), which already cover **`99.8207%` (`190,041,904 / 190,383,184`)** of all national given-name mass. In `sex_prior`, keep `count_male` / `count_female` nullable (`None` when suppressed), store `residual_unassigned = N - N_{\text{obs}} \in [1, 19]`, set the observed sex's empirical rate to $\hat{p}_{\text{obs}}(i) = N_{i,\text{obs}} / N_i < 1.0$ (exact ratio of two published integers, **not** `1.0`), and set the suppressed opposite sex's rate to `NaN` (excluded from opposite-sex conditionals). This satisfies **exact national marginal coherence**:
    $$\frac{P_{\text{nat}}(N=i)\,\hat{p}_s(i)}{\sum_{j:\,N_{j,s}\text{ obs}} P_{\text{nat}}(N=j)\,\hat{p}_s(j)} = \frac{\frac{N_i}{\sum_k N_k}\cdot\frac{N_{i,s}}{N_i}}{\sum_{j:\,N_{j,s}\text{ obs}} \frac{N_j}{\sum_k N_k}\cdot\frac{N_{j,s}}{N_j}} = \frac{N_{i,s}}{\sum_{j:\,N_{j,s}\text{ obs}} N_{j,s}} = P_{\text{strict}}(N=i \mid S=s)$$
    to machine precision, without ever fabricating `< 20` counts!
  - `both_null_suppressed` (`4,725` names, $20 \le N \le 38$, total mass `108,522` = `0.057%`): both $N_M \le 19$ and $N_F \le 19$; retain in unconditioned national sampling, exclude from sex-conditioned tables (`p_male = NaN, p_female = NaN`), and **do not invoke Brasil.IO or Gemini LLM gap-fill on 2022 data** (`99.82%` empirical coverage makes LLM heuristics unnecessary).
- **Observed 2022 sex mixture:** Among sex-observed given-name occurrences, $\pi_M^{\text{obs}} = 92,287,140 / 190,041,904 = 0.485615$ and $\pi_F^{\text{obs}} = 97,754,764 / 190,041,904 = 0.514385$. Keep `sex_conditioning='mixed'` documented as a balanced `0.5 / 0.5` design and add `sex_conditioning='population'` using empirical $\pi^{\text{obs}}$ (or implied $Z(c, s)$ under `estimated` mode).
- **Legacy 2010 Gemini cleanup:** In `scripts/ingest_to_parquet.py` (`_merge_sex_prior`), stop fabricating `count_male=1` / `count_female=1` / `count_total=1` on LLM-classified rows; store `count_male=0, count_female=0, count_total=0` so synthetic LLM labels are never mistaken for 1-person empirical observations.

### 3. Cohort Indexing Alignment (Preventing the 10-Year Shift Bug)
Legacy Census 2010 (`names_data.json`) labels birth cohorts by their **upper endpoint** (`ate1940` = `[1930, 1940)`, ..., `ate2010` = `[2000, 2010)`), whereas IBGE 2022 / `olob0` `name_by_decade.parquet` labels cohorts by **decade start** (`decade=1940` = `1940–1949`, ..., `decade=2000` = `2000–2009`, `decade=2010` = `2010–2019`, `decade=2020` = `2020–1 Aug 2022`, and `decade=1930` = `<= 1939` with `2,541,671` survivors — merging `<1930` and `1930–1939`, as verified both demographically against Brazil's 83+ population and by minimum cross-census TVD: $\mathrm{TVD}(\text{2010 }\texttt{ate2010},\, \text{2022 }\texttt{decade=2000}) = 0.133$ with `enzo = 0.144%` vs `0.139%`, whereas `2022 decade=2010` has `enzo = 1.079%`).

| Birth years | Legacy 2010 key (`names_data.json`) | `olob0` `decade` (`int16`) | `TimePeriod` enum member & value | Supported in `2010`? | Supported in `2022`? |
| --- | --- | --- | --- | :---: | :---: |
| Whole resident stock | *(not available)* | *(from `name_ranking`)* | `TimePeriod.ALL = 'all'` | No (`ValueError`) | **Yes (2022 default)** |
| `< 1930` | `ate1930` | *(merged into `1930`)* | `TimePeriod.UNTIL_1930 = 'ate1930'` | Yes | No (`ValueError`) |
| `1930–1939` (`<=1939` in 2022) | `ate1940` | `1930` | `TimePeriod.UNTIL_1940 = 'ate1940'` | Yes | Yes |
| `1940–1949` | `ate1950` | `1940` | `TimePeriod.UNTIL_1950 = 'ate1950'` | Yes | Yes |
| `1950–1959` | `ate1960` | `1950` | `TimePeriod.UNTIL_1960 = 'ate1960'` | Yes | Yes |
| `1960–1969` | `ate1970` | `1960` | `TimePeriod.UNTIL_1970 = 'ate1970'` | Yes | Yes |
| `1970–1979` | `ate1980` | `1970` | `TimePeriod.UNTIL_1980 = 'ate1980'` | Yes | Yes |
| `1980–1989` | `ate1990` | `1980` | `TimePeriod.UNTIL_1990 = 'ate1990'` | Yes | Yes |
| `1990–1999` | `ate2000` | `1990` | `TimePeriod.UNTIL_2000 = 'ate2000'` | Yes | Yes |
| `2000–2009` | `ate2010` | `2000` | `TimePeriod.UNTIL_2010 = 'ate2010'` | **Yes (2010 default)** | Yes |
| `2010–2019` | *(post-2010)* | `2010` | `TimePeriod.UNTIL_2020 = 'ate2020'` | No (`ValueError`) | Yes |
| `2020–1 Aug 2022` (partial) | *(post-2010)* | `2020` | `TimePeriod.PERIOD_2020_2022 = '2020_2022'` | No (`ValueError`) | Yes |

### 4. Conditioning Policy: Strict Observed vs. Lazy Bayes Estimation
The 2022 tables contain **1D/2D marginals only** (`national`, `national × sex`, `national × cohort`, `UF`). Joining marginals does not create observed joint counts:
- **`conditioning_mode='strict'` (default for `census_year=2022`):** Serves only directly observed distributions:
  1. National whole-census: `(time_period=ALL, uf=None, sex=None)`
  2. National by sex: `(time_period=ALL, uf=None, sex in {'M', 'F'})`
  3. National by birth cohort: `(time_period=<2022 cohort>, uf=None, sex=None)`
  4. UF whole-census: `(time_period=ALL, uf=<UF>, sex=None)` (selected via `uf_conditioning=True` or scalar/per-row `uf` without `sex`)
  Any joint request (`UF × sex`, `cohort × sex`, `UF × cohort`, `UF × cohort × sex`) raises `ValueError` naming the missing joint observation and showing how to opt into `conditioning_mode='estimated'` where applicable. **Zero silent fallback or dropped conditions.**
- **`conditioning_mode='estimated'` (explicit opt-in):** Permits `UF × sex` (with `time_period=ALL`) and `cohort × sex` (with `uf=None`) under the conditional-independence assumption $P(S = s \mid N = i, C = c) \approx P_{\text{nat}}(S = s \mid N = i)$ via Bayes' rule:
  $$P_{\text{est}}(N = i \mid C = c, S = s) = \frac{P_{\text{obs}}(N = i \mid C = c)\, \hat{p}_s(i)}{Z(c, s)}, \qquad Z(c, s) = \sum_{j \in \mathcal{K}} P_{\text{obs}}(N = j \mid C = c)\, \hat{p}_s(j)$$
  where $\mathcal{K}$ is the set of names with non-null 2022 sex prior ($\eta(c) = \sum_{j \in \mathcal{K}} P_{\text{obs}}(N = j \mid C = c)$ is the retained coverage mass). `UF × cohort` remains rejected with `ValueError` even in `'estimated'` mode because cohort age structures vary across UFs without a defensible name-level invariance law.

### 5. Surname Token-Slot Weights vs. Person-Level Presence
In `name_ranking` (`surname`), $\sum_{s} \text{frequency}(s) = 333,496,261$ across `203,080,756` residents ($\bar{k} \approx 1.6422$ recorded surname tokens per person, or `164.2185%` exact unrounded ratio vs. `sum(percentage) = 161.9529%` on upstream's 4-decimal-rounded `percentage` column):
- IBGE's headline `Silva = 16.76%` (`34,030,104 / 203,080,756`) is **person-level presence** across all surname positions, whereas the normalized token-slot share is:
  $$q_{\text{Silva}} = \frac{34,030,104}{333,496,261} = 0.10204044, \qquad q_{\text{Santos}} = \frac{21,367,475}{333,496,261} = 0.06407111$$
- Under two independent with-replacement slot draws, person-level presence is $1 - (1 - q_s)^2$ ($19.37\%$ for `Silva`), with identical-stem collision probability $\sum_s q_s^2 \approx 0.0193$. In `census_year=2022` two-surname mode (`with_only_one_surname=False`), resample slot 2 conditional on $s_2 \neq s_1$ (when table support $|S| \ge 2$) so synthetic names never emit `"Maria da Silva Silva"`, and document both slot weight $q_s$ and resulting two-slot presence $q_s + \sum_{j \neq s} q_j \frac{q_s}{1 - q_j}$ explicitly. Keep `census_year=2010` assembly unchanged for seeded backward compatibility.
- When UF conditioning is active in `census_year=2022`, draw surnames from `census_year=2022/surnames/uf=<UF>/part.parquet` (capturing regional concentrations such as `Santos` in Sergipe and `Silva` in Alagoas/Pernambuco); when `top_40=True` in `census_year=2022`, slice the top 40 entries by `count` from the active 2022 surname table rather than falling back to 2010 JSON.

### 6. Numerical Precision & Four-Layer Statistical Validation
- **Float64 & `math.fsum`:** Upgrade Parquet `weight` (`_SCHEMA`) and `p_male` / `p_female` (`_SEX_PRIOR_SCHEMA`) from `pa.float32()` to `pa.float64()` and compute normalized weights with `math.fsum`, keeping $\|\mathbf{w}\|_1 - 1 < 10^{-15}$ across 201k-row tables.
- **Display casing normalization:** `olob0` `name_text` is lowercase ASCII (`'maria'`, `'silva'`). Canonicalize lookup keys with `.strip().lower()`, and store Title-Cased display strings (`'Maria'`, `'Silva'`) in 2022 Parquet `name` columns so `name_raw=False` (`'Maria da Silva'`) and `name_raw=True` (`.upper()` $\to$ `'MARIA DA SILVA'`, plus `SURNAME_PREFIXES` matching) work identically to `0.2.0`. Preserve spelling variants (`Ana` vs `Anna`, `Luis` vs `Luiz`) as distinct rows and document IBGE's diacritic-stripped source strings (`Joao`, `Goncalves`) without inventing heuristic accents.
- **Replace the three statistical anti-patterns in `tests/test_distribution_validation.py`:**
  1. Remove `ks_2samp` on arbitrary integer label indices (`ks_2samp` is not permutation-invariant on nominal categories).
  2. Remove top-50 truncation + `exp_counts` rescaling (`e * total_obs / total_exp` masks arbitrary probability mass leaks between the top-50 head and the `128,408`-name tail).
  3. Add **Layer A** (deterministic ingestion conservation laws), **Layer B** (exact $O(M)$ closed-form alias-table probability reconstruction via `np.bincount`, zero randomness, `< 50 ms` in normal CI), **Layer C** (exhaustive tail-pooled multinomial $\chi^2$ GoF with all pooled $E_j \ge 5$, Holm–Bonferroni FWER control at $\alpha_{\text{FWER}} = 0.001$, $\mathrm{TVD}$ and $\ell_\infty$ bounds, plus two mandatory negative controls), and **Layer D** (cross-table & demographic coherence diagnostics in `scripts/audit_datasets.py`).

---

## Package Workability, Hugging Face Runtime Delivery, & Resource Budgets

To keep `ptbr-sampler` `0.3.0` near-instant to `pip`/`uv` install (`< 150 KiB` wheel), fast to import, safe offline/in-CI, and lightweight in memory:

1. **Ultra-Slim Wheel (`< 150 KiB`) + Pinned Hugging Face Dataset Hub (`arthrod/ptbr-sampler-data`):**
   - **Zero dataset payload in the Python wheel:** Exclude `ptbr_sampler/data/parquet/**`, `ptbr_sampler/data/raw/**`, `ptbr_sampler/data/cities_with_ceps.json`, `ptbr_sampler/data/locations_data*.json*`, `ptbr_sampler/data/names_data.json`, `ptbr_sampler/data/surnames_data.json`, `ptbr_sampler/data/middle_names.json`, and `ptbr_sampler/tests/**` via `[tool.uv.build-backend]` `wheel-exclude`. Only `ptbr_sampler/data/dataset_manifest.json` (`~16 KiB` uncompressed, `~4 KiB` zipped) ships inside the `.whl`, shrinking the published wheel from `~80 MiB` to **`< 150 KiB`**.
   - **Immutable, cryptographically verified runtime resolution (`ptbr_sampler/datasets.py`):**
     - `dataset_manifest.json` pins `hf_repo_id` (`"arthrod/ptbr-sampler-data"`), an immutable 40-character Hugging Face commit OID (`hf_revision`), and `{sha256, size_bytes, census_years}` for every runtime artifact.
     - Resolution order in `ensure_data_file(relpath)`:
       1. `PTBR_SAMPLER_DATA_DIR/<relpath>` (when `PTBR_SAMPLER_DATA_DIR` is set for pre-baked Docker/air-gapped deployments),
       2. Local repository checkout `ptbr_sampler/data/<relpath>` when present (unless `PTBR_SAMPLER_IGNORE_LOCAL_DATA=1`, used in wheel-simulation tests), so contributors and local repo pytest runs incur zero network I/O,
       3. Revision-addressed user cache `<cache_root>/<hf_revision>/<relpath>` (`PTBR_SAMPLER_CACHE_DIR`, `$XDG_CACHE_HOME/ptbr-sampler`, or `~/.cache/ptbr-sampler`),
       4. On-demand HTTPS streaming download from `https://huggingface.co/datasets/<hf_repo_id>/resolve/<hf_revision>/<relpath>` under a per-file cross-process advisory lock (`fcntl.flock`), verifying streaming SHA-256 and exact byte count into `<dest>.<pid>.part` before atomic `os.replace`. Optional `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` headers are attached **only** to `huggingface.co` and stripped on cross-origin redirects (`*.hf.co` CDN nodes). Setting `PTBR_SAMPLER_OFFLINE=1` disables network calls and raises a deterministic `RuntimeError` pointing to `ptbr datasets prefetch`.
   - **Granular Partition-Level Lazy Fetching:**
     - `PartitionStore` accepts a `path_resolver` callback wired to `ensure_data_file`. A cold `BrazilianNameSampler.from_parquet().get_random_name()` downloads **only** the 2–3 touched files (`census_year=2022/first_names/scope=national/part.parquet`, `census_year=2022/surnames/scope=national/part.parquet`, and `middle_names.json` — `~3.1 MiB` total), never legacy 2010 JSONs or unused UF/cohort partitions.
     - `ptbr datasets prefetch [--census-year 2022|2010|all]`, `ptbr datasets status [--verify]`, and `ptbr datasets clear-cache` give Docker builds and CI explicit pre-warming and SHA-256 audit controls.
2. **Zero Cartesian Partition Explosion (< 13 MiB total 2022 Parquet on Hugging Face):**
   - Materialize **only observed 1D marginals** under `parquet/census_year=2022/`:
     - `first_names/scope=national/part.parquet` (`128,458` rows)
     - `first_names/sex=M/part.parquet` (`60,954` rows) and `first_names/sex=F/part.parquet` (`73,361` rows)
     - `first_names/period=<period>/part.parquet` (`10` cohorts, `221,524` rows total)
     - `first_names/uf=<UF>/part.parquet` (`27` UFs, `379,474` rows total)
     - `sex_prior/scope=national/part.parquet` (`128,458` rows)
     - `surnames/scope=national/part.parquet` (`201,601` rows)
     - `surnames/uf=<UF>/part.parquet` (`27` UFs, `449,093` rows total)
     - `states/part.parquet` (`27` rows from `state.parquet`)
   - **Never** pre-compute `27 × 10 × 2 = 540` full-tail `UF × period × sex` Parquet files. Compute opt-in `conditioning_mode='estimated'` tables lazily in memory by vectorized NumPy multiplication (`< 5 ms` cold build) and cache the resulting `AliasTable` inside `BrazilianNameSampler`.
3. **Runtime Latency & Memory Reuse (`ptbr_sampler/sampler.py` & `ptbr_sampler/br_name_class.py`):**
   - Replace per-call `copy.deepcopy(...)` + fresh `BrazilianNameSampler` reconstruction in `ptbr_sampler/sampler.py` with an LRU-cached `_get_name_sampler(...)` helper keyed by `(census_year, names_path, surnames_path, middle_names_path, parquet_root, conditioning_mode)`, deepcopying location dictionaries only when `locations_path` mutates them.
   - In the new `0.3.0` default (`census_year=2022`), `BrazilianNameSampler.from_parquet()` / `from_bundled_parquet()` never touches 2010 `names_data.json` (`17 MiB`) or `surnames_data.json` (`5.5 MiB`).
   - Sort `(uf, sex)` conditioning buckets deterministically (`sorted(buckets.items(), key=lambda kv: (kv[0][0] or '', kv[0][1] or ''))`) so seeded RNG streams never depend on hash/insertion ordering.

---

## File Structure & Responsibility Map

| File | Action | Responsibility |
| --- | --- | --- |
| `pyproject.toml`, `ptbr_sampler/__init__.py`, `.gitignore` | Modify | Bump package version to `0.3.0`; add `huggingface-hub>=0.26` to `[project.optional-dependencies].dev`; configure `wheel-exclude` so only code + `dataset_manifest.json` ship in `< 150 KiB` `.whl`; ignore raw `.parquet` / `.part` staging files |
| `scripts/audit_datasets.py` | Create | Offline & pinned-snapshot statistical auditor: SHA-256/schema verification, censoring regime decomposition, cohort TVD alignment matrix, UF-vs-national marginal coherence, and JSON/Markdown discrepancy ledger output |
| `tests/test_dataset_audit.py` | Create | Deterministic offline unit tests for key uniqueness, negative counts, censoring classification (`R=0` vs `1<=R<=19` vs both-null), percentage-vs-proportion scaling, spelling-variant preservation, and cohort shift detection |
| `docs/sources/ibge-nomes-2022-availability.md` | Create | Empirical capability matrix, pinned `olob0` artifact manifest, censoring math, cohort boundary verification, and discrepancy ledger |
| `ptbr_sampler/sampling/validation.py` | Create | Reusable statistical validation primitives: `reconstruct_alias_probabilities`, `total_variation_distance`, `linf_distance`, `exhaustive_multinomial_gof` (adaptive tail/cell pooling with $E_j \ge 5$), and `holm_bonferroni_reject` |
| `ptbr_sampler/sampling/alias.py` | Modify | Expose `AliasTable.induced_probabilities()` delegating to exact $O(M)$ alias reconstruction and `AliasTable.top_k(k)` for `top_40` slicing on 2022 Parquet tables |
| `ptbr_sampler/sampling/store.py` | Modify | Support `float64` weights cleanly alongside count-based loading, plus optional `path_resolver: Callable[[Path], Path]` for lazy on-demand partition downloads |
| `ptbr_sampler/datasets.py` | Create | Pure-stdlib runtime dataset resolver & downloader: loads `dataset_manifest.json`, resolves local checkout / `PTBR_SAMPLER_DATA_DIR` / `~/.cache/ptbr-sampler/<hf_revision>/`, downloads on demand with cross-process lock + cross-origin token stripping + streaming SHA-256 verification, exposes `ensure_data_file`, `ensure_parquet_root`, `prefetch_datasets`, `dataset_cache_status`, and `clear_dataset_cache` |
| `ptbr_sampler/data/dataset_manifest.json` | Create | Small (`~16 KiB`) packaged manifest pinning `hf_repo_id` (`arthrod/ptbr-sampler-data`), immutable 40-char `hf_revision`, and `{sha256, size_bytes, census_years}` for every runtime file |
| `scripts/publish_hf_dataset.py` | Create | Stages runtime Parquet + geography artifacts and generated Dataset Card (`README.md`), validates Parquet integrity, uploads to Hugging Face Hub (`HfApi.upload_folder`), and pins the returned immutable commit SHA into `ptbr_sampler/data/dataset_manifest.json` |
| `scripts/download_datasets.py` | Modify | Add `--fetch-ibge-2022` pinned to `05efb85c92af43da2ed4ed088d1e0c9f17160e65` (`5` Parquet files), HTTPS + Hugging Face redirect allowlist, streaming SHA-256 verification, `.part` atomic writes, bounded transient retries (`429`/`5xx`/timeout), cache validation before skip, and `source_manifest.json` |
| `scripts/ingest_to_parquet.py` | Modify | Upgrade schemas to `float64` + `math.fsum`, separate `fetched_at_utc` from `built_at_utc`, fix Gemini `count=0` in 2010 `_merge_sex_prior`, add `ingest_ibge_2022(...)` writing `parquet/census_year=2022/` 1D marginals + `sex_prior` + `states` via atomic staging swap |
| `ptbr_sampler/data_origins.py` | Modify | Make `DataOrigin` manifest- and cache-aware (`remote_artifacts` + `raw_inputs` alongside local checkout status), default provenance reporting to Census 2022 + shared geography, and expose Hugging Face repo/revision provenance |
| `ptbr_sampler/br_name_class.py` | Modify | Default `from_parquet` and `from_bundled_parquet` to `census_year=2022` backed by `ensure_parquet_root`; add `TimePeriod.ALL`, `UNTIL_2020`, `PERIOD_2020_2022` + `LEGACY_2010_PERIODS` guard; add `conditioning_mode`, lazy `estimated` Bayes builder, UF surname routing, 2022 duplicate-stem resampling, and deterministic bucket sorting |
| `ptbr_sampler/sampler.py`, `sample.py`, `ptbr_sampler/cli.py` | Modify | Flip default to `census_year=2022` (`time_period=None -> TimePeriod.ALL`; `census_year=2010 -> TimePeriod.UNTIL_2010`); resolve default JSON/Parquet paths through `ptbr_sampler.datasets`; add `ptbr datasets status|prefetch|clear-cache` subcommands; cache reusable sampler instances |
| `tests/test_runtime_datasets.py` | Create | Unit & local-HTTP integration tests for `ptbr_sampler/datasets.py` and `scripts/publish_hf_dataset.py`: cold cache download, SHA-256 mismatch rejection, corrupt `.part` cleanup, offline mode, cross-origin `Authorization` stripping, multi-thread/process lock safety, and `PartitionStore` lazy fetch |
| `tests/test_dataset_scripts.py`, `tests/test_data_origins.py`, `tests/test_cli.py` | Modify / Create | Mocked network retry/checksum tests, 2022 ingestion tests, manifest-backed `data_origins` checks, CLI tests for Census 2022 default, `--census-year 2010`, `--conditioning-mode`, and `ptbr datasets` subcommands |
| `tests/conftest.py`, `tests/test_smoke.py`, `tests/test_pr_additions.py`, `tests/test_name_sampler.py`, `tests/test_sample_api.py`, `tests/test_sampler.py`, `tests/test_batch_parity.py`, `tests/test_distribution_validation.py` | Modify | Update version (`0.3.0`), `TimePeriod` enum-count (`9 -> 12`), and runtime-data availability fixtures; verify Census 2022 default across `sample()` and `BrazilianNameSampler.from_bundled_parquet()`; add Layer B exact alias reconstruction and Layer C exhaustive $\chi^2$ + Holm–Bonferroni + negative controls |
| `docs/*.md`, `README.md`, `README.en.md`, `CHANGELOG.md`, `todo.md`, `THIRD_PARTY_NOTICES.md` | Modify / Create | Document `0.3.0` Census 2022 default, Hugging Face runtime dataset caching/prefetching/env vars, disclosure thresholds (`20`/`15`/`10`), observed vs estimated coverage definitions, dataset attribution, and release changelog |

---

### Task 1: Build the Statistical Audit Engine & Verify Baseline Invariants

**Files:**
- Create: `ptbr_sampler/sampling/validation.py`
- Create: `scripts/audit_datasets.py`
- Create: `tests/test_dataset_audit.py`
- Create: `docs/sources/ibge-nomes-2022-availability.md`
- Modify: `ptbr_sampler/sampling/alias.py:130-155`

- [ ] **Step 1: Write failing tests for statistical primitives and Census 2022 audit invariants**

Create `tests/test_dataset_audit.py`:

```python
"""Deterministic unit tests for Census 2022 statistical auditing and validation primitives."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.validation import (
    exhaustive_multinomial_gof,
    holm_bonferroni_reject,
    linf_distance,
    reconstruct_alias_probabilities,
    total_variation_distance,
)
from scripts.audit_datasets import (
    CensoringSummary,
    audit_ibge_2022_tables,
    classify_sex_censoring,
    compute_cohort_alignment_tvd,
    format_census_2022_display_name,
)


def test_reconstruct_alias_probabilities_is_exact_to_machine_precision():
    weights = np.array([0.50, 0.30, 0.15, 0.049, 0.001], dtype=np.float64)
    table = AliasTable.from_weights(['A', 'B', 'C', 'D', 'E'], weights)
    induced = reconstruct_alias_probabilities(table.prob, table.alias)
    assert total_variation_distance(induced, table.weights) < 1e-14
    assert linf_distance(induced, table.weights) < 1e-14
    assert np.allclose(table.induced_probabilities(), induced)


def test_exhaustive_multinomial_gof_catches_head_to_tail_leak():
    # 50 head items (each 0.01 = 0.50 total) + 500 tail items (each 0.001 = 0.50 total)
    probs = np.concatenate([np.full(50, 0.01), np.full(500, 0.001)])
    # Corrupt draw generator: shifts 15% mass from tail into head uniformly
    corrupt_probs = np.concatenate([np.full(50, 0.013), np.full(500, 0.0007)])
    rng = np.random.default_rng(12345)
    draws = rng.choice(len(probs), size=20_000, p=corrupt_probs)
    counts = np.bincount(draws, minlength=len(probs))

    res = exhaustive_multinomial_gof(counts, probs, min_expected=5.0)
    assert res.pooled_bins >= 51
    assert abs(res.expected_sum - 20_000.0) < 1e-9
    assert res.p_value < 1e-10
    assert res.tvd > 0.10


def test_holm_bonferroni_controls_familywise_error():
    p_values = {'p1': 0.0001, 'p2': 0.02, 'p3': 0.50}
    rejected = holm_bonferroni_reject(p_values, alpha=0.001)
    assert rejected == {'p1'}


def test_classify_sex_censoring_distinguishes_four_regimes():
    assert classify_sex_censoring(total=100, male=60, female=40) == 'both_observed'
    assert classify_sex_censoring(total=55, male=55, female=None) == 'one_null_exact_zero'
    assert classify_sex_censoring(total=60, male=50, female=None) == 'one_null_suppressed_positive'
    assert classify_sex_censoring(total=28, male=None, female=None) == 'both_null_suppressed'
    with pytest.raises(ValueError, match='conservation'):
        classify_sex_censoring(total=100, male=50, female=40)
    with pytest.raises(ValueError, match='threshold'):
        classify_sex_censoring(total=100, male=75, female=None)


def test_display_name_preserves_spelling_variants_and_capitalizes():
    assert format_census_2022_display_name('maria') == 'Maria'
    assert format_census_2022_display_name('ana') != format_census_2022_display_name('anna')
    assert format_census_2022_display_name('luis') != format_census_2022_display_name('luiz')


def _write_minimal_2022_fixture(root: Path, *, duplicate: bool = False, negative: bool = False) -> None:
    ranking_rows = [
        ('maria', 'given', -10 if negative else 100, 50.0, 1),
        ('ana', 'given', 60, 30.0, 2),
        ('anna', 'given', 25, 12.5, 3),
        ('ariel', 'given', 24, 12.0, 4),
        ('silva', 'surname', 120, 60.0, 1),
        ('perl', 'surname', 24, 12.0, 2),
    ]
    if duplicate:
        ranking_rows.append(('maria', 'given', 100, 50.0, 1))
    pq.write_table(
        pa.table(
            {
                'name_text': [r[0] for r in ranking_rows],
                'name_type': [r[1] for r in ranking_rows],
                'frequency': pa.array([r[2] for r in ranking_rows], type=pa.int32()),
                'percentage': pa.array([r[3] for r in ranking_rows], type=pa.float64()),
                'rank': pa.array([r[4] for r in ranking_rows], type=pa.int32()),
            }
        ),
        root / 'name_ranking.parquet',
    )
    # Note: ('perl', 'surname') intentionally absent from detail to test documented IBGE WAF gap
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria', 'ana', 'anna', 'ariel', 'silva'],
                'name_type': ['given', 'given', 'given', 'given', 'surname'],
                'letter_rank': pa.array([1, 1, 2, 3, 1], type=pa.int32()),
                'male_count': pa.array([20, None, None, None, None], type=pa.int32()),
                'female_count': pa.array([80, 60, 20, None, None], type=pa.int32()),
                'median_age': pa.array([45.0, 38.0, 35.0, 29.0, 40.0], type=pa.float64()),
            }
        ),
        root / 'name_detail.parquet',
    )
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria', 'ana'],
                'name_type': ['given', 'given'],
                'decade': pa.array([2000, 2010], type=pa.int16()),
                'frequency': pa.array([50, 30], type=pa.int32()),
            }
        ),
        root / 'name_by_decade.parquet',
    )
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria', 'silva'],
                'name_type': ['given', 'surname'],
                'state_code': pa.array([35, 35], type=pa.uint8()),
                'frequency': pa.array([40, 50], type=pa.int32()),
                'percentage': pa.array([40.0, 50.0], type=pa.float64()),
            }
        ),
        root / 'name_by_state.parquet',
    )
    pq.write_table(
        pa.table(
            {
                'code': pa.array([35], type=pa.uint8()),
                'abbreviation': ['SP'],
                'name': ['São Paulo'],
                'region_code': pa.array([3], type=pa.uint8()),
                'population': pa.array([200], type=pa.int32()),
            }
        ),
        root / 'state.parquet',
    )


def test_audit_ibge_2022_tables_passes_valid_fixture_and_tolerates_perl_gap(tmp_path: Path):
    _write_minimal_2022_fixture(tmp_path)
    report = audit_ibge_2022_tables(tmp_path)
    assert report['missing_detail_keys'] == [('perl', 'surname')]
    censoring: CensoringSummary = report['censoring']
    assert censoring.both_observed == 1
    assert censoring.one_null_exact_zero == 1
    assert censoring.one_null_suppressed_positive == 1
    assert censoring.both_null_suppressed == 1
    assert abs(report['maria_proportion_from_percentage'] - 0.50) < 1e-12


def test_audit_ibge_2022_tables_rejects_duplicates_and_negative_frequencies(tmp_path: Path):
    dup_dir = tmp_path / 'dup'
    dup_dir.mkdir()
    _write_minimal_2022_fixture(dup_dir, duplicate=True)
    with pytest.raises(ValueError, match='duplicate'):
        audit_ibge_2022_tables(dup_dir)

    neg_dir = tmp_path / 'neg'
    neg_dir.mkdir()
    _write_minimal_2022_fixture(neg_dir, negative=True)
    with pytest.raises(ValueError, match='negative'):
        audit_ibge_2022_tables(neg_dir)


def test_cohort_alignment_detects_ten_year_endpoint_vs_start_shift():
    legacy_2010 = {
        'ate2000': {'MARIA': 0.60, 'ENZO': 0.01, 'ANA': 0.39},
        'ate2010': {'MARIA': 0.38, 'ENZO': 0.02, 'ANA': 0.60},
    }
    olob0_2022_by_decade = {
        1990: {'maria': 610, 'enzo': 10, 'ana': 380},
        2000: {'maria': 390, 'enzo': 20, 'ana': 590},
        2010: {'maria': 250, 'enzo': 250, 'ana': 500},
    }
    matrix = compute_cohort_alignment_tvd(legacy_2010, olob0_2022_by_decade)
    # Legacy 'ate2010' (born 2000-2009) aligns with olob0 decade=2000, NOT decade=2010!
    assert matrix['ate2010'][2000] < 0.03
    assert matrix['ate2010'][2010] > 0.20
```

- [ ] **Step 2: Run `tests/test_dataset_audit.py` to verify failure**

Run: `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_dataset_audit.py -v`
Expected: `FAIL` with `ModuleNotFoundError: No module named 'ptbr_sampler.sampling.validation'`.

- [ ] **Step 3: Implement `ptbr_sampler/sampling/validation.py` and `AliasTable` helpers**

Create `ptbr_sampler/sampling/validation.py`:

```python
"""Exact and Monte Carlo statistical validation primitives for categorical tables."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True, frozen=True)
class MultinomialGoFResult:
    """Summary of an exhaustive tail-pooled categorical goodness-of-fit test."""

    chi2_stat: float
    g_stat: float
    p_value: float
    df: int
    pooled_bins: int
    sample_size: int
    expected_sum: float
    tvd: float
    linf: float


def reconstruct_alias_probabilities(prob: np.ndarray, alias: np.ndarray) -> np.ndarray:
    """Return the exact categorical probability vector induced by ``(prob, alias)`` in O(M).

    For a Walker/Vose table of size M, uniform slot choice i in {0..M-1} stays at i with
    probability prob[i]/M and redirects to alias[i] with probability (1 - prob[i])/M:

        p_induced[j] = (prob[j] + sum_{i: alias[i] == j} (1 - prob[i])) / M
    """
    p = np.asarray(prob, dtype=np.float64)
    a = np.asarray(alias, dtype=np.int64)
    if p.ndim != 1 or a.ndim != 1 or p.shape != a.shape or p.size == 0:
        raise ValueError('prob and alias must be non-empty 1D arrays of equal length')
    m = p.size
    redirected = np.bincount(a, weights=1.0 - p, minlength=m)
    return (p + redirected) / float(m)


def total_variation_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Return TVD(p, q) = 0.5 * sum_i |p_i - q_i| using compensated summation."""
    pa = np.asarray(p, dtype=np.float64)
    qa = np.asarray(q, dtype=np.float64)
    if pa.shape != qa.shape:
        raise ValueError(f'probability shape mismatch: {pa.shape} vs {qa.shape}')
    return 0.5 * math.fsum(np.abs(pa - qa).tolist())


def linf_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Return max_i |p_i - q_i|."""
    pa = np.asarray(p, dtype=np.float64)
    qa = np.asarray(q, dtype=np.float64)
    if pa.shape != qa.shape:
        raise ValueError(f'probability shape mismatch: {pa.shape} vs {qa.shape}')
    return float(np.max(np.abs(pa - qa)))


def exhaustive_multinomial_gof(
    observed_counts: np.ndarray,
    target_probs: np.ndarray,
    *,
    min_expected: float = 5.0,
) -> MultinomialGoFResult:
    """Run an exhaustive categorical GoF test without dropping or rescaling tail mass.

    Categories are sorted in descending order of ``target_probs`` and greedily pooled
    from largest to smallest so every pooled cell satisfies ``E_j >= min_expected``.
    If the final remainder cell has ``E_last < min_expected``, it is merged into the
    preceding cell. Thus ``sum(E_j) == n == sum(O_j)`` holds identically without ad-hoc
    renormalization, making head-to-tail probability leaks strictly detectable.
    """
    from scipy.stats import chi2  # noqa: PLC0415 - scipy is test-only

    obs = np.asarray(observed_counts, dtype=np.int64)
    probs = np.asarray(target_probs, dtype=np.float64)
    if obs.ndim != 1 or probs.ndim != 1 or obs.shape != probs.shape or obs.size == 0:
        raise ValueError('observed_counts and target_probs must be matching non-empty 1D arrays')
    prob_sum = math.fsum(probs.tolist())
    if abs(prob_sum - 1.0) > 1e-9:
        raise ValueError(f'target_probs must sum to 1.0 (got {prob_sum:.12f})')
    n = int(obs.sum())
    if n <= 0:
        raise ValueError('sample size n must be positive')

    emp_probs = obs.astype(np.float64) / float(n)
    tvd = total_variation_distance(emp_probs, probs)
    linf = linf_distance(emp_probs, probs)

    order = np.argsort(-probs, kind='mergesort')
    pooled_obs: list[float] = []
    pooled_exp: list[float] = []
    acc_obs = 0.0
    acc_exp = 0.0
    for idx in order:
        acc_obs += float(obs[idx])
        acc_exp += float(probs[idx]) * n
        if acc_exp >= min_expected:
            pooled_obs.append(acc_obs)
            pooled_exp.append(acc_exp)
            acc_obs = 0.0
            acc_exp = 0.0
    if acc_exp > 0.0 or acc_obs > 0.0:
        if pooled_exp:
            pooled_obs[-1] += acc_obs
            pooled_exp[-1] += acc_exp
        else:
            pooled_obs.append(acc_obs)
            pooled_exp.append(acc_exp)

    if len(pooled_exp) < 2:
        raise ValueError('need at least 2 pooled bins with expected count >= min_expected')

    o_arr = np.asarray(pooled_obs, dtype=np.float64)
    e_arr = np.asarray(pooled_exp, dtype=np.float64)
    chi2_stat = float(math.fsum(((o_arr - e_arr) ** 2 / e_arr).tolist()))
    nonzero = o_arr > 0
    g_terms = np.zeros_like(o_arr)
    g_terms[nonzero] = 2.0 * o_arr[nonzero] * np.log(o_arr[nonzero] / e_arr[nonzero])
    g_stat = float(math.fsum(g_terms.tolist()))
    df = len(pooled_exp) - 1
    p_value = float(chi2.sf(chi2_stat, df))

    return MultinomialGoFResult(
        chi2_stat=chi2_stat,
        g_stat=g_stat,
        p_value=p_value,
        df=df,
        pooled_bins=len(pooled_exp),
        sample_size=n,
        expected_sum=float(math.fsum(pooled_exp)),
        tvd=tvd,
        linf=linf,
    )


def holm_bonferroni_reject(p_values: dict[str, float], *, alpha: float = 0.001) -> set[str]:
    """Return keys rejected by the step-down Holm-Bonferroni procedure at FWER ``alpha``."""
    if not (0.0 < alpha < 1.0):
        raise ValueError('alpha must be in (0, 1)')
    m = len(p_values)
    ranked = sorted(p_values.items(), key=lambda kv: kv[1])
    rejected: set[str] = set()
    for rank_idx, (key, p_val) in enumerate(ranked):
        threshold = alpha / float(m - rank_idx)
        if p_val <= threshold:
            rejected.add(key)
        else:
            break
    return rejected
```

Update `ptbr_sampler/sampling/alias.py` to normalize sums with `math.fsum` (`import math`) and add `induced_probabilities()` and `top_k(k: int)` to `AliasTable`:

```python
    # In build_alias(weights):
    total = math.fsum(w.tolist())

    # In AliasTable.from_counts(cls, labels, counts):
    total = int(counts_arr.sum())
    if total <= 0:
        raise ValueError('counts must sum to a positive value')
    weights = counts_arr.astype(np.float64) / float(total)

    # In AliasTable.from_weights(cls, labels, weights):
    total = math.fsum(weights_arr.tolist())
    if total <= 0.0:
        raise ValueError('weights must sum to a positive value')
    weights_arr = weights_arr / total

    def induced_probabilities(self) -> np.ndarray:
        """Return the exact categorical probabilities induced by ``(self.prob, self.alias)``."""
        from .validation import reconstruct_alias_probabilities  # noqa: PLC0415

        return reconstruct_alias_probabilities(self.prob, self.alias)

    def top_k(self, k: int) -> AliasTable:
        """Return a renormalised ``AliasTable`` over the top ``k`` entries ranked by weight/count."""
        if k < 1:
            raise ValueError('k must be >= 1')
        if k >= len(self):
            return self
        metric = self.counts.astype(np.float64) if int(self.counts.sum()) > 0 else self.weights
        order = np.argsort(-metric, kind='mergesort')[:k]
        if int(self.counts.sum()) > 0:
            return AliasTable.from_counts(self.labels[order].tolist(), self.counts[order].tolist())
        return AliasTable.from_weights(self.labels[order].tolist(), self.weights[order].tolist())
```

- [ ] **Step 4: Implement `scripts/audit_datasets.py` and write `docs/sources/ibge-nomes-2022-availability.md`**

Create `scripts/audit_datasets.py`:

```python
"""Statistical audit and discrepancy-ledger generator for IBGE Census 2022 tables."""

from __future__ import annotations

import argparse
import json
import math
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from ptbr_sampler.sampling.validation import total_variation_distance

DOCUMENTED_MISSING_DETAIL_KEYS: frozenset[tuple[str, str]] = frozenset({('perl', 'surname')})


@dataclass(slots=True, frozen=True)
class CensoringSummary:
    both_observed: int
    one_null_exact_zero: int
    one_null_suppressed_positive: int
    both_null_suppressed: int
    observed_male_mass: int
    observed_female_mass: int
    suppressed_positive_residual_mass: int
    both_null_mass: int


def format_census_2022_display_name(name_text: str) -> str:
    """Convert lowercase upstream ``name_text`` into canonical Title-Cased display form."""
    cleaned = ' '.join(name_text.strip().split())
    if not cleaned:
        raise ValueError('name_text must be non-empty')
    return ' '.join(tok.capitalize() for tok in cleaned.split(' '))


def _fold_ascii_key(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text.strip().lower())
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def classify_sex_censoring(total: int, male: int | None, female: int | None) -> str:
    """Classify a given-name row under IBGE's <20 sex-cell disclosure rule."""
    if total < 20:
        raise ValueError(f'national given-name frequency below <20 threshold: {total}')
    if male is not None and female is not None:
        if male < 20 or female < 20:
            raise ValueError(f'observed sex count below <20 threshold: male={male}, female={female}')
        if total != male + female:
            raise ValueError(f'sex-count conservation violated: total={total} != {male}+{female}')
        return 'both_observed'
    if male is not None or female is not None:
        obs = male if male is not None else female
        assert obs is not None
        if obs < 20:
            raise ValueError(f'observed sex count below <20 threshold: {obs}')
        residual = total - obs
        if residual < 0 or residual > 19:
            raise ValueError(f'suppressed opposite-sex residual outside [0, 19] threshold: {residual}')
        return 'one_null_exact_zero' if residual == 0 else 'one_null_suppressed_positive'
    if total > 38:
        raise ValueError(f'both_null_suppressed impossible when total={total} > 38 (at least one sex >= 20)')
    return 'both_null_suppressed'


def audit_ibge_2022_tables(raw_dir: Path) -> dict[str, Any]:
    """Validate keys, foreign-key inclusion, signs, scaling, and censoring on 2022 Parquet tables."""
    ranking = pq.read_table(raw_dir / 'name_ranking.parquet')
    detail = pq.read_table(raw_dir / 'name_detail.parquet')
    by_decade = pq.read_table(raw_dir / 'name_by_decade.parquet')
    by_state = pq.read_table(raw_dir / 'name_by_state.parquet')
    states = pq.read_table(raw_dir / 'state.parquet')

    state_pop_by_code = dict(
        zip(states['code'].to_pylist(), states['population'].to_pylist(), strict=True)
    )
    national_pop = int(sum(state_pop_by_code.values()))
    if national_pop <= 0:
        raise ValueError('state.parquet population sum must be positive')

    ranking_freq: dict[tuple[str, str], int] = {}
    ranking_pct: dict[tuple[str, str], float] = {}
    for name_text, name_type, freq, pct in zip(
        ranking['name_text'].to_pylist(),
        ranking['name_type'].to_pylist(),
        ranking['frequency'].to_pylist(),
        ranking['percentage'].to_pylist(),
        strict=True,
    ):
        if freq is None or int(freq) <= 0:
            raise ValueError(f'negative or zero frequency for {(name_text, name_type)}: {freq}')
        key = (str(name_text), str(name_type))
        if key in ranking_freq:
            raise ValueError(f'duplicate primary key in name_ranking: {key}')
        ranking_freq[key] = int(freq)
        ranking_pct[key] = float(pct)

    detail_map: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for name_text, name_type, male, female in zip(
        detail['name_text'].to_pylist(),
        detail['name_type'].to_pylist(),
        detail['male_count'].to_pylist(),
        detail['female_count'].to_pylist(),
        strict=True,
    ):
        key = (str(name_text), str(name_type))
        if key in detail_map:
            raise ValueError(f'duplicate primary key in name_detail: {key}')
        if key not in ranking_freq:
            raise ValueError(f'orphan key in name_detail absent from name_ranking: {key}')
        detail_map[key] = (None if male is None else int(male), None if female is None else int(female))

    missing_detail = sorted(set(ranking_freq) - set(detail_map))
    unexpected_missing = set(missing_detail) - DOCUMENTED_MISSING_DETAIL_KEYS
    if unexpected_missing:
        raise ValueError(f'unexpected missing name_detail keys: {sorted(unexpected_missing)}')

    seen_decade: set[tuple[str, str, int]] = set()
    for name_text, name_type, decade, freq in zip(
        by_decade['name_text'].to_pylist(),
        by_decade['name_type'].to_pylist(),
        by_decade['decade'].to_pylist(),
        by_decade['frequency'].to_pylist(),
        strict=True,
    ):
        dkey = (str(name_text), str(name_type), int(decade))
        if dkey in seen_decade:
            raise ValueError(f'duplicate key in name_by_decade: {dkey}')
        seen_decade.add(dkey)
        if (dkey[0], dkey[1]) not in ranking_freq:
            raise ValueError(f'orphan key in name_by_decade: {dkey}')
        if int(freq) <= 0:
            raise ValueError(f'negative or zero decade frequency: {dkey}')

    seen_state: set[tuple[str, str, int]] = set()
    for name_text, name_type, scode, freq in zip(
        by_state['name_text'].to_pylist(),
        by_state['name_type'].to_pylist(),
        by_state['state_code'].to_pylist(),
        by_state['frequency'].to_pylist(),
        strict=True,
    ):
        skey = (str(name_text), str(name_type), int(scode))
        if skey in seen_state:
            raise ValueError(f'duplicate key in name_by_state: {skey}')
        seen_state.add(skey)
        if int(scode) not in state_pop_by_code:
            raise ValueError(f'unknown state_code in name_by_state: {scode}')
        if (skey[0], skey[1]) not in ranking_freq:
            raise ValueError(f'orphan key in name_by_state: {skey}')
        if int(freq) <= 0:
            raise ValueError(f'negative or zero state frequency: {skey}')

    counts_by_regime: dict[str, int] = defaultdict(int)
    obs_m = 0
    obs_f = 0
    supp_pos_mass = 0
    both_null_mass = 0
    for (name_text, name_type), total in ranking_freq.items():
        if name_type != 'given':
            continue
        male, female = detail_map[name_text, name_type]
        regime = classify_sex_censoring(total=total, male=male, female=female)
        counts_by_regime[regime] += 1
        if male is not None:
            obs_m += male
        if female is not None:
            obs_f += female
        if regime == 'one_null_suppressed_positive':
            supp_pos_mass += total - (male if male is not None else (female or 0))
        elif regime == 'both_null_suppressed':
            both_null_mass += total

    maria_pct = ranking_pct.get(('maria', 'given'), 0.0)
    return {
        'national_population': national_pop,
        'given_rows': sum(1 for (_, t) in ranking_freq if t == 'given'),
        'surname_rows': sum(1 for (_, t) in ranking_freq if t == 'surname'),
        'missing_detail_keys': missing_detail,
        'maria_proportion_from_percentage': maria_pct / 100.0,
        'censoring': CensoringSummary(
            both_observed=counts_by_regime['both_observed'],
            one_null_exact_zero=counts_by_regime['one_null_exact_zero'],
            one_null_suppressed_positive=counts_by_regime['one_null_suppressed_positive'],
            both_null_suppressed=counts_by_regime['both_null_suppressed'],
            observed_male_mass=obs_m,
            observed_female_mass=obs_f,
            suppressed_positive_residual_mass=supp_pos_mass,
            both_null_mass=both_null_mass,
        ),
    }


def compute_cohort_alignment_tvd(
    legacy_2010_periods: dict[str, dict[str, float]],
    olob0_by_decade: dict[int, dict[str, int]],
) -> dict[str, dict[int, float]]:
    """Compute pairwise TVD between legacy 2010 ``ate<Y>`` keys and 2022 ``decade`` bins."""
    norm_2010: dict[str, dict[str, float]] = {}
    for pkey, mapping in legacy_2010_periods.items():
        folded: dict[str, float] = defaultdict(float)
        for name, weight in mapping.items():
            folded[_fold_ascii_key(name)] += float(weight)
        tot = math.fsum(folded.values())
        norm_2010[pkey] = {k: v / tot for k, v in folded.items()}

    norm_2022: dict[int, dict[str, float]] = {}
    for dec, mapping in olob0_by_decade.items():
        folded_22: dict[str, float] = defaultdict(float)
        for name, cnt in mapping.items():
            folded_22[_fold_ascii_key(name)] += float(cnt)
        tot = math.fsum(folded_22.values())
        norm_2022[dec] = {k: v / tot for k, v in folded_22.items()}

    out: dict[str, dict[int, float]] = {}
    for pkey, p_dist in norm_2010.items():
        out[pkey] = {}
        for dec, q_dist in norm_2022.items():
            vocab = sorted(set(p_dist) | set(q_dist))
            p_vec = np.array([p_dist.get(k, 0.0) for k in vocab], dtype=np.float64)
            q_vec = np.array([q_dist.get(k, 0.0) for k in vocab], dtype=np.float64)
            out[pkey][dec] = total_variation_distance(p_vec, q_vec)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Audit Census 2022 Parquet tables.')
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--parquet-dir', type=Path, default=None)
    parser.add_argument('--json-out', type=Path, default=None)
    args = parser.parse_args(argv)

    report = audit_ibge_2022_tables(args.raw_dir)
    serializable = {
        **report,
        'missing_detail_keys': [list(k) for k in report['missing_detail_keys']],
        'censoring': asdict(report['censoring']),
    }
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(serializable, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(serializable, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

Document the complete capability matrix, censoring breakdown, cohort alignment proof, and discrepancy ledger in `docs/sources/ibge-nomes-2022-availability.md`.

- [ ] **Step 5: Run audit unit tests and commit Task 1**

Run: `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_dataset_audit.py -v`
Expected: `PASS` (`7 passed`).

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  ptbr_sampler/sampling/validation.py \
  ptbr_sampler/sampling/alias.py \
  scripts/audit_datasets.py \
  tests/test_dataset_audit.py \
  docs/sources/ibge-nomes-2022-availability.md
git -C /home/arthrod/workspace/ptbr-sampler commit -m "feat: add Census 2022 statistical audit engine and validation primitives"
```

---

### Task 2: Reconcile Documentation, Attribution, and Handoffs Against Empirical Evidence

**Files:**
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `docs/sources/ibge-nomes-no-brasil-2022.md`
- Modify: `docs/sources/genero-nomes.md`
- Modify: `docs/sources/gemini-gender-classifications.md`
- Modify: `docs/sources/bibliography.md`
- Modify: `docs/data-origins.md`
- Modify: `docs/architecture.md`
- Modify: `docs/handoff-fetch-and-ingest.md`
- Modify: `docs/handoff-resume-with-claude.md`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `todo.md`

- [ ] **Step 1: Correct source availability, disclosure thresholds, and coverage definitions**

Update `docs/sources/ibge-nomes-no-brasil-2022.md`, `docs/data-origins.md`, `docs/sources/genero-nomes.md`, `docs/sources/gemini-gender-classifications.md`, and `docs/sources/bibliography.md`:
- Replace claims that "no bulk download or mirror exists" with the verified Hugging Face compilation (`olob0/ibge-nomes-no-brasil-2022` at `05efb85c92af43da2ed4ed088d1e0c9f17160e65`) and distinguish IBGE's undocumented web-app v3 endpoints from documented stable public APIs.
- Correct IBGE disclosure thresholds per [Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf): `< 20` nationally and national-by-decade, `< 15` per UF, and `< 10` per municipality (regional thresholds are **lower**, not higher, than national).
- Define and report five distinct sex-coverage metrics instead of claiming "100% sex coverage":
  1. **Vocabulary lookup coverage** (share of distinct name types with any label)
  2. **Directly observed empirical mass** (`99.8207%` in Census 2022 `name_detail`; `~93%` row match in legacy Brasil.IO `genero-nomes`)
  3. **Deduced exact-zero mass** (`55,210` single-null 2022 names where $N - N_{\text{obs}} = 0$)
  4. **LLM-assigned uncalibrated mass** (legacy 2010 Gemini gap-fill only; `0.0%` in Census 2022)
  5. **Suppressed/excluded mass** (`341,280` occurrences = `0.1793%` across `one_null_suppressed_positive` + `both_null_suppressed` in Census 2022)
- Keep Brasil.IO blank-field parsing semantics separate from IBGE 2022 `NULL` censoring semantics.

- [ ] **Step 2: Add `THIRD_PARTY_NOTICES.md` and reconcile READMEs, architecture, `todo.md`, and handoffs for `0.3.0`**

- Create `THIRD_PARTY_NOTICES.md` separating the repository's code license from IBGE public-domain/statistical dissemination attribution, Gabriel Lobo's compilation attribution (`olob0/ibge-nomes-no-brasil-2022`, revision `05efb85c92af43da2ed4ed088d1e0c9f17160e65`), Álvaro Justen's `brasil.io/genero-nomes`, Arpen-Brasil civil-registry references, and the `arthrod/ptbr-sampler-data` Hugging Face runtime dataset mirror.
- Update `docs/architecture.md`, `README.md`, and `README.en.md` for **`ptbr-sampler` `0.3.0`**:
  - Document **Census 2022 (`census_year=2022`, `TimePeriod.ALL`) as the primary default** across `sample()`, `BrazilianNameSampler.from_parquet()`, and `ptbr generate`, with `--census-year 2010` / `census_year=2010` documented as an explicit historical opt-in.
  - Document the **slim-wheel + Hugging Face runtime dataset architecture**: `< 150 KiB` PyPI wheel bundling only `ptbr_sampler/data/dataset_manifest.json`, lazy SHA-256-verified downloads from `arthrod/ptbr-sampler-data` into `~/.cache/ptbr-sampler/<hf_revision>/`, offline/Docker pre-warming via `ptbr datasets prefetch --census-year 2022`, and environment controls (`PTBR_SAMPLER_CACHE_DIR`, `PTBR_SAMPLER_DATA_DIR`, `PTBR_SAMPLER_HF_REPO`, `PTBR_SAMPLER_OFFLINE`).
  - Document `--conditioning-mode strict|estimated`, `--uf-conditioning`, the 10-year endpoint-vs-start cohort convention, surname slot probability ($q_{\text{Silva}} = 10.20\%$) vs person-level presence ($16.76\%$), and mixed reference dates (`2022` names vs `2024` geography).
- Update `docs/handoff-fetch-and-ingest.md`, `docs/handoff-resume-with-claude.md`, and `todo.md` so ordinary reruns validate cached files and skip valid ones while `--overwrite` refetches, removing stale `0.2.x` claims and replacing handoff checklists with concrete manifest hashes, status counts, HF publish/prefetch commands, and remaining assumptions.

- [ ] **Step 3: Verify links, CLI flag alignment, and lint checks, then commit Task 2**

Run: `uv run --extra dev ruff check /home/arthrod/workspace/ptbr-sampler`
Expected: `All checks passed!`

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  THIRD_PARTY_NOTICES.md \
  README.md README.en.md todo.md \
  docs/architecture.md docs/data-origins.md \
  docs/handoff-fetch-and-ingest.md docs/handoff-resume-with-claude.md \
  docs/sources/
git -C /home/arthrod/workspace/ptbr-sampler commit -m "docs: reconcile Census 2022 availability, censoring math, and provenance notices"
```

---

### Task 3: Reproducible Census 2022 Acquisition & Float64 Atomic Parquet Ingestion

**Files:**
- Modify: `scripts/download_datasets.py`
- Modify: `scripts/ingest_to_parquet.py`
- Modify: `.gitignore`
- Modify: `tests/test_dataset_scripts.py`

- [ ] **Step 1: Write failing tests for pinned 2022 downloads, retries, cache verification, and float64 ingestion**

Extend `tests/test_dataset_scripts.py` with mocked-network and fixture tests:

```python
def test_fetch_ibge_2022_verifies_sha256_and_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = b'PAR1mockparquetbytesPAR1'
    digest = hashlib.sha256(payload).hexdigest()
    spec = download_datasets.PinnedParquetSpec(
        filename='state.parquet',
        sha256=digest,
        size_bytes=len(payload),
        expected_rows=1,
        required_columns=('code', 'abbreviation', 'population'),
    )
    monkeypatch.setattr(download_datasets, 'IBGE_2022_FILES', (spec,))
    monkeypatch.setattr(download_datasets, '_validate_parquet_schema_and_rows', lambda path, s: 1)
    monkeypatch.setattr(download_datasets, '_stream_https_bytes', lambda url, dest, **kw: dest.write_bytes(payload))

    manifest_path = download_datasets.fetch_ibge_2022(out_dir=tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['revision'] == download_datasets.IBGE_2022_REVISION
    assert manifest['files']['state.parquet']['sha256'] == digest
    assert 'fetched_at_utc' in manifest['files']['state.parquet']


def test_fetch_ibge_2022_rejects_checksum_mismatch_and_leaves_no_partial_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = download_datasets.PinnedParquetSpec(
        filename='state.parquet',
        sha256='0' * 64,
        size_bytes=4,
        expected_rows=1,
        required_columns=('code',),
    )
    monkeypatch.setattr(download_datasets, 'IBGE_2022_FILES', (spec,))
    monkeypatch.setattr(download_datasets, '_stream_https_bytes', lambda url, dest, **kw: dest.write_bytes(b'bad!'))

    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        download_datasets.fetch_ibge_2022(out_dir=tmp_path)
    assert not (tmp_path / 'state.parquet').exists()
    assert not list(tmp_path.glob('*.part'))


def test_fetch_ibge_2022_reuses_valid_cache_and_replaces_corrupt_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    good = b'valid-parquet-bytes'
    digest = hashlib.sha256(good).hexdigest()
    spec = download_datasets.PinnedParquetSpec('state.parquet', digest, len(good), 1, ('code',))
    monkeypatch.setattr(download_datasets, 'IBGE_2022_FILES', (spec,))
    monkeypatch.setattr(download_datasets, '_validate_parquet_schema_and_rows', lambda path, s: 1)

    calls = 0

    def fake_stream(url: str, dest: Path, **kw: object) -> None:
        nonlocal calls
        calls += 1
        dest.write_bytes(good)

    monkeypatch.setattr(download_datasets, '_stream_https_bytes', fake_stream)

    # Corrupt existing file must be detected and refetched automatically
    (tmp_path / 'state.parquet').write_bytes(b'corrupted')
    download_datasets.fetch_ibge_2022(out_dir=tmp_path, overwrite=False)
    assert calls == 1

    # Second call with valid file on disk skips network completely
    download_datasets.fetch_ibge_2022(out_dir=tmp_path, overwrite=False)
    assert calls == 1


def test_retry_helper_retries_429_and_503_but_fails_fast_on_404():
    attempts = 0

    def transient_then_ok() -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.HTTPError('https://huggingface.co/x', 503, 'Service Unavailable', hdrs=None, fp=None)
        return b'ok'

    assert download_datasets._with_bounded_retries(transient_then_ok, max_attempts=3, base_sleep=0.0) == b'ok'
    assert attempts == 3

    def permanent_404() -> bytes:
        raise urllib.error.HTTPError('https://huggingface.co/x', 404, 'Not Found', hdrs=None, fp=None)

    with pytest.raises(urllib.error.HTTPError):
        download_datasets._with_bounded_retries(permanent_404, max_attempts=3, base_sleep=0.0)


def test_merge_sex_prior_never_fabricates_unit_counts_for_gemini(tmp_path: Path):
    from scripts import ingest_to_parquet

    csv_path = tmp_path / 'nomes.csv'
    csv_path.write_text('first_name,frequency_male,frequency_female,frequency_total,ratio,classification,alternative_names\nANA,10,990,1000,0.99,F,\n', encoding='utf-8')
    gemini_path = tmp_path / 'classifications.jsonl'
    gemini_path.write_text('{"name": "ZORBLAX", "gender": "M", "model": "gemini-test"}\n', encoding='utf-8')

    merged, counts = ingest_to_parquet._merge_sex_prior(csv_path, gemini_path)
    assert counts['gemini_M'] == 1
    assert merged['ZORBLAX']['count_male'] == 0
    assert merged['ZORBLAX']['count_female'] == 0
    assert merged['ZORBLAX']['count_total'] == 0
    assert merged['ZORBLAX']['p_male'] == 1.0
```

- [ ] **Step 2: Run the new script tests to confirm failure**

Run: `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_dataset_scripts.py -v`
Expected: `FAIL` with `AttributeError: module 'scripts.download_datasets' has no attribute 'PinnedParquetSpec'`.

- [ ] **Step 3: Implement pinned `--fetch-ibge-2022` downloader with redirect allowlist, retries, and `source_manifest.json`**

Update `scripts/download_datasets.py` with the pinned specification, redirect allowlist, bounded retry wrapper, cache validation, and `source_manifest.json` writer:

```python
IBGE_2022_REPO = 'olob0/ibge-nomes-no-brasil-2022'
IBGE_2022_REVISION = '05efb85c92af43da2ed4ed088d1e0c9f17160e65'
_ALLOWED_HF_HOST_SUFFIXES = ('huggingface.co', '.huggingface.co', '.hf.co')


@dataclass(slots=True, frozen=True)
class PinnedParquetSpec:
    filename: str
    sha256: str
    size_bytes: int
    expected_rows: int
    required_columns: tuple[str, ...]


IBGE_2022_FILES: tuple[PinnedParquetSpec, ...] = (
    PinnedParquetSpec(
        filename='name_ranking.parquet',
        sha256='635691d3ce52eb59c242ecb886dbaab62b4b42e6bed4b4f1766f8c6725636c64',
        size_bytes=1_738_567,
        expected_rows=330_059,
        required_columns=('name_text', 'name_type', 'frequency', 'percentage', 'rank'),
    ),
    PinnedParquetSpec(
        filename='name_detail.parquet',
        sha256='91518f2d0d1da8e438ab9f557127da06633e186914aecb717f1bbf7bfb6b2943',
        size_bytes=2_250_879,
        expected_rows=330_058,
        required_columns=('name_text', 'name_type', 'letter_rank', 'male_count', 'female_count', 'median_age'),
    ),
    PinnedParquetSpec(
        filename='name_by_decade.parquet',
        sha256='9f852814bf42a47358841c054a70939c763c4fc70c7e38564ad44fb94b7fbdef',
        size_bytes=910_784,
        expected_rows=221_524,
        required_columns=('name_text', 'name_type', 'decade', 'frequency'),
    ),
    PinnedParquetSpec(
        filename='name_by_state.parquet',
        sha256='5588f012d43bb38b07691044010eb7e96cb2bfc359dd3b53a6c3b0ea46f1504e',
        size_bytes=3_729_128,
        expected_rows=828_567,
        required_columns=('name_text', 'name_type', 'state_code', 'frequency', 'percentage'),
    ),
    PinnedParquetSpec(
        filename='state.parquet',
        sha256='5d4aa2a4faf4cdef421f2563de63cd8298b58113779774045a29b9e13ddebc55',
        size_bytes=1_285,
        expected_rows=27,
        required_columns=('code', 'abbreviation', 'name', 'region_code', 'population'),
    ),
)


def _assert_allowed_https_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not any(
        host == sfx.lstrip('.') or host.endswith(sfx) for sfx in _ALLOWED_HF_HOST_SUFFIXES
    ):
        raise RuntimeError(f'Blocked redirect or fetch outside allowlisted HTTPS hosts: {url!r}')


class _AllowedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _assert_allowed_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _with_bounded_retries(fn, *, max_attempts: int = 4, base_sleep: float = 1.0):
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except urllib.error.HTTPError as err:
            retryable = err.code in {429, 500, 502, 503, 504}
            if not retryable or attempt >= max_attempts:
                raise
            retry_after = err.headers.get('Retry-After') if err.headers is not None else None
            delay = min(float(retry_after), 30.0) if (retry_after and retry_after.isdigit()) else base_sleep * (2 ** (attempt - 1))
            time.sleep(delay)
        except (TimeoutError, urllib.error.URLError):
            if attempt >= max_attempts:
                raise
            time.sleep(base_sleep * (2 ** (attempt - 1)))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _validate_parquet_schema_and_rows(path: Path, spec: PinnedParquetSpec) -> int:
    import pyarrow.parquet as pq  # noqa: PLC0415

    meta = pq.read_metadata(path)
    schema_names = set(pq.read_schema(path).names)
    missing = set(spec.required_columns) - schema_names
    if missing:
        raise RuntimeError(f'{spec.filename}: missing required columns {sorted(missing)}')
    if meta.num_rows != spec.expected_rows:
        raise RuntimeError(f'{spec.filename}: expected {spec.expected_rows} rows, got {meta.num_rows}')
    return int(meta.num_rows)


def _stream_https_bytes(url: str, dest: Path, *, timeout: float = 60.0) -> None:
    _assert_allowed_https_url(url)
    opener = urllib.request.build_opener(_AllowedRedirectHandler())
    req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
    with opener.open(req, timeout=timeout) as resp, dest.open('wb') as out:
        while chunk := resp.read(1 << 18):
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())


def fetch_ibge_2022(*, out_dir: Path | None = None, overwrite: bool = False) -> Path:
    target_dir = out_dir or (_RAW_ROOT / 'ibge_nomes_2022')
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / 'source_manifest.json'
    prior_files: dict[str, dict[str, object]] = {}
    if manifest_path.exists():
        prior_files = json.loads(manifest_path.read_text(encoding='utf-8')).get('files', {})

    recorded: dict[str, dict[str, object]] = {}
    for spec in IBGE_2022_FILES:
        final_path = target_dir / spec.filename
        url = (
            f'https://huggingface.co/datasets/{IBGE_2022_REPO}/resolve/'
            f'{IBGE_2022_REVISION}/data/{spec.filename}'
        )
        cache_valid = False
        if not overwrite and final_path.exists() and final_path.stat().st_size == spec.size_bytes:
            if _sha256_file(final_path) == spec.sha256:
                try:
                    _validate_parquet_schema_and_rows(final_path, spec)
                    cache_valid = True
                except Exception:
                    cache_valid = False

        if not cache_valid:
            part_path = target_dir / f'{spec.filename}.part'
            part_path.unlink(missing_ok=True)
            try:
                _with_bounded_retries(lambda u=url, p=part_path: _stream_https_bytes(u, p))
                actual_sha = _sha256_file(part_path)
                if actual_sha != spec.sha256:
                    raise RuntimeError(
                        f'SHA-256 mismatch for {spec.filename}: expected {spec.sha256}, got {actual_sha}'
                    )
                _validate_parquet_schema_and_rows(part_path, spec)
                part_path.replace(final_path)
            except Exception:
                part_path.unlink(missing_ok=True)
                raise
            fetched_ts = datetime.now(UTC).isoformat()
        else:
            fetched_ts = str(prior_files.get(spec.filename, {}).get('fetched_at_utc') or datetime.now(UTC).isoformat())

        recorded[spec.filename] = {
            'url': url,
            'sha256': spec.sha256,
            'size_bytes': spec.size_bytes,
            'rows': spec.expected_rows,
            'fetched_at_utc': fetched_ts,
        }

    manifest = {
        'dataset': IBGE_2022_REPO,
        'revision': IBGE_2022_REVISION,
        'primary_authority': 'IBGE Censo Demográfico 2022 — Nomes no Brasil',
        'compilation_attribution': 'Gabriel Lobo (olob0/ibge-nomes-no-brasil-2022 on Hugging Face)',
        'files': recorded,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest_path
```

Wire `--fetch-ibge-2022` into `download_datasets.main()` and return exit code `1` whenever any requested `--fetch-*` target fails or remains missing.

- [ ] **Step 4: Upgrade `scripts/ingest_to_parquet.py` to `float64`, `math.fsum`, atomic staging, and `ingest_ibge_2022`**

Update `scripts/ingest_to_parquet.py` with `float64` schemas, `math.fsum` normalization, Gemini `count=0` metadata cleanup, and atomic `ingest_ibge_2022`:

```python
CENSUS_2022_DECADE_TO_PERIOD: dict[int, str] = {
    1930: 'ate1940',
    1940: 'ate1950',
    1950: 'ate1960',
    1960: 'ate1970',
    1970: 'ate1980',
    1980: 'ate1990',
    1990: 'ate2000',
    2000: 'ate2010',
    2010: 'ate2020',
    2020: '2020_2022',
}

_SCHEMA = pa.schema(
    [
        ('name', pa.string()),
        ('count', pa.int64()),
        ('weight', pa.float64()),
    ]
)

_SEX_PRIOR_SCHEMA = pa.schema(
    [
        ('name', pa.string()),
        ('count_male', pa.int64()),
        ('count_female', pa.int64()),
        ('count_total', pa.int64()),
        ('p_male', pa.float64()),
        ('p_female', pa.float64()),
        ('classification', pa.string()),
        ('source', pa.string()),
    ]
)

_SEX_PRIOR_2022_SCHEMA = pa.schema(
    [
        ('name', pa.string()),
        ('canonical_key', pa.string()),
        ('count_total', pa.int64()),
        ('count_male', pa.int64()),      # nullable: None when IBGE suppressed (<20)
        ('count_female', pa.int64()),    # nullable: None when IBGE suppressed (<20)
        ('residual_unassigned', pa.int64()),
        ('p_male', pa.float64()),        # NaN when male cell suppressed with positive residual
        ('p_female', pa.float64()),      # NaN when female cell suppressed with positive residual
        ('censoring_regime', pa.string()),
    ]
)


def _normalise(entries: list[tuple[str, int, float]]) -> tuple[list[str], list[int], list[float]]:
    filtered = [(name, c, w) for name, c, w in entries if w > 0 and math.isfinite(w)]
    if not filtered:
        raise ValueError('partition has no positive-weight entries')
    total = math.fsum(w for _, _, w in filtered)
    names = [name for name, _, _ in filtered]
    counts = [int(c) for _, c, _ in filtered]
    weights = [float(w) / total for _, _, w in filtered]
    return names, counts, weights


# In _merge_sex_prior(csv_path, gemini_path): keep count_male=0, count_female=0, count_total=0 for LLM rows:
# if gender == 'M':
#     out[key] = {'count_male': 0, 'count_female': 0, 'count_total': 0, 'p_male': 1.0, 'p_female': 0.0, ...}
# elif gender == 'F':
#     out[key] = {'count_male': 0, 'count_female': 0, 'count_total': 0, 'p_male': 0.0, 'p_female': 1.0, ...}


def _write_count_partition_2022(
    rows: list[tuple[str, int]],
    dest_dir: Path,
    *,
    origin_meta: dict[str, Any],
) -> None:
    # Canonical deterministic order: descending count, then ascending display name
    ordered = sorted(rows, key=lambda kv: (-kv[1], kv[0]))
    names, counts, weights = _normalise([(n, c, float(c)) for n, c in ordered])
    dest_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({'name': names, 'count': counts, 'weight': weights}, schema=_SCHEMA),
        dest_dir / 'part.parquet',
        compression='zstd',
    )
    sidecar = {
        **origin_meta,
        'rows': len(names),
        'count_sum': int(sum(counts)),
        'weight_sum': math.fsum(weights),
        'built_at_utc': datetime.now(UTC).isoformat(),
    }
    (dest_dir / 'data_origin.json').write_text(json.dumps(sidecar, indent=2) + '\n', encoding='utf-8')


def ingest_ibge_2022(raw_dir: Path, out_root: Path) -> dict[str, Any]:
    """Ingest pinned IBGE Census 2022 tables into ``out_root / 'census_year=2022'`` atomically."""
    from scripts.audit_datasets import (  # noqa: PLC0415
        audit_ibge_2022_tables,
        classify_sex_censoring,
        format_census_2022_display_name,
    )

    audit = audit_ibge_2022_tables(raw_dir)
    manifest_path = raw_dir / 'source_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}

    staging = out_root / '.tmp_census_year=2022'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        ranking = pq.read_table(raw_dir / 'name_ranking.parquet')
        detail = pq.read_table(raw_dir / 'name_detail.parquet')
        by_decade = pq.read_table(raw_dir / 'name_by_decade.parquet')
        by_state = pq.read_table(raw_dir / 'name_by_state.parquet')
        states = pq.read_table(raw_dir / 'state.parquet')

        base_meta = {
            'census_year': 2022,
            'reference_date': '2022-08-01',
            'dataset': manifest.get('dataset', 'olob0/ibge-nomes-no-brasil-2022'),
            'revision': manifest.get('revision', '05efb85c92af43da2ed4ed088d1e0c9f17160e65'),
        }

        given_nat: list[tuple[str, int]] = []
        surname_nat: list[tuple[str, int]] = []
        given_total_by_key: dict[str, int] = {}
        for name_text, name_type, freq in zip(
            ranking['name_text'].to_pylist(),
            ranking['name_type'].to_pylist(),
            ranking['frequency'].to_pylist(),
            strict=True,
        ):
            disp = format_census_2022_display_name(str(name_text))
            cnt = int(freq)
            if name_type == 'given':
                given_nat.append((disp, cnt))
                given_total_by_key[str(name_text)] = cnt
            elif name_type == 'surname':
                surname_nat.append((disp, cnt))

        _write_count_partition_2022(
            given_nat,
            staging / 'first_names' / 'scope=national',
            origin_meta={**base_meta, 'grain': 'national_given', 'disclosure_threshold': 20},
        )
        _write_count_partition_2022(
            surname_nat,
            staging / 'surnames' / 'scope=national',
            origin_meta={**base_meta, 'grain': 'national_surname_token_slots', 'disclosure_threshold': 20},
        )

        # Sex tables & nullable sex_prior with exact national marginal coherence
        sex_m_rows: list[tuple[str, int]] = []
        sex_f_rows: list[tuple[str, int]] = []
        prior_cols: dict[str, list[Any]] = {k: [] for k in _SEX_PRIOR_2022_SCHEMA.names}

        for name_text, name_type, male, female in zip(
            detail['name_text'].to_pylist(),
            detail['name_type'].to_pylist(),
            detail['male_count'].to_pylist(),
            detail['female_count'].to_pylist(),
            strict=True,
        ):
            if name_type != 'given':
                continue
            key = str(name_text)
            disp = format_census_2022_display_name(key)
            total = given_total_by_key[key]
            m_val = None if male is None else int(male)
            f_val = None if female is None else int(female)
            regime = classify_sex_censoring(total=total, male=m_val, female=f_val)

            if m_val is not None:
                sex_m_rows.append((disp, m_val))
            if f_val is not None:
                sex_f_rows.append((disp, f_val))

            if regime == 'both_observed':
                assert m_val is not None and f_val is not None
                p_m, p_f, residual = m_val / total, f_val / total, 0
            elif regime == 'one_null_exact_zero':
                residual = 0
                p_m = 1.0 if m_val is not None else 0.0
                p_f = 1.0 if f_val is not None else 0.0
            elif regime == 'one_null_suppressed_positive':
                obs_val = m_val if m_val is not None else (f_val or 0)
                residual = total - obs_val
                # Exact observed rate N_{i,obs}/N_i (< 1.0); suppressed cell stays NaN (excluded)
                p_m = (m_val / total) if m_val is not None else math.nan
                p_f = (f_val / total) if f_val is not None else math.nan
            else:
                residual = total
                p_m, p_f = math.nan, math.nan

            prior_cols['name'].append(disp)
            prior_cols['canonical_key'].append(key)
            prior_cols['count_total'].append(total)
            prior_cols['count_male'].append(m_val)
            prior_cols['count_female'].append(f_val)
            prior_cols['residual_unassigned'].append(residual)
            prior_cols['p_male'].append(p_m)
            prior_cols['p_female'].append(p_f)
            prior_cols['censoring_regime'].append(regime)

        _write_count_partition_2022(
            sex_m_rows,
            staging / 'first_names' / 'sex=M',
            origin_meta={
                **base_meta,
                'grain': 'national_given_sex_observed',
                'sex': 'M',
                'observed_male_mass': audit['censoring'].observed_male_mass,
                'observed_female_mass': audit['censoring'].observed_female_mass,
            },
        )
        _write_count_partition_2022(
            sex_f_rows,
            staging / 'first_names' / 'sex=F',
            origin_meta={
                **base_meta,
                'grain': 'national_given_sex_observed',
                'sex': 'F',
                'observed_male_mass': audit['censoring'].observed_male_mass,
                'observed_female_mass': audit['censoring'].observed_female_mass,
            },
        )

        sex_prior_dir = staging / 'sex_prior' / 'scope=national'
        sex_prior_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table(prior_cols, schema=_SEX_PRIOR_2022_SCHEMA),
            sex_prior_dir / 'part.parquet',
            compression='zstd',
        )

        # Birth-cohort survivor partitions (10 cohorts)
        decade_buckets: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for name_text, name_type, dec, freq in zip(
            by_decade['name_text'].to_pylist(),
            by_decade['name_type'].to_pylist(),
            by_decade['decade'].to_pylist(),
            by_decade['frequency'].to_pylist(),
            strict=True,
        ):
            if name_type == 'given':
                decade_buckets[int(dec)].append((format_census_2022_display_name(str(name_text)), int(freq)))

        for dec, period_key in CENSUS_2022_DECADE_TO_PERIOD.items():
            _write_count_partition_2022(
                decade_buckets[dec],
                staging / 'first_names' / f'period={period_key}',
                origin_meta={**base_meta, 'grain': 'national_birth_cohort_survivors', 'olob0_decade': dec, 'period': period_key},
            )

        # UF partitions (27 given + 27 surname) and states table
        code_to_uf = dict(zip(states['code'].to_pylist(), states['abbreviation'].to_pylist(), strict=True))
        code_to_pop = dict(zip(states['code'].to_pylist(), states['population'].to_pylist(), strict=True))
        uf_given: dict[str, list[tuple[str, int]]] = defaultdict(list)
        uf_surname: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for name_text, name_type, scode, freq in zip(
            by_state['name_text'].to_pylist(),
            by_state['name_type'].to_pylist(),
            by_state['state_code'].to_pylist(),
            by_state['frequency'].to_pylist(),
            strict=True,
        ):
            uf = str(code_to_uf[int(scode)])
            disp = format_census_2022_display_name(str(name_text))
            if name_type == 'given':
                uf_given[uf].append((disp, int(freq)))
            elif name_type == 'surname':
                uf_surname[uf].append((disp, int(freq)))

        uf_to_pop = {str(code_to_uf[c]): int(p) for c, p in code_to_pop.items()}
        for uf, pop_u in sorted(uf_to_pop.items()):
            _write_count_partition_2022(
                uf_given[uf],
                staging / 'first_names' / f'uf={uf}',
                origin_meta={**base_meta, 'grain': 'uf_given', 'uf': uf, 'uf_population_2022': pop_u, 'disclosure_threshold': 15},
            )
            _write_count_partition_2022(
                uf_surname[uf],
                staging / 'surnames' / f'uf={uf}',
                origin_meta={**base_meta, 'grain': 'uf_surname_token_slots', 'uf': uf, 'uf_population_2022': pop_u, 'disclosure_threshold': 15},
            )

        states_dir = staging / 'states'
        states_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(states, states_dir / 'part.parquet', compression='zstd')

        final_dest = out_root / 'census_year=2022'
        backup_dest = out_root / '.bak_census_year=2022'
        if backup_dest.exists():
            shutil.rmtree(backup_dest)
        if final_dest.exists():
            final_dest.replace(backup_dest)
        staging.replace(final_dest)
        if backup_dest.exists():
            shutil.rmtree(backup_dest)
        return audit
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
```

- [ ] **Step 5: Update `.gitignore`, fetch pinned Census 2022 raw files, build `parquet/census_year=2022/`, run tests, and commit Task 3**

In `.gitignore`, add `ptbr_sampler/data/raw/ibge_nomes_2022/*.parquet` and `ptbr_sampler/data/raw/ibge_nomes_2022/*.part` so `source_manifest.json` stays tracked in Git while raw `8.23 MiB` upstream staging Parquets are reproducible via `python -m scripts.download_datasets --fetch-ibge-2022`. Also update the user-agent string in `scripts/download_datasets.py` to `'ptbr-sampler/0.3.0 (+https://github.com/jandira-tech/ptbr-sampler)'`.

Run:
1. `uv run python -m scripts.download_datasets --fetch-ibge-2022`
2. `uv run python -m scripts.ingest_to_parquet`
3. `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_dataset_scripts.py -v`
Expected: `5` raw Parquet files verified, `parquet/census_year=2022/` built cleanly (`< 13 MiB` on disk), and all tests `PASS`.

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  .gitignore \
  scripts/download_datasets.py scripts/ingest_to_parquet.py \
  ptbr_sampler/data/raw/ibge_nomes_2022/source_manifest.json \
  ptbr_sampler/data/parquet/ \
  tests/test_dataset_scripts.py
git -C /home/arthrod/workspace/ptbr-sampler commit -m "feat: add reproducible Census 2022 download and float64 Parquet ingestion"
```

---

### Task 4: Runtime Hugging Face Dataset Delivery, Manifest Publisher, Version Bump to `0.3.0`, and `< 150 KiB` Ultra-Slim Wheel

**Files:**
- Modify: `pyproject.toml`
- Modify: `ptbr_sampler/__init__.py`
- Create: `ptbr_sampler/datasets.py`
- Create: `scripts/publish_hf_dataset.py`
- Create: `ptbr_sampler/data/dataset_manifest.json`
- Modify: `ptbr_sampler/sampling/store.py`
- Modify: `ptbr_sampler/data_origins.py`
- Create: `tests/test_runtime_datasets.py`
- Modify: `tests/test_data_origins.py`

- [ ] **Step 1: Write failing unit & local-HTTP integration tests for `0.3.0` version, manifest generation, runtime HF download/cache/locking, cross-origin token stripping, and `PartitionStore` lazy fetch**

Create `tests/test_runtime_datasets.py` and update `tests/test_data_origins.py`:

```python
"""Tests for runtime Hugging Face dataset resolution, caching, SHA-256 verification, and manifest publishing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import ptbr_sampler
from ptbr_sampler import datasets as ds_mod
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore
from scripts import publish_hf_dataset


def _write_mini_parquet(path: Path, names: list[str], counts: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tot = float(sum(counts))
    pq.write_table(
        pa.table(
            {
                'name': pa.array(names, type=pa.string()),
                'count': pa.array(counts, type=pa.int64()),
                'weight': pa.array([c / tot for c in counts], type=pa.float64()),
            }
        ),
        path,
        compression='zstd',
    )


def test_package_version_is_0_3_0():
    assert ptbr_sampler.__version__ == '0.3.0'


def test_publish_manifest_builder_collects_runtime_artifacts_and_excludes_raw_and_backups(tmp_path: Path):
    data_dir = tmp_path / 'data'
    _write_mini_parquet(
        data_dir / 'parquet' / 'census_year=2022' / 'first_names' / 'scope=national' / 'part.parquet',
        ['Maria', 'Joao'],
        [60, 40],
    )
    (data_dir / 'middle_names.json').write_text('{"common_middle_names": ["Maria"]}\n', encoding='utf-8')
    (data_dir / 'raw' / 'ibge_nomes_2022').mkdir(parents=True)
    (data_dir / 'raw' / 'ibge_nomes_2022' / 'state.parquet').write_bytes(b'ignored')
    (data_dir / 'locations_data.bak.json').write_text('{}', encoding='utf-8')

    manifest_path = publish_hf_dataset.write_dataset_manifest(
        data_dir,
        repo_id='arthrod/ptbr-sampler-data',
        revision='a' * 40,
    )
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['package_version'] == '0.3.0'
    assert manifest['hf_repo_id'] == 'arthrod/ptbr-sampler-data'
    assert manifest['hf_revision'] == 'a' * 40
    assert 'parquet/census_year=2022/first_names/scope=national/part.parquet' in manifest['artifacts']
    assert 'middle_names.json' in manifest['artifacts']
    assert not any(k.startswith('raw/') or '.bak' in k for k in manifest['artifacts'])


def test_ensure_data_file_downloads_lazily_verifies_sha256_and_reuses_cache_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    remote_root = tmp_path / 'remote'
    rel = 'parquet/census_year=2022/first_names/scope=national/part.parquet'
    src_file = remote_root / rel
    _write_mini_parquet(src_file, ['Maria', 'Ana'], [70, 30])
    payload = src_file.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    rev = 'b' * 40

    manifest_file = tmp_path / 'dataset_manifest.json'
    manifest_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'package_version': '0.3.0',
                'hf_repo_id': 'arthrod/ptbr-sampler-data',
                'hf_revision': rev,
                'artifacts': {
                    rel: {'sha256': digest, 'size_bytes': len(payload), 'census_years': [2022]},
                },
            }
        ),
        encoding='utf-8',
    )

    request_count = 0
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal request_count
            expected_path = f'/datasets/arthrod/ptbr-sampler-data/resolve/{rev}/{rel}'
            if self.path != expected_path:
                self.send_response(404)
                self.end_headers()
                return
            with lock:
                request_count += 1
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cache_dir = tmp_path / 'cache'
        monkeypatch.setattr(ds_mod, 'MANIFEST_PATH', manifest_file)
        ds_mod.load_dataset_manifest.cache_clear()
        monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(cache_dir))
        monkeypatch.setenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', '1')
        monkeypatch.setenv('PTBR_SAMPLER_HF_BASE_URL', f'http://127.0.0.1:{server.server_port}')

        # Concurrent cold downloads must serialize on the advisory lock and hit HTTP once:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: ds_mod.ensure_data_file(rel), range(6)))

        assert all(p == results[0] and p.is_file() for p in results)
        assert request_count == 1

        # PartitionStore with resolve_partition_path loads lazily from the cache root:
        store = PartitionStore(path_resolver=ds_mod.resolve_partition_path)
        p_root = ds_mod.ensure_parquet_root(census_year=2022)
        table = store.get(PartitionSpec.of(p_root / 'first_names', scope='national'))
        assert list(table.labels) == ['Maria', 'Ana']
        assert request_count == 1
    finally:
        server.shutdown()
        ds_mod.load_dataset_manifest.cache_clear()


def test_ensure_data_file_rejects_sha256_mismatch_and_offline_cache_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rel = 'middle_names.json'
    rev = 'c' * 40
    manifest_file = tmp_path / 'dataset_manifest.json'
    manifest_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'package_version': '0.3.0',
                'hf_repo_id': 'arthrod/ptbr-sampler-data',
                'hf_revision': rev,
                'artifacts': {
                    rel: {'sha256': '0' * 64, 'size_bytes': 12, 'census_years': [2010, 2022]},
                },
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(ds_mod, 'MANIFEST_PATH', manifest_file)
    ds_mod.load_dataset_manifest.cache_clear()
    monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', '1')

    monkeypatch.setenv('PTBR_SAMPLER_OFFLINE', '1')
    with pytest.raises(RuntimeError, match='PTBR_SAMPLER_OFFLINE=1'):
        ds_mod.ensure_data_file(rel)

    monkeypatch.delenv('PTBR_SAMPLER_OFFLINE')
    monkeypatch.setattr(ds_mod, '_download_url_to_part', lambda url, part_path, **kw: (part_path.write_bytes(b'tampered1234'), 'f' * 64, 12)[1:])
    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        ds_mod.ensure_data_file(rel)
    ds_mod.load_dataset_manifest.cache_clear()


def test_redirect_handler_strips_authorization_header_on_cross_origin_cdn_redirect():
    handler = ds_mod._CrossOriginSafeRedirectHandler(allow_loopback_http=False)
    req = urllib.request.Request(
        'https://huggingface.co/datasets/arthrod/ptbr-sampler-data/resolve/main/middle_names.json',
        headers={'Authorization': 'Bearer hf_secret_token', 'User-Agent': 'ptbr-sampler/0.3.0'},
    )
    redirected = handler.redirect_request(
        req,
        fp=None,
        code=302,
        msg='Found',
        headers={},
        newurl='https://cas-bridge.xethub.hf.co/xet-bridge-us/signed-blob',
    )
    assert redirected is not None
    assert not redirected.has_header('Authorization')
    assert 'authorization' not in {k.lower() for k in redirected.unredirected_hdrs}
```

- [ ] **Step 2: Run the new runtime dataset tests to confirm failure**

Run: `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_runtime_datasets.py -v`
Expected: `FAIL` with `ImportError: cannot import name 'datasets' from 'ptbr_sampler'`.

- [ ] **Step 3: Implement `ptbr_sampler/datasets.py`, update `PartitionStore` for lazy resolution, and bump package version to `0.3.0`**

Update `ptbr_sampler/__init__.py` (`__version__ = '0.3.0'`) and `pyproject.toml`:

```toml
[project]
name = 'ptbr-sampler'
version = '0.3.0'
```

Add `'huggingface-hub>=0.26'` under `[project.optional-dependencies].dev` (keeping runtime `[project].dependencies` unchanged) and configure `[tool.uv.build-backend]` so **only** `ptbr_sampler/data/dataset_manifest.json` ships in `ptbr_sampler/data/` inside the wheel and sdist:

```toml
[tool.uv.build-backend]
module-name = 'ptbr_sampler'
module-root = ''
wheel-exclude = [
    'ptbr_sampler/data/parquet/**',
    'ptbr_sampler/data/raw/**',
    'ptbr_sampler/data/cities_with_ceps.json',
    'ptbr_sampler/data/locations_data*.json*',
    'ptbr_sampler/data/names_data.json',
    'ptbr_sampler/data/surnames_data.json',
    'ptbr_sampler/data/middle_names.json',
    'ptbr_sampler/tests/**',
]
source-exclude = [
    'ptbr_sampler/data/parquet/**',
    'ptbr_sampler/data/raw/**',
    'ptbr_sampler/data/cities_with_ceps.json',
    'ptbr_sampler/data/locations_data*.json*',
    'ptbr_sampler/data/names_data.json',
    'ptbr_sampler/data/surnames_data.json',
    'ptbr_sampler/data/middle_names.json',
]
```

Create `ptbr_sampler/datasets.py`:

```python
"""Runtime Hugging Face dataset resolver, SHA-256 verifier, and revision-addressed cache."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

PACKAGE_DATA_DIR: Path = Path(__file__).resolve().parent / 'data'
MANIFEST_PATH: Path = PACKAGE_DATA_DIR / 'dataset_manifest.json'
DEFAULT_HF_REPO_ID: str = 'arthrod/ptbr-sampler-data'
DEFAULT_HF_BASE_URL: str = 'https://huggingface.co'
USER_AGENT: str = 'ptbr-sampler/0.3.0 (+https://github.com/jandira-tech/ptbr-sampler)'
_ALLOWED_HF_HOST_SUFFIXES: tuple[str, ...] = ('huggingface.co', '.huggingface.co', '.hf.co')
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.Lock] = {}


@dataclass(slots=True, frozen=True)
class ArtifactEntry:
    relpath: str
    sha256: str
    size_bytes: int
    census_years: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class DatasetManifest:
    schema_version: int
    package_version: str
    hf_repo_id: str
    hf_revision: str
    artifacts: dict[str, ArtifactEntry]


def _normalize_relpath(relpath: str | Path) -> str:
    raw = str(relpath).replace('\\', '/').strip()
    while raw.startswith('./'):
        raw = raw[2:]
    if not raw or raw.startswith('/'):
        raise ValueError(f'Invalid dataset relative path: {relpath!r}')
    posix = PurePosixPath(raw)
    if '..' in posix.parts:
        raise ValueError(f'Path traversal rejected in dataset path: {relpath!r}')
    return posix.as_posix()


@lru_cache(maxsize=1)
def load_dataset_manifest() -> DatasetManifest:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            f'Packaged dataset manifest missing at {MANIFEST_PATH}. '
            'Run `python -m scripts.publish_hf_dataset --manifest-only` in a source checkout.'
        )
    raw = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    artifacts: dict[str, ArtifactEntry] = {}
    for rel, meta in raw.get('artifacts', {}).items():
        norm = _normalize_relpath(rel)
        artifacts[norm] = ArtifactEntry(
            relpath=norm,
            sha256=str(meta['sha256']),
            size_bytes=int(meta['size_bytes']),
            census_years=tuple(int(y) for y in meta.get('census_years', (2010, 2022))),
        )
    return DatasetManifest(
        schema_version=int(raw.get('schema_version', 1)),
        package_version=str(raw.get('package_version', '0.3.0')),
        hf_repo_id=os.environ.get('PTBR_SAMPLER_HF_REPO') or str(raw['hf_repo_id']),
        hf_revision=os.environ.get('PTBR_SAMPLER_HF_REVISION') or str(raw['hf_revision']),
        artifacts=artifacts,
    )


def get_cache_root() -> Path:
    override = os.environ.get('PTBR_SAMPLER_CACHE_DIR')
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get('XDG_CACHE_HOME')
    base = Path(xdg).expanduser() if xdg else (Path.home() / '.cache')
    return (base / 'ptbr-sampler').resolve()


def get_revision_cache_dir(manifest: DatasetManifest | None = None) -> Path:
    mf = manifest or load_dataset_manifest()
    safe_rev = ''.join(ch for ch in mf.hf_revision if ch.isalnum() or ch in ('-', '_', '.'))
    if not safe_rev:
        raise ValueError(f'Invalid hf_revision: {mf.hf_revision!r}')
    return get_cache_root() / safe_rev


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def _artifact_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCKS_GUARD:
        tlock = _THREAD_LOCKS.setdefault(lock_path, threading.Lock())
    with tlock:
        if fcntl is None:
            yield
            return
        with lock_path.open('a+b') as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class _CrossOriginSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_loopback_http: bool = False) -> None:
        super().__init__()
        self._allow_loopback_http = allow_loopback_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        parsed_new = urllib.parse.urlsplit(newurl)
        host = (parsed_new.hostname or '').lower()
        if parsed_new.scheme == 'https':
            if not any(
                host == s.lstrip('.') or (s.startswith('.') and host.endswith(s))
                for s in _ALLOWED_HF_HOST_SUFFIXES
            ):
                raise urllib.error.URLError(f'Disallowed redirect host: {host!r}')
        elif self._allow_loopback_http and parsed_new.scheme == 'http' and host in {'127.0.0.1', 'localhost'}:
            pass
        else:
            raise urllib.error.URLError(f'Disallowed redirect URL scheme/host: {newurl!r}')

        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            parsed_orig = urllib.parse.urlsplit(req.full_url)
            if (parsed_orig.scheme, parsed_orig.netloc.lower()) != (parsed_new.scheme, parsed_new.netloc.lower()):
                for hdr_dict in (new_req.headers, new_req.unredirected_hdrs):
                    for key in [k for k in hdr_dict if k.lower() == 'authorization']:
                        del hdr_dict[key]
        return new_req


def _download_url_to_part(
    url: str,
    part_path: Path,
    *,
    allow_loopback_http: bool = False,
    timeout: float = 60.0,
) -> tuple[str, int]:
    headers = {'User-Agent': USER_AGENT}
    token = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
    parsed = urllib.parse.urlsplit(url)
    if token and (parsed.hostname or '').lower() == 'huggingface.co':
        headers['Authorization'] = f'Bearer {token}'

    opener = urllib.request.build_opener(
        _CrossOriginSafeRedirectHandler(allow_loopback_http=allow_loopback_http)
    )
    req = urllib.request.Request(url, headers=headers)
    h = hashlib.sha256()
    total = 0
    part_path.parent.mkdir(parents=True, exist_ok=True)
    with opener.open(req, timeout=timeout) as resp, part_path.open('wb') as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            total += len(chunk)
        out.flush()
        os.fsync(out.fileno())
    return h.hexdigest(), total


def _download_with_retries(
    url: str,
    part_path: Path,
    *,
    allow_loopback_http: bool = False,
    max_attempts: int = 4,
    base_sleep: float = 1.0,
) -> tuple[str, int]:
    for attempt in range(1, max_attempts + 1):
        part_path.unlink(missing_ok=True)
        try:
            return _download_url_to_part(url, part_path, allow_loopback_http=allow_loopback_http)
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_HTTP_CODES or attempt == max_attempts:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_attempts:
                raise
        if base_sleep > 0:
            time.sleep(base_sleep * (2 ** (attempt - 1)))
    raise RuntimeError('unreachable')


def ensure_data_file(relpath: str | Path, *, verify_sha256: bool = False) -> Path:
    """Resolve a runtime dataset file from override dir, local checkout, or verified HF cache."""
    rel = _normalize_relpath(relpath)

    env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
    if env_data_dir:
        override_file = (Path(env_data_dir).expanduser() / rel).resolve()
        if override_file.is_file():
            return override_file

    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1':
        local_file = PACKAGE_DATA_DIR / rel
        if local_file.is_file():
            return local_file

    manifest = load_dataset_manifest()
    if rel not in manifest.artifacts:
        raise FileNotFoundError(f'Dataset artifact {rel!r} is not registered in dataset_manifest.json')
    entry = manifest.artifacts[rel]
    rev_dir = get_revision_cache_dir(manifest)
    cache_file = rev_dir / rel

    if cache_file.is_file() and cache_file.stat().st_size == entry.size_bytes:
        if not verify_sha256 or _sha256_file(cache_file) == entry.sha256:
            return cache_file

    if os.environ.get('PTBR_SAMPLER_OFFLINE') == '1':
        raise RuntimeError(
            f'Dataset artifact {rel!r} is not cached at {cache_file} and PTBR_SAMPLER_OFFLINE=1. '
            'Pre-warm the cache with `ptbr datasets prefetch`.'
        )

    lock_name = rel.replace('/', '__') + '.lock'
    with _artifact_lock(rev_dir / '.locks' / lock_name):
        if cache_file.is_file() and cache_file.stat().st_size == entry.size_bytes:
            if _sha256_file(cache_file) == entry.sha256:
                return cache_file

        base_url = (os.environ.get('PTBR_SAMPLER_HF_BASE_URL') or DEFAULT_HF_BASE_URL).rstrip('/')
        parsed_base = urllib.parse.urlsplit(base_url)
        allow_loopback = parsed_base.scheme == 'http' and (parsed_base.hostname or '') in {'127.0.0.1', 'localhost'}
        if parsed_base.scheme != 'https' and not allow_loopback:
            raise ValueError(f'PTBR_SAMPLER_HF_BASE_URL must use https:// (got {base_url!r})')

        url = f'{base_url}/datasets/{manifest.hf_repo_id}/resolve/{manifest.hf_revision}/{rel}'
        part_path = cache_file.with_name(f'{cache_file.name}.{os.getpid()}.{threading.get_ident()}.part')
        try:
            digest, nbytes = _download_with_retries(url, part_path, allow_loopback_http=allow_loopback)
            if nbytes != entry.size_bytes:
                raise RuntimeError(
                    f'Byte-length mismatch for {rel}: expected {entry.size_bytes}, got {nbytes}'
                )
            if digest != entry.sha256:
                raise RuntimeError(
                    f'SHA-256 mismatch for {rel}: expected {entry.sha256}, got {digest}'
                )
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            part_path.replace(cache_file)
        finally:
            part_path.unlink(missing_ok=True)

    return cache_file


def resolve_bundled_or_custom_path(path: str | Path | None, default_relpath: str) -> Path:
    """Resolve None or default PACKAGE_DATA_DIR paths via ensure_data_file; leave custom user paths untouched."""
    if path is None:
        return ensure_data_file(default_relpath)
    candidate = Path(path)
    if candidate.resolve() == (PACKAGE_DATA_DIR / default_relpath).resolve():
        return ensure_data_file(default_relpath)
    return candidate


def ensure_parquet_root(census_year: int = 2022) -> Path:
    """Return an existing directory root for PartitionSpec construction (local checkout or revision cache)."""
    if census_year not in (2010, 2022):
        raise ValueError(f'census_year must be 2010 or 2022; got {census_year!r}')
    rel_root = 'parquet/census_year=2022' if census_year == 2022 else 'parquet'

    env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
    if env_data_dir:
        candidate = (Path(env_data_dir).expanduser() / rel_root).resolve()
        if (candidate / 'first_names').is_dir():
            return candidate

    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1':
        local_root = PACKAGE_DATA_DIR / rel_root
        if (local_root / 'first_names').is_dir():
            return local_root

    cache_root = get_revision_cache_dir() / rel_root
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def resolve_partition_path(path: Path) -> Path:
    """Lazy PartitionStore resolver: maps logical cache/package paths to ensure_data_file on demand."""
    resolved = path.resolve()
    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and resolved.is_file():
        return resolved

    for root in (PACKAGE_DATA_DIR.resolve(), get_revision_cache_dir().resolve()):
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        return ensure_data_file(rel)

    return path


def has_runtime_data_available(*, census_year: int = 2022) -> bool:
    probe = (
        'parquet/census_year=2022/first_names/scope=national/part.parquet'
        if census_year == 2022
        else 'names_data.json'
    )
    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and (PACKAGE_DATA_DIR / probe).is_file():
        return True
    if not MANIFEST_PATH.is_file():
        return False
    manifest = load_dataset_manifest()
    if probe in manifest.artifacts and (get_revision_cache_dir(manifest) / probe).is_file():
        return True
    return os.environ.get('PTBR_SAMPLER_OFFLINE') != '1'


def prefetch_datasets(*, census_year: int | None = 2022, verify_sha256: bool = True) -> list[Path]:
    manifest = load_dataset_manifest()
    downloaded: list[Path] = []
    for rel, entry in sorted(manifest.artifacts.items()):
        if census_year is not None and census_year not in entry.census_years:
            continue
        downloaded.append(ensure_data_file(rel, verify_sha256=verify_sha256))
    return downloaded


def dataset_cache_status(*, census_year: int | None = None, verify_sha256: bool = False) -> dict[str, Any]:
    manifest = load_dataset_manifest()
    rev_dir = get_revision_cache_dir(manifest)
    rows: list[dict[str, Any]] = []
    for rel, entry in sorted(manifest.artifacts.items()):
        if census_year is not None and census_year not in entry.census_years:
            continue
        local_file = PACKAGE_DATA_DIR / rel
        cache_file = rev_dir / rel
        if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and local_file.is_file():
            state = 'local-checkout'
            valid = not verify_sha256 or _sha256_file(local_file) == entry.sha256
        elif cache_file.is_file() and cache_file.stat().st_size == entry.size_bytes:
            state = 'cached'
            valid = not verify_sha256 or _sha256_file(cache_file) == entry.sha256
        else:
            state = 'remote-hf'
            valid = True
        rows.append(
            {
                'relpath': rel,
                'size_bytes': entry.size_bytes,
                'census_years': list(entry.census_years),
                'state': state,
                'valid': valid,
            }
        )
    return {
        'hf_repo_id': manifest.hf_repo_id,
        'hf_revision': manifest.hf_revision,
        'cache_dir': str(rev_dir),
        'artifacts': rows,
    }


def clear_dataset_cache(*, all_revisions: bool = False) -> int:
    target = get_cache_root() if all_revisions else get_revision_cache_dir()
    if not target.exists():
        return 0
    removed = sum(1 for p in target.rglob('*') if p.is_file())
    shutil.rmtree(target)
    return removed
```

Update `PartitionStore` in `ptbr_sampler/sampling/store.py` to accept `path_resolver: Callable[[Path], Path] | None = None`:

```python
class PartitionStore:
    def __init__(
        self,
        max_entries: int = 64,
        path_resolver: Callable[[Path], Path] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError('max_entries must be >= 1')
        self._max = max_entries
        self._path_resolver = path_resolver
        self._cache: OrderedDict[PartitionSpec, AliasTable] = OrderedDict()

    def _load(self, spec: PartitionSpec) -> AliasTable:
        raw_path = spec.path()
        path = self._path_resolver(raw_path) if self._path_resolver is not None else raw_path
        if not path.exists():
            raise FileNotFoundError(f'partition missing: {path}')
        dataset = ds.dataset(path, format='parquet')
        cols = set(dataset.schema.names)
        if 'count' in cols:
            tbl = dataset.to_table(columns=['name', 'count'])
            weights = tbl['count'].to_numpy(zero_copy_only=False).astype(np.float64)
        elif 'weight' in cols:
            tbl = dataset.to_table(columns=['name', 'weight'])
            weights = tbl['weight'].to_numpy(zero_copy_only=False).astype(np.float64)
        else:
            raise ValueError(f'partition {path} missing count/weight column (got {sorted(cols)})')
        names = tbl['name'].to_numpy(zero_copy_only=False)
        labels = np.asarray(names, dtype=object)
        return AliasTable.from_weights(labels, weights)
```

- [ ] **Step 4: Implement `scripts/publish_hf_dataset.py` and manifest-aware `ptbr_sampler/data_origins.py`**

Create `scripts/publish_hf_dataset.py` so contributors/CI can both generate `ptbr_sampler/data/dataset_manifest.json` offline (`--manifest-only`) and publish the runtime dataset tree + generated Dataset Card to `arthrod/ptbr-sampler-data` (`--publish`), automatically pinning the returned 40-character Hugging Face commit OID in `dataset_manifest.json`:

```python
"""Build dataset_manifest.json and publish runtime datasets to Hugging Face Hub."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import pyarrow.parquet as pq

import ptbr_sampler

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / 'ptbr_sampler' / 'data'
DEFAULT_REPO_ID = 'arthrod/ptbr-sampler-data'
_SHARED_JSON_FILES = frozenset({'cities_with_ceps.json', 'locations_data.json', 'middle_names.json'})
_LEGACY_2010_JSON_FILES = frozenset({'names_data.json', 'surnames_data.json'})


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _classify_census_years(relpath: str) -> list[int]:
    if relpath.startswith('parquet/census_year=2022/'):
        return [2022]
    if relpath.startswith(('parquet/middle_names/', 'parquet/states/')) or relpath in _SHARED_JSON_FILES:
        return [2010, 2022]
    if relpath.startswith(('parquet/first_names/', 'parquet/surnames/', 'parquet/sex_prior/')) or relpath in _LEGACY_2010_JSON_FILES:
        return [2010]
    raise ValueError(f'Unclassified runtime artifact: {relpath}')


def collect_runtime_artifacts(data_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    parquet_root = data_dir / 'parquet'
    if parquet_root.is_dir():
        for file_path in sorted(parquet_root.rglob('*')):
            if not file_path.is_file() or file_path.name.startswith('.') or '.bak' in file_path.name:
                continue
            if file_path.suffix == '.parquet':
                meta = pq.read_metadata(file_path)
                if meta.num_rows < 1:
                    raise ValueError(f'Empty Parquet artifact rejected: {file_path}')
            elif file_path.name == 'data_origin.json':
                json.loads(file_path.read_text(encoding='utf-8'))
            else:
                continue
            rel = file_path.relative_to(data_dir).as_posix()
            artifacts[rel] = {
                'sha256': _sha256(file_path),
                'size_bytes': file_path.stat().st_size,
                'census_years': _classify_census_years(rel),
            }

    for json_name in sorted(_SHARED_JSON_FILES | _LEGACY_2010_JSON_FILES):
        json_path = data_dir / json_name
        if not json_path.is_file():
            continue
        json.loads(json_path.read_text(encoding='utf-8'))
        artifacts[json_name] = {
            'sha256': _sha256(json_path),
            'size_bytes': json_path.stat().st_size,
            'census_years': _classify_census_years(json_name),
        }
    return artifacts


def build_dataset_card(repo_id: str, artifacts: dict[str, dict[str, Any]]) -> str:
    total_mib = sum(int(v['size_bytes']) for v in artifacts.values()) / (1024 * 1024)
    return (
        '---\n'
        'license: other\n'
        'language:\n'
        '- pt\n'
        'pretty_name: ptbr-sampler Runtime Demographic & Geographic Tables (Census 2022 & 2010)\n'
        'tags:\n'
        '- brazil\n'
        '- ibge\n'
        '- census-2022\n'
        '- names\n'
        '- demographics\n'
        '---\n\n'
        f'# `{repo_id}`\n\n'
        f'Pinned runtime dataset bundle (`{len(artifacts)}` files, `{total_mib:.2f} MiB`) fetched lazily on demand '
        f'by [`ptbr-sampler`](https://github.com/jandira-tech/ptbr-sampler) `v{ptbr_sampler.__version__}` so the PyPI '
        'wheel stays `< 150 KiB`.\n\n'
        '## Provenance & Attribution\n\n'
        '- **IBGE Censo Demográfico 2022 — Nomes no Brasil** (disclosure thresholds `< 20` national/cohort, `< 15` UF, `< 10` municipality; IBGE Liv102228).\n'
        '- **Census 2022 Parquet compilation:** Gabriel Lobo (`olob0/ibge-nomes-no-brasil-2022` @ `05efb85c92af43da2ed4ed088d1e0c9f17160e65`).\n'
        '- **Legacy 2010 Sex Prior:** Álvaro Justen (`brasil.io/genero-nomes`, CC BY-SA 4.0).\n'
        '- **IBGE Geography & Correios CEP ranges:** IBGE Localidades / CNEFE & CEP ranges.\n'
    )


def write_dataset_manifest(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    repo_id: str = DEFAULT_REPO_ID,
    revision: str = 'main',
) -> Path:
    artifacts = collect_runtime_artifacts(data_dir)
    manifest = {
        'schema_version': 1,
        'package_version': ptbr_sampler.__version__,
        'hf_repo_id': repo_id,
        'hf_revision': revision,
        'artifacts': artifacts,
    }
    out_path = data_dir / 'dataset_manifest.json'
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return out_path


def publish_to_huggingface(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    repo_id: str = DEFAULT_REPO_ID,
    private: bool = False,
    token: str | None = None,
) -> Path:
    from huggingface_hub import HfApi

    artifacts = collect_runtime_artifacts(data_dir)
    api = HfApi(token=token or os.environ.get('HF_TOKEN'))
    api.create_repo(repo_id=repo_id, repo_type='dataset', private=private, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='ptbr_hf_stage_') as tmp:
        stage = Path(tmp)
        for rel in artifacts:
            src = data_dir / rel
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        (stage / 'README.md').write_text(build_dataset_card(repo_id, artifacts), encoding='utf-8')

        commit_info = api.upload_folder(
            repo_id=repo_id,
            repo_type='dataset',
            folder_path=str(stage),
            commit_message=f'Publish ptbr-sampler v{ptbr_sampler.__version__} runtime datasets ({len(artifacts)} files)',
        )

    commit_oid = str(commit_info.oid)
    if len(commit_oid) != 40:
        info = api.repo_info(repo_id=repo_id, repo_type='dataset')
        commit_oid = str(info.sha)
    return write_dataset_manifest(data_dir, repo_id=repo_id, revision=commit_oid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument('--repo-id', default=os.environ.get('PTBR_SAMPLER_HF_REPO', DEFAULT_REPO_ID))
    parser.add_argument('--revision', default='main', help='Revision written in --manifest-only mode')
    parser.add_argument('--manifest-only', action='store_true', help='Write dataset_manifest.json without uploading')
    parser.add_argument('--publish', action='store_true', help='Upload runtime bundle to Hugging Face and pin commit SHA')
    parser.add_argument('--private', action='store_true', help='Create private HF dataset repo if creating new')
    args = parser.parse_args(argv)

    if args.publish:
        out = publish_to_huggingface(args.data_dir, repo_id=args.repo_id, private=args.private)
        print(f'Published to {args.repo_id} and pinned manifest: {out}')
        return 0
    out = write_dataset_manifest(args.data_dir, repo_id=args.repo_id, revision=args.revision)
    print(f'Wrote manifest ({out})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

Update `ptbr_sampler/data_origins.py` so `DataOrigin` tracks manifest-backed `remote_artifacts: tuple[str, ...]` (relative paths verified against `dataset_manifest.json`) alongside optional local `raw_inputs`, exposes `census_years: tuple[int, ...]`, and reports whether each artifact is `'local-checkout'`, `'cached'`, or `'remote-hf'` so `ptbr sources` and `tests/test_data_origins.py` pass both in source checkouts and inside cold slim wheels! Add Census 2022 `First names (Census 2022)` and `Surnames (Census 2022)` entries as primary defaults (`census_years=(2022,)`) and update `by_kind(kind_filter: str | None = None, *, census_year: int | None = None)`.

- [ ] **Step 5: Generate initial `dataset_manifest.json`, update `uv.lock`, run Task 4 tests, and commit**

Run:
1. `uv lock`
2. `uv run python -m scripts.publish_hf_dataset --manifest-only`
3. `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_runtime_datasets.py /home/arthrod/workspace/ptbr-sampler/tests/test_data_origins.py -v`
Expected: `dataset_manifest.json` written (`< 25 KiB`), all tests `PASS`.

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  pyproject.toml uv.lock \
  ptbr_sampler/__init__.py ptbr_sampler/datasets.py \
  ptbr_sampler/sampling/store.py ptbr_sampler/data_origins.py \
  ptbr_sampler/data/dataset_manifest.json \
  scripts/publish_hf_dataset.py \
  tests/test_runtime_datasets.py tests/test_data_origins.py
git -C /home/arthrod/workspace/ptbr-sampler commit -m "feat: bump to 0.3.0 and add Hugging Face runtime dataset resolver and slim-wheel manifest"
```

---

### Task 5: Move Default to Census 2022, Wire Strict/Estimated Conditioning & Lazy HF Resolution into Sampler & CLI

**Files:**
- Modify: `ptbr_sampler/br_name_class.py`
- Modify: `ptbr_sampler/sampler.py`
- Modify: `sample.py`
- Modify: `ptbr_sampler/cli.py`
- Create: `tests/test_cli.py`
- Modify: `tests/conftest.py:100-115`
- Modify: `tests/test_smoke.py:31-55`
- Modify: `tests/test_sampler.py:60-75`
- Modify: `tests/test_pr_additions.py:927-950`
- Modify: `tests/test_name_sampler.py`
- Modify: `tests/test_sample_api.py`

- [ ] **Step 1: Write failing tests for `census_year=2022` as primary default, `census_year=2010` opt-in, cohort bounds, strict vs estimated conditioning, surname UF/dedup, and `ptbr datasets` CLI**

Update `tests/conftest.py:100-115` (`for period in LEGACY_2010_PERIODS`), `tests/test_smoke.py:31-55` (assert `ptbr_sampler.__version__ == '0.3.0'`, `len(TimePeriod) == 12`, and `_skip_if_no_data` using `has_runtime_data_available()`), `tests/test_sample_api.py:8-24` and `tests/test_sampler.py:60-72` (`_skip_if_no_data` using `has_runtime_data_available()`), `tests/test_pr_additions.py:927-950`, and `tests/test_name_sampler.py:164-170` (`test_time_period_selection` iterating `LEGACY_2010_PERIODS`). Append the `0.3.0` default-2022 and conditioning unit tests to `tests/test_name_sampler.py` and `tests/test_sample_api.py`:

```python
import pyarrow as pa
import pyarrow.parquet as pq
from ptbr_sampler.br_name_class import LEGACY_2010_PERIODS, BrazilianNameSampler, TimePeriod


def _write_test_partition(dest_dir: Path, names: list[str], counts: list[int]) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    tot = float(sum(counts))
    pq.write_table(
        pa.table(
            {
                'name': pa.array(names, type=pa.string()),
                'count': pa.array(counts, type=pa.int64()),
                'weight': pa.array([c / tot for c in counts], type=pa.float64()),
            }
        ),
        dest_dir / 'part.parquet',
    )


def _write_test_sex_prior(
    dest_dir: Path,
    rows: list[tuple[str, str, int, int | None, int | None, int, float, float, str]],
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                'name': pa.array([r[0] for r in rows], type=pa.string()),
                'canonical_key': pa.array([r[1] for r in rows], type=pa.string()),
                'count_total': pa.array([r[2] for r in rows], type=pa.int64()),
                'count_male': pa.array([r[3] for r in rows], type=pa.int64()),
                'count_female': pa.array([r[4] for r in rows], type=pa.int64()),
                'residual_unassigned': pa.array([r[5] for r in rows], type=pa.int64()),
                'p_male': pa.array([r[6] for r in rows], type=pa.float64()),
                'p_female': pa.array([r[7] for r in rows], type=pa.float64()),
                'censoring_regime': pa.array([r[8] for r in rows], type=pa.string()),
            }
        ),
        dest_dir / 'part.parquet',
    )


def test_from_parquet_and_from_bundled_parquet_default_to_census_2022():
    sampler_default = BrazilianNameSampler.from_parquet()
    sampler_alias = BrazilianNameSampler.from_bundled_parquet()
    assert sampler_default.census_year == 2022
    assert sampler_alias.census_year == 2022
    assert sampler_default.parquet_root is not None and sampler_default.parquet_root.exists()


def test_legacy_2010_json_validation_ignores_2022_only_time_periods(mock_name_data):
    assert len(LEGACY_2010_PERIODS) == 9
    assert len(TimePeriod) == 12
    sampler = BrazilianNameSampler(mock_name_data)
    assert sampler.census_year == 2010
    with pytest.raises(ValueError, match='census_year=2010'):
        sampler.get_random_name(time_period=TimePeriod.ALL)
    with pytest.raises(ValueError, match='census_year=2010'):
        sampler.get_random_name(time_period=TimePeriod.PERIOD_2020_2022)


def test_census_2022_rejects_ate1930_and_strict_joint_queries():
    sampler = BrazilianNameSampler.from_parquet()
    with pytest.raises(ValueError, match='ate1930'):
        sampler.get_random_name(time_period=TimePeriod.UNTIL_1930)
    with pytest.raises(ValueError, match="conditioning_mode='estimated'"):
        sampler.get_random_name(time_period=TimePeriod.ALL, uf='SP', sex='F')
    with pytest.raises(ValueError, match="conditioning_mode='estimated'"):
        sampler.get_random_name(time_period=TimePeriod.UNTIL_2020, sex='M')
    sampler_est = BrazilianNameSampler.from_parquet(conditioning_mode='estimated')
    with pytest.raises(ValueError, match='UF x cohort'):
        sampler_est.get_random_name(time_period=TimePeriod.UNTIL_2020, uf='SP')


def test_census_2022_estimated_mode_computes_exact_bayes_weights_and_excludes_suppressed_sex(tmp_path: Path):
    import math

    root_2022 = tmp_path / 'census_year=2022'
    # Cohort has 'Maria' (100), 'Joao' (100), and 'Rara' (30, male suppressed <20: female=25, residual=5)
    _write_test_partition(root_2022 / 'first_names' / 'period=ate2020', ['Maria', 'Joao', 'Rara'], [100, 100, 30])
    _write_test_partition(root_2022 / 'surnames' / 'scope=national', ['Silva', 'Santos'], [60, 40])
    _write_test_sex_prior(
        root_2022 / 'sex_prior' / 'scope=national',
        rows=[
            ('Maria', 'maria', 1000, 100, 900, 0, 0.10, 0.90, 'both_observed'),
            ('Joao', 'joao', 1000, 900, 100, 0, 0.90, 0.10, 'both_observed'),
            ('Rara', 'rara', 30, None, 25, 5, math.nan, 25.0 / 30.0, 'one_null_suppressed_positive'),
        ],
    )
    sampler = BrazilianNameSampler.from_parquet_root(
        root_2022,
        census_year=2022,
        conditioning_mode='estimated',
    )
    # Male table must exclude 'Rara' (male cell suppressed <20) rather than fabricating count=5:
    table_m = sampler._first_names_table(TimePeriod.UNTIL_2020, sex='M')
    by_m = dict(zip(table_m.labels.tolist(), table_m.induced_probabilities().tolist(), strict=True))
    assert 'Rara' not in by_m
    assert abs(by_m['Joao'] - 0.90) < 1e-12
    assert abs(by_m['Maria'] - 0.10) < 1e-12

    # Female table scales 'Rara' by exact observed rate 25/30 (NOT 1.0!):
    # Unnormalised numerators proportional to: Maria 100*0.9=90, Joao 100*0.1=10, Rara 30*(25/30)=25 -> sum=125
    table_f = sampler._first_names_table(TimePeriod.UNTIL_2020, sex='F')
    by_f = dict(zip(table_f.labels.tolist(), table_f.induced_probabilities().tolist(), strict=True))
    assert abs(by_f['Maria'] - (90.0 / 125.0)) < 1e-12
    assert abs(by_f['Joao'] - (10.0 / 125.0)) < 1e-12
    assert abs(by_f['Rara'] - (25.0 / 125.0)) < 1e-12


def test_census_2022_two_surname_draw_prevents_identical_stems(tmp_path: Path):
    root_2022 = tmp_path / 'census_year=2022'
    _write_test_partition(root_2022 / 'first_names' / 'scope=national', ['Maria'], [100])
    _write_test_partition(root_2022 / 'surnames' / 'scope=national', ['Silva', 'Santos'], [90, 10])
    sampler = BrazilianNameSampler.from_parquet_root(root_2022, census_year=2022)
    random.seed(7)
    batches = sampler.batch_sample_names(500, time_period=TimePeriod.ALL, raw=True)
    for comp in batches:
        tokens = [t for t in comp.surname.split() if t not in {'DA', 'DE', 'DO', 'DOS', 'DAS', 'E'}]
        assert len(tokens) == 2
        assert tokens[0] != tokens[1]


def test_sample_api_defaults_to_census_2022_and_supports_2010_opt_in():
    from sample import sample

    s_default = sample(q=1)
    s_2022_pop = sample(q=5, sex_conditioning='population')
    s_2010 = sample(q=1, census_year=2010)
    assert isinstance(s_default, dict) and s_default['name']
    assert len(s_2022_pop) == 5
    assert isinstance(s_2010, dict) and s_2010['name']
    # Confirm default is 2022 ('population' is valid without passing census_year=2022, and ate1930 is rejected):
    with pytest.raises(ValueError, match='ate1930'):
        sample(q=1, time_period=TimePeriod.UNTIL_1930)
```

Create `tests/test_cli.py`:

```python
"""CLI integration tests for 0.3.0 Census 2022 default, 2010 opt-in, conditioning modes, and HF dataset commands."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def _run_ptbr(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, '-m', 'ptbr_sampler', *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_cli_generate_defaults_to_census_2022_and_supports_2010_opt_in():
    for extra in (
        (),  # bare default -> Census 2022 + TimePeriod.ALL
        ('--sex-conditioning', 'F'),
        ('--sex-conditioning', 'population'),
        ('--time-period', 'ate2020'),
        ('--time-period', '2020_2022'),
        ('--uf-conditioning',),
        ('--uf-conditioning', '--sex-conditioning', 'F', '--conditioning-mode', 'estimated'),
        ('--census-year', '2010'),
        ('--census-year', '2010', '--time-period', 'ate1930'),
    ):
        res = _run_ptbr('generate', '--qty', '2', *extra)
        assert res.returncode == 0, f'failed for {extra}: {res.stderr}\n{res.stdout}'


def test_cli_generate_default_rejects_strict_joint_uf_and_sex_and_ate1930():
    res_joint = _run_ptbr('generate', '--qty', '2', '--uf-conditioning', '--sex-conditioning', 'F')
    assert res_joint.returncode != 0
    assert 'estimated' in f'{res_joint.stdout}\n{res_joint.stderr}'

    res_1930 = _run_ptbr('generate', '--qty', '2', '--time-period', 'ate1930')
    assert res_1930.returncode != 0
    assert 'ate1930' in f'{res_1930.stdout}\n{res_1930.stderr}'


def test_cli_sources_and_datasets_status_and_clear_cache(tmp_path: Path):
    res_src = _run_ptbr('sources', '--census-year', '2022')
    assert res_src.returncode == 0, res_src.stderr
    assert 'Census 2022' in res_src.stdout

    env = {'PTBR_SAMPLER_CACHE_DIR': str(tmp_path / 'hf_cache')}
    res_status = _run_ptbr('datasets', 'status', '--census-year', '2022', env_overrides=env)
    assert res_status.returncode == 0, res_status.stderr
    assert 'arthrod/ptbr-sampler-data' in res_status.stdout

    res_clear = _run_ptbr('datasets', 'clear-cache', env_overrides=env)
    assert res_clear.returncode == 0, res_clear.stderr
```

- [ ] **Step 2: Run the new sampler, API, and CLI tests to confirm failure**

Run: `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_name_sampler.py /home/arthrod/workspace/ptbr-sampler/tests/test_sample_api.py /home/arthrod/workspace/ptbr-sampler/tests/test_cli.py -v`
Expected: `FAIL` with `ImportError: cannot import name 'LEGACY_2010_PERIODS' from 'ptbr_sampler.br_name_class'`.

- [ ] **Step 3: Extend `TimePeriod` and `BrazilianNameSampler` in `ptbr_sampler/br_name_class.py` with `census_year=2022` default and lazy HF resolution**

Update `ptbr_sampler/br_name_class.py` with vintage-aware `TimePeriod` constants, `from_parquet` / `from_bundled_parquet` defaulting to `census_year=2022` and wired to `ensure_parquet_root` + `resolve_partition_path`, strict vs lazy Bayes `_first_names_table_2022`, UF surname tables, non-colliding 2-surname draws, and deterministic bucket sorting:

```python
from ptbr_sampler.datasets import (
    ensure_data_file,
    ensure_parquet_root,
    resolve_bundled_or_custom_path,
    resolve_partition_path,
)

CENSUS_2022_OBSERVED_MALE_SHARE: float = 92_287_140 / 190_041_904  # 0.4856151515825794


class TimePeriod(StrEnum):
    ALL = 'all'
    UNTIL_1930 = 'ate1930'
    UNTIL_1940 = 'ate1940'
    UNTIL_1950 = 'ate1950'
    UNTIL_1960 = 'ate1960'
    UNTIL_1970 = 'ate1970'
    UNTIL_1980 = 'ate1980'
    UNTIL_1990 = 'ate1990'
    UNTIL_2000 = 'ate2000'
    UNTIL_2010 = 'ate2010'
    UNTIL_2020 = 'ate2020'
    PERIOD_2020_2022 = '2020_2022'


LEGACY_2010_PERIODS: tuple[TimePeriod, ...] = (
    TimePeriod.UNTIL_1930,
    TimePeriod.UNTIL_1940,
    TimePeriod.UNTIL_1950,
    TimePeriod.UNTIL_1960,
    TimePeriod.UNTIL_1970,
    TimePeriod.UNTIL_1980,
    TimePeriod.UNTIL_1990,
    TimePeriod.UNTIL_2000,
    TimePeriod.UNTIL_2010,
)

CENSUS_2022_SUPPORTED_PERIODS: frozenset[TimePeriod] = frozenset(
    {
        TimePeriod.ALL,
        TimePeriod.UNTIL_1940,
        TimePeriod.UNTIL_1950,
        TimePeriod.UNTIL_1960,
        TimePeriod.UNTIL_1970,
        TimePeriod.UNTIL_1980,
        TimePeriod.UNTIL_1990,
        TimePeriod.UNTIL_2000,
        TimePeriod.UNTIL_2010,
        TimePeriod.UNTIL_2020,
        TimePeriod.PERIOD_2020_2022,
    }
)


def resolve_time_period(time_period: TimePeriod | None, census_year: int) -> TimePeriod:
    if census_year == 2010:
        resolved = TimePeriod.UNTIL_2010 if time_period is None else TimePeriod(time_period)
        if resolved not in LEGACY_2010_PERIODS:
            raise ValueError(
                f'time_period={resolved.value!r} is not supported for census_year=2010; '
                f'choose one of {[p.value for p in LEGACY_2010_PERIODS]} or census_year=2022.'
            )
        return resolved
    if census_year == 2022:
        resolved = TimePeriod.ALL if time_period is None else TimePeriod(time_period)
        if resolved not in CENSUS_2022_SUPPORTED_PERIODS:
            raise ValueError(
                f'time_period={resolved.value!r} is not supported for census_year=2022 '
                '(IBGE 2022 merges pre-1930 survivors into decade=1930 / ate1940).'
            )
        return resolved
    raise ValueError(f'census_year must be 2010 or 2022; got {census_year!r}')
```

Inside `BrazilianNameSampler`:

```python
    @classmethod
    def from_parquet_root(
        cls,
        parquet_root: str | Path,
        *,
        middle_names_path: str | Path | None = None,
        census_year: int = 2022,
        conditioning_mode: Literal['strict', 'estimated'] = 'strict',
        lru_size: int = 64,
        path_resolver: Callable[[Path], Path] | None = None,
    ) -> BrazilianNameSampler:
        root = Path(parquet_root)
        if not root.exists():
            raise FileNotFoundError(f'Parquet root not found: {root}')
        return cls(
            {'surnames': {'top_40': {}}, 'common_names_percentage': {}},
            middle_names_path=middle_names_path,
            names_path=None,
            parquet_root=root,
            lru_size=lru_size,
            census_year=census_year,
            conditioning_mode=conditioning_mode,
            path_resolver=path_resolver,
        )

    @classmethod
    def from_parquet(
        cls,
        *,
        include_middle_names: bool = True,
        lru_size: int = 64,
        census_year: int = 2022,
        conditioning_mode: Literal['strict', 'estimated'] = 'strict',
    ) -> BrazilianNameSampler:
        middle_path = ensure_data_file('middle_names.json') if include_middle_names else None
        p_root = ensure_parquet_root(census_year)
        if census_year == 2022:
            return cls.from_parquet_root(
                p_root,
                middle_names_path=middle_path,
                census_year=2022,
                conditioning_mode=conditioning_mode,
                lru_size=lru_size,
                path_resolver=resolve_partition_path,
            )
        surnames_path = ensure_data_file('surnames_data.json')
        with surnames_path.open(encoding='utf-8') as fh:
            surnames_payload = json.load(fh)
        return cls(
            {'surnames': surnames_payload['surnames'], 'common_names_percentage': {}},
            middle_names_path=middle_path,
            names_path=None,
            parquet_root=p_root,
            lru_size=lru_size,
            census_year=2010,
            conditioning_mode=conditioning_mode,
            path_resolver=resolve_partition_path,
        )

    from_bundled_parquet = from_parquet

    def _load_sex_prior_2022(self) -> dict[str, tuple[float, float]]:
        if self._sex_prior_2022 is not None:
            return self._sex_prior_2022
        assert self.parquet_root is not None
        import pyarrow.parquet as pq  # noqa: PLC0415

        raw_path = self.parquet_root / 'sex_prior' / 'scope=national' / 'part.parquet'
        prior_path = self._path_resolver(raw_path) if self._path_resolver is not None else raw_path
        tbl = pq.read_table(prior_path, columns=['name', 'p_male', 'p_female'])
        self._sex_prior_2022 = {
            str(n): (float(pm), float(pf))
            for n, pm, pf in zip(
                tbl['name'].to_pylist(),
                tbl['p_male'].to_pylist(),
                tbl['p_female'].to_pylist(),
                strict=True,
            )
        }
        return self._sex_prior_2022

    def _first_names_table_2022(
        self,
        time_period: TimePeriod,
        *,
        uf: str | None = None,
        sex: str | None = None,
    ) -> AliasTable:
        resolved = resolve_time_period(time_period, 2022)
        assert self.parquet_root is not None
        if uf is not None and resolved != TimePeriod.ALL:
            raise ValueError(
                f'Census 2022 does not provide UF x cohort joint distributions '
                f'(requested uf={uf!r}, time_period={resolved.value!r}).'
            )
        # 4 directly observed 1D marginals:
        if resolved == TimePeriod.ALL and uf is None and sex is None:
            spec = PartitionSpec.of(self.parquet_root / 'first_names', scope='national')
            return self._require_parquet(spec)
        if resolved == TimePeriod.ALL and uf is None and sex is not None:
            spec = PartitionSpec.of(self.parquet_root / 'first_names', sex=sex)
            return self._require_parquet(spec)
        if resolved != TimePeriod.ALL and uf is None and sex is None:
            spec = PartitionSpec.of(self.parquet_root / 'first_names', period=resolved.value)
            return self._require_parquet(spec)
        if resolved == TimePeriod.ALL and uf is not None and sex is None:
            spec = PartitionSpec.of(self.parquet_root / 'first_names', uf=uf)
            return self._require_parquet(spec)

        # Remaining combinations are (UF x sex) or (cohort x sex):
        if self.conditioning_mode == 'strict':
            raise ValueError(
                f'Census 2022 has no observed joint partition for '
                f'(time_period={resolved.value!r}, uf={uf!r}, sex={sex!r}); '
                "pass conditioning_mode='estimated' to opt into national-sex-prior Bayes reweighting."
            )

        est_key = (resolved.value, uf, sex)
        cached = self._estimated_2022_alias.get(est_key)
        if cached is not None:
            return cached

        base = (
            self._require_parquet(PartitionSpec.of(self.parquet_root / 'first_names', uf=uf))
            if uf is not None
            else self._require_parquet(PartitionSpec.of(self.parquet_root / 'first_names', period=resolved.value))
        )
        sex_prior = self._load_sex_prior_2022()
        sex_idx = 0 if sex == 'M' else 1
        out_labels: list[str] = []
        out_weights: list[float] = []
        for label, base_w in zip(base.labels.tolist(), base.weights.tolist(), strict=True):
            pair = sex_prior.get(str(label))
            if pair is None:
                continue
            p_sex = pair[sex_idx]
            if math.isfinite(p_sex) and p_sex > 0.0:
                out_labels.append(str(label))
                out_weights.append(float(base_w) * p_sex)
        if not out_weights:
            raise ValueError(f'Empty estimated conditional support for {est_key}')
        table = AliasTable.from_weights(out_labels, out_weights)
        self._estimated_2022_alias[est_key] = table
        return table
```

Note that direct dict/JSON calls `BrazilianNameSampler(json_file_path_or_dict, ...)` with `parquet_root=None` retain `census_year: int = 2010` as their constructor default so existing unit tests passing `mock_name_data` dictionaries remain 100% compatible without changes.

And in `_draw` / `_surnames_table` / `_draw_first_names_conditioned`:
- `_surnames_table(uf: str | None = None)` loads `PartitionSpec.of(self.parquet_root / 'surnames', uf=uf)` when `self.census_year == 2022 and uf is not None`, else `scope='national'`; `_top_40_table(uf=uf)` returns `self._surnames_table(uf=uf).top_k(40)` when `self.census_year == 2022`; `get_random_surname(..., uf: str | None = None)` accepts optional `uf`.
- When `self.census_year == 2022 and not with_only_one_surname and len(surname_table) >= 2`, redraw colliding slot-2 surnames (`clash = surname_draws_b == surname_draws_a; while np.any(clash): surname_draws_b[clash] = _alias_draw(surname_table, int(np.count_nonzero(clash)), rng, random_mode=random_mode); clash = surname_draws_b == surname_draws_a`).
- Sort `(uf, sex)` buckets deterministically via `for (bucket_uf, bucket_sex), indices in sorted(buckets.items(), key=lambda kv: (kv[0][0] or '', kv[0][1] or '')):`.

- [ ] **Step 4: Flip defaults to `census_year=2022`, resolve runtime paths via `ptbr_sampler.datasets`, and add `ptbr datasets` CLI in `ptbr_sampler/sampler.py`, `sample.py`, and `ptbr_sampler/cli.py`**

Update `ptbr_sampler/sampler.py`:

```python
@functools.lru_cache(maxsize=8)
def _get_cached_name_sampler(
    census_year: int,
    conditioning_mode: str,
    custom_names_path: str | None,
    custom_surnames_path: str | None,
    resolved_middle_path: str | None,
) -> BrazilianNameSampler:
    if census_year == 2022 and custom_names_path is None and custom_surnames_path is None:
        return BrazilianNameSampler.from_parquet_root(
            ensure_parquet_root(2022),
            middle_names_path=resolved_middle_path,
            census_year=2022,
            conditioning_mode=conditioning_mode,  # type: ignore[arg-type]
            path_resolver=resolve_partition_path,
        )
    surnames_file = Path(custom_surnames_path) if custom_surnames_path else ensure_data_file('surnames_data.json')
    names_file = Path(custom_names_path) if custom_names_path else ensure_data_file('names_data.json')
    surnames_data = copy.deepcopy(_load_json_cached(surnames_file))
    name_data = {'surnames': surnames_data['surnames']}
    name_data.update(copy.deepcopy(_load_json_cached(names_file)))
    use_parquet = custom_names_path is None and custom_surnames_path is None
    return BrazilianNameSampler(
        name_data,
        resolved_middle_path,
        None,
        parquet_root=ensure_parquet_root(census_year) if use_parquet else None,
        census_year=census_year,
        conditioning_mode=conditioning_mode,  # type: ignore[arg-type]
        path_resolver=resolve_partition_path if use_parquet else None,
    )


def _population_sexes_2022(n: int) -> list[str]:
    return [
        'M' if random_module.random() < CENSUS_2022_OBSERVED_MALE_SHARE else 'F'
        for _ in range(n)
    ]
```

In `ptbr_sampler/sampler.py:sample(...)`, `sample.py:sample(...)`, and `ptbr_sampler/cli.py`:
- Flip `census_year: int = 2022` and `time_period: TimePeriod | None = None` (`resolve_time_period(None, 2022) -> TimePeriod.ALL`; `resolve_time_period(None, 2010) -> TimePeriod.UNTIL_2010`), plus `conditioning_mode: str = 'strict'` and `uf_conditioning: bool = False`.
- Resolve `json_path`, `middle_names_path`, and `locations_path` via `resolve_bundled_or_custom_path(...)` so fresh slim-wheel installs download `cities_with_ceps.json` / `locations_data.json` / `middle_names.json` automatically on first `sample()` call, while treating default `PACKAGE_DATA_DIR / 'names_data.json'` and `'surnames_data.json'` as `custom_names_path=None` / `custom_surnames_path=None` so `census_year=2022` never downloads 2010 legacy JSONs.
- Validate `conditioning_mode in {'strict', 'estimated'}` and `sex_conditioning` in `{'M', 'F', 'MIXED', 'POPULATION'}` (`'POPULATION'` requires `census_year == 2022` and uses `_population_sexes_2022(actual_qty)`).
- Pass `ufs=per_row_ufs` whenever `uf_conditioning or experimental_uf_sex_conditioning` across batch, single-row, `return_only_name`, and `only_surname` paths.
- In `ptbr_sampler/cli.py`:
  - Set `CENSUS_YEAR = typer.Option(2022, '--census-year', help='IBGE Census vintage: 2022 (default) or 2010 (historical).')`, `TIME_PERIOD` default to `None`, `CONDITIONING_MODE = typer.Option('strict', '--conditioning-mode', ...)`, and `UF_CONDITIONING = typer.Option(False, '--uf-conditioning', ...)`.
  - Add `datasets_app = typer.Typer(help='Inspect, prefetch, or clear cached Hugging Face runtime datasets.')` (`app.add_typer(datasets_app, name='datasets')`) with `ptbr datasets status [--census-year 2022|2010] [--verify]`, `ptbr datasets prefetch [--census-year 2022|2010] [--all-vintages]`, and `ptbr datasets clear-cache [--all-revisions]`.

- [ ] **Step 5: Run unit, API, CLI, and parity tests, then commit Task 5**

Run:
`uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_smoke.py /home/arthrod/workspace/ptbr-sampler/tests/test_sampler.py /home/arthrod/workspace/ptbr-sampler/tests/test_pr_additions.py /home/arthrod/workspace/ptbr-sampler/tests/test_name_sampler.py /home/arthrod/workspace/ptbr-sampler/tests/test_sample_api.py /home/arthrod/workspace/ptbr-sampler/tests/test_cli.py -v`
Expected: `PASS` across all `0.3.0` Census 2022 default tests and explicit `census_year=2010` compatibility tests.

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  ptbr_sampler/br_name_class.py ptbr_sampler/sampler.py sample.py ptbr_sampler/cli.py \
  tests/conftest.py tests/test_smoke.py tests/test_sampler.py tests/test_pr_additions.py \
  tests/test_name_sampler.py tests/test_sample_api.py tests/test_cli.py
git -C /home/arthrod/workspace/ptbr-sampler commit -m "feat: switch default to Census 2022, wire HF dataset resolver, and add datasets CLI"
```

---

### Task 6: Four-Layer Statistical Validation & Negative-Control Suite

**Files:**
- Modify: `tests/test_distribution_validation.py`
- Modify: `tests/test_batch_parity.py`
- Modify: `scripts/audit_datasets.py`

- [ ] **Step 1: Replace flawed KS / truncated-head tests in `tests/test_distribution_validation.py` and `tests/test_batch_parity.py` with the four-layer suite**

Rewrite `tests/test_distribution_validation.py` to separate fast deterministic validation (runs in ordinary CI without `-m slow`) from Monte Carlo end-to-end sampling checks (`@pytest.mark.slow`), resolving partition paths through `ptbr_sampler.datasets` so the suite runs identically against both local checkouts and slim-wheel caches:

```python
"""Four-layer statistical validation suite for 2022 (default) and 2010 Parquet distributions."""

from __future__ import annotations

import math
import random
from collections import Counter

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ptbr_sampler.br_name_class import BrazilianNameSampler, TimePeriod
from ptbr_sampler.datasets import ensure_data_file, ensure_parquet_root, load_dataset_manifest, resolve_partition_path
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore
from ptbr_sampler.sampling.validation import (
    exhaustive_multinomial_gof,
    holm_bonferroni_reject,
    linf_distance,
    total_variation_distance,
)


def _read_parquet_rel(relpath: str) -> pa.Table:
    return pq.read_table(ensure_data_file(relpath))


class TestLayerACensus2022IngestionConservation:
    """Layer A: Deterministic source-to-Parquet conservation & anchor invariants."""

    def test_partition_row_counts_and_published_anchors(self):
        nat_given = _read_parquet_rel('parquet/census_year=2022/first_names/scope=national/part.parquet')
        nat_surnames = _read_parquet_rel('parquet/census_year=2022/surnames/scope=national/part.parquet')
        sex_m = _read_parquet_rel('parquet/census_year=2022/first_names/sex=M/part.parquet')
        sex_f = _read_parquet_rel('parquet/census_year=2022/first_names/sex=F/part.parquet')
        states = _read_parquet_rel('parquet/census_year=2022/states/part.parquet')

        assert nat_given.num_rows == 128_458
        assert nat_surnames.num_rows == 201_601
        assert sex_m.num_rows == 60_954
        assert sex_f.num_rows == 73_361
        assert states.num_rows == 27
        assert sum(states['population'].to_pylist()) == 203_080_756

        given_counts = dict(zip(nat_given['name'].to_pylist(), nat_given['count'].to_pylist(), strict=True))
        surname_counts = dict(zip(nat_surnames['name'].to_pylist(), nat_surnames['count'].to_pylist(), strict=True))
        assert given_counts['Maria'] == 12_284_478
        assert surname_counts['Silva'] == 34_030_104
        assert surname_counts['Santos'] == 21_367_475
        assert surname_counts['Perl'] == 24

    def test_every_manifest_parquet_partition_sums_to_unit_mass_in_float64(self):
        manifest = load_dataset_manifest()
        parquet_rels = [rel for rel in sorted(manifest.artifacts) if rel.endswith('part.parquet')]
        assert parquet_rels
        for rel in parquet_rels:
            pf = ensure_data_file(rel)
            schema = pq.read_schema(pf)
            if 'weight' not in schema.names:
                continue
            weights = pq.read_table(pf, columns=['weight'])['weight'].to_pylist()
            assert abs(math.fsum(weights) - 1.0) < 1e-12, f'non-unit weight sum in {rel}'

    def test_exact_national_marginal_coherence_between_sex_prior_and_strict_sex_tables(self):
        nat = _read_parquet_rel('parquet/census_year=2022/first_names/scope=national/part.parquet')
        prior = _read_parquet_rel('parquet/census_year=2022/sex_prior/scope=national/part.parquet')
        strict_f = _read_parquet_rel('parquet/census_year=2022/first_names/sex=F/part.parquet')

        p_f_by_name = dict(zip(prior['name'].to_pylist(), prior['p_female'].to_pylist(), strict=True))
        bayes_num = {
            str(n): float(w) * p_f_by_name[str(n)]
            for n, w in zip(nat['name'].to_pylist(), nat['weight'].to_pylist(), strict=True)
            if math.isfinite(p_f_by_name[str(n)]) and p_f_by_name[str(n)] > 0.0
        }
        z = math.fsum(bayes_num.values())
        bayes_f = {k: v / z for k, v in bayes_num.items()}
        strict_f_map = dict(zip(strict_f['name'].to_pylist(), strict_f['weight'].to_pylist(), strict=True))

        assert set(bayes_f) == set(strict_f_map)
        vocab = sorted(strict_f_map)
        tvd = total_variation_distance(
            np.array([bayes_f[k] for k in vocab]),
            np.array([strict_f_map[k] for k in vocab]),
        )
        assert tvd < 1e-14

    def test_cohort_enzo_shift_and_regional_surname_concentration(self):
        p2010 = _read_parquet_rel('parquet/census_year=2022/first_names/period=ate2010/part.parquet')
        p2020 = _read_parquet_rel('parquet/census_year=2022/first_names/period=ate2020/part.parquet')
        w2010 = dict(zip(p2010['name'].to_pylist(), p2010['weight'].to_pylist(), strict=True))
        w2020 = dict(zip(p2020['name'].to_pylist(), p2020['weight'].to_pylist(), strict=True))
        assert w2020['Enzo'] > 5.0 * w2010['Enzo']

        nat_s = _read_parquet_rel('parquet/census_year=2022/surnames/scope=national/part.parquet')
        se_s = _read_parquet_rel('parquet/census_year=2022/surnames/uf=SE/part.parquet')
        al_s = _read_parquet_rel('parquet/census_year=2022/surnames/uf=AL/part.parquet')
        wnat = dict(zip(nat_s['name'].to_pylist(), nat_s['weight'].to_pylist(), strict=True))
        wse = dict(zip(se_s['name'].to_pylist(), se_s['weight'].to_pylist(), strict=True))
        wal = dict(zip(al_s['name'].to_pylist(), al_s['weight'].to_pylist(), strict=True))
        assert wse['Santos'] > 2.5 * wnat['Santos']
        assert wal['Silva'] > 1.8 * wnat['Silva']


class TestLayerBExactAliasReconstruction:
    """Layer B: Closed-form O(M) alias probability verification (zero Monte Carlo variance)."""

    @pytest.mark.parametrize(
        ('census_year', 'subdir', 'filters'),
        [
            (2010, 'first_names', {'period': 'ate2010'}),
            (2022, 'first_names', {'scope': 'national'}),
            (2022, 'surnames', {'scope': 'national'}),
            (2022, 'first_names', {'sex': 'F'}),
            (2022, 'first_names', {'uf': 'SP'}),
            (2022, 'first_names', {'uf': 'AC'}),
            (2022, 'first_names', {'period': '2020_2022'}),
        ],
    )
    def test_induced_alias_probabilities_match_weights_to_machine_precision(
        self, census_year: int, subdir: str, filters: dict[str, str]
    ):
        root = ensure_parquet_root(census_year)
        store = PartitionStore(max_entries=4, path_resolver=resolve_partition_path)
        table = store.get(PartitionSpec.of(root / subdir, **filters))
        induced = table.induced_probabilities()
        assert total_variation_distance(induced, table.weights) < 1e-13
        assert linf_distance(induced, table.weights) < 1e-14


@pytest.mark.slow
class TestLayerCMonteCarloAndNegativeControls:
    """Layer C: Exhaustive tail-pooled GoF + Holm-Bonferroni FWER + negative controls."""

    def test_end_to_end_family_passes_holm_bonferroni_at_alpha_0_001(self):
        pytest.importorskip('scipy.stats')
        sampler_2010 = BrazilianNameSampler.from_parquet(census_year=2010)
        sampler_2022 = BrazilianNameSampler.from_parquet()  # default census_year=2022
        sampler_2022_est = BrazilianNameSampler.from_parquet(conditioning_mode='estimated')
        n = 50_000
        cases = {
            '2010_ate2010': (sampler_2010, sampler_2010._first_names_table(TimePeriod.UNTIL_2010), {'time_period': TimePeriod.UNTIL_2010}),
            '2022_all': (sampler_2022, sampler_2022._first_names_table(TimePeriod.ALL), {'time_period': TimePeriod.ALL}),
            '2022_sex_f': (sampler_2022, sampler_2022._first_names_table(TimePeriod.ALL, sex='F'), {'time_period': TimePeriod.ALL, 'sexes': ['F'] * n}),
            '2022_sex_m': (sampler_2022, sampler_2022._first_names_table(TimePeriod.ALL, sex='M'), {'time_period': TimePeriod.ALL, 'sexes': ['M'] * n}),
            '2022_ate2020': (sampler_2022, sampler_2022._first_names_table(TimePeriod.UNTIL_2020), {'time_period': TimePeriod.UNTIL_2020}),
            '2022_uf_sp': (sampler_2022, sampler_2022._first_names_table(TimePeriod.ALL, uf='SP'), {'time_period': TimePeriod.ALL, 'ufs': ['SP'] * n}),
            '2022_est_ba_f': (sampler_2022_est, sampler_2022_est._first_names_table(TimePeriod.ALL, uf='BA', sex='F'), {'time_period': TimePeriod.ALL, 'ufs': ['BA'] * n, 'sexes': ['F'] * n}),
        }
        p_values: dict[str, float] = {}
        for idx, (key, (smp, table, draw_kw)) in enumerate(cases.items()):
            random.seed(10_000 + idx)
            comps = smp.batch_sample_names(n, include_surname=False, **draw_kw)
            tally = Counter(c.first_name for c in comps)
            obs = np.array([tally.get(str(lbl), 0) for lbl in table.labels], dtype=np.int64)
            res = exhaustive_multinomial_gof(obs, table.weights, min_expected=5.0)
            p_values[key] = res.p_value
            assert res.tvd < 0.015, f'{key}: excessive TVD={res.tvd:.4f}'

        assert holm_bonferroni_reject(p_values, alpha=0.001) == set(), f'FWER rejection: {p_values}'

    def test_surname_slot_share_and_two_slot_person_presence_match_distinct_targets(self):
        sampler_2022 = BrazilianNameSampler.from_parquet()
        table = sampler_2022._surnames_table()
        q = dict(zip((str(x) for x in table.labels), table.weights.tolist(), strict=True))
        q_silva = q['Silva']  # ~0.10204044
        # Analytical 2-slot non-colliding presence: q_s + sum_{j != s} q_j * q_s / (1 - q_j)
        expected_two_slot = q_silva + math.fsum(
            qj * (q_silva / (1.0 - qj)) for name, qj in q.items() if name != 'Silva'
        )
        random.seed(2022)
        one_slot = sampler_2022.batch_sample_names(40_000, time_period=TimePeriod.ALL, with_only_one_surname=True, raw=True)
        two_slot = sampler_2022.batch_sample_names(40_000, time_period=TimePeriod.ALL, with_only_one_surname=False, raw=True)

        emp_one = sum('SILVA' in c.surname.split() for c in one_slot) / 40_000
        emp_two = sum('SILVA' in c.surname.split() for c in two_slot) / 40_000
        assert abs(emp_one - q_silva) < 0.008
        assert abs(emp_two - expected_two_slot) < 0.008

    def test_negative_control_head_to_tail_leak_and_dropped_conditioning_are_rejected(self):
        pytest.importorskip('scipy.stats')
        root_2022 = ensure_parquet_root(2022)
        store = PartitionStore(max_entries=4, path_resolver=resolve_partition_path)
        nat = store.get(PartitionSpec.of(root_2022 / 'first_names', scope='national'))
        sex_f = store.get(PartitionSpec.of(root_2022 / 'first_names', sex='F'))

        # Negative Control 1: 5% mass leaked from tail into top-10 head
        corrupt = nat.weights.copy()
        order = np.argsort(-corrupt)
        corrupt[order[:10]] += 0.005
        corrupt[order[10:]] *= (1.0 - float(corrupt[order[:10]].sum())) / float(corrupt[order[10:]].sum())
        rng = np.random.default_rng(99)
        draws = rng.choice(len(nat), size=30_000, p=corrupt)
        obs = np.bincount(draws, minlength=len(nat))
        res_leak = exhaustive_multinomial_gof(obs, nat.weights, min_expected=5.0)
        assert res_leak.p_value < 1e-6

        # Negative Control 2: unconditioned national draws evaluated against sex=F target
        nat_draws = nat.sample(20_000, rng)
        tally = Counter(str(x) for x in nat_draws)
        obs_f = np.array([tally.get(str(lbl), 0) for lbl in sex_f.labels], dtype=np.int64)
        in_support = int(obs_f.sum())
        assert in_support < 15_000
        res_drop = exhaustive_multinomial_gof(obs_f, sex_f.weights, min_expected=5.0)
        assert res_drop.p_value < 1e-12
        assert res_drop.tvd > 0.25
```

In `tests/test_batch_parity.py`, replace the two `exp >= 5` truncation + `filtered_exp = [e * obs_total / exp_total ...]` blocks (`lines 40-60` and `117-135`) with `exhaustive_multinomial_gof`:

```python
from ptbr_sampler.sampling.validation import exhaustive_multinomial_gof

# State parity:
probs = np.array([w / total_weight for w in location_sampler.state_weights], dtype=np.float64)
obs = np.array([batched_states.get(s, 0) for s in location_sampler.state_names], dtype=np.int64)
res = exhaustive_multinomial_gof(obs, probs, min_expected=5.0)
assert res.p_value > 0.001, f'State distribution mismatch: chi2={res.chi2_stat:.2f}, p={res.p_value:.4f}'

# First-name parity:
labels = list(names_data.keys())
probs = np.array([names_data[k]['percentage'] / total_weight for k in labels], dtype=np.float64)
obs = np.array([batched_names.get(k, 0) for k in labels], dtype=np.int64)
res = exhaustive_multinomial_gof(obs, probs, min_expected=5.0)
assert res.p_value > 0.001, f'Name distribution mismatch: chi2={res.chi2_stat:.2f}, p={res.p_value:.4f}'
```

- [ ] **Step 2: Extend `scripts/audit_datasets.py` with Layer D cross-table coherence diagnostics**

Add `audit_cross_table_coherence(raw_dir: Path, parquet_dir: Path) -> dict[str, float]` to `scripts/audit_datasets.py` and include its output whenever `--parquet-dir` is passed:

```python
def audit_cross_table_coherence(raw_dir: Path, parquet_dir: Path) -> dict[str, float]:
    root_2022 = parquet_dir / 'census_year=2022'
    nat = pq.read_table(root_2022 / 'first_names' / 'scope=national' / 'part.parquet')
    states = pq.read_table(root_2022 / 'states' / 'part.parquet')
    by_decade = pq.read_table(raw_dir / 'name_by_decade.parquet')

    nat_w = dict(zip(nat['name'].to_pylist(), nat['weight'].to_pylist(), strict=True))
    total_pop = float(sum(states['population'].to_pylist()))
    uf_mix: dict[str, float] = defaultdict(float)
    for uf, pop in zip(states['abbreviation'].to_pylist(), states['population'].to_pylist(), strict=True):
        w_u = float(pop) / total_pop
        uf_tbl = pq.read_table(root_2022 / 'first_names' / f'uf={uf}' / 'part.parquet')
        for n, w in zip(uf_tbl['name'].to_pylist(), uf_tbl['weight'].to_pylist(), strict=True):
            uf_mix[str(n)] += w_u * float(w)

    vocab = sorted(set(nat_w) | set(uf_mix))
    tvd_uf_vs_nat = total_variation_distance(
        np.array([uf_mix.get(k, 0.0) for k in vocab]),
        np.array([nat_w.get(k, 0.0) for k in vocab]),
    )
    given_sum = float(sum(nat['count'].to_pylist()))
    decade_sum = float(sum(by_decade['frequency'].to_pylist()))
    return {
        'uf_weighted_vs_national_given_tvd': tvd_uf_vs_nat,
        'decade_sum_to_national_given_ratio': decade_sum / given_sum,
    }
```

- [ ] **Step 3: Run fast validation, slow validation, and audit report, then commit Task 6**

Run:
1. `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_distribution_validation.py -m "not slow" -v`
2. `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler/tests/test_distribution_validation.py /home/arthrod/workspace/ptbr-sampler/tests/test_batch_parity.py -v`
3. `uv run python -m scripts.audit_datasets --raw-dir /home/arthrod/workspace/ptbr-sampler/ptbr_sampler/data/raw/ibge_nomes_2022 --parquet-dir /home/arthrod/workspace/ptbr-sampler/ptbr_sampler/data/parquet`
Expected: All fast and slow statistical tests `PASS` (including both negative controls rejecting as required), and audit report prints clean conservation and TVD metrics.

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  tests/test_distribution_validation.py \
  tests/test_batch_parity.py \
  scripts/audit_datasets.py \
  docs/sources/ibge-nomes-2022-availability.md
git -C /home/arthrod/workspace/ptbr-sampler commit -m "test: replace flawed KS/top-50 checks with 4-layer statistical validation suite"
```

---

### Task 7: Deploy Runtime Datasets to Hugging Face Hub, Pin Manifest OID, Build `< 150 KiB` `0.3.0` Wheel, and Verify Fresh-Venv Runtime Fetch

**Files:**
- Modify: `ptbr_sampler/data/dataset_manifest.json`
- Modify: `docs/handoff-fetch-and-ingest.md`
- Modify: `docs/handoff-resume-with-claude.md`
- Modify: `CHANGELOG.md` (create if absent)

- [ ] **Step 1: Verify clean temporary Parquet rebuild and full test + lint suite**

Run:
1. `uv run python -m scripts.ingest_to_parquet --out /tmp/ptbr-clean-parquet-check`
2. `uv run --extra dev ruff check /home/arthrod/workspace/ptbr-sampler`
3. `uv run --extra test pytest /home/arthrod/workspace/ptbr-sampler -q`
Expected: Clean temporary rebuild succeeds with zero residual files, `ruff` passes cleanly, and full `pytest` suite passes.

- [ ] **Step 2: Publish runtime dataset bundle to Hugging Face Hub (`arthrod/ptbr-sampler-data`) and pin immutable 40-char commit OID in `dataset_manifest.json`**

Confirm Hugging Face Hub authentication (`HF_TOKEN` or cached token for `arthrod`), upload the verified runtime Parquet + geography bundle, and pin the exact returned commit SHA:

Run:
1. `uv run --extra dev python -m scripts.publish_hf_dataset --publish --repo-id arthrod/ptbr-sampler-data`
2. Verify `ptbr_sampler/data/dataset_manifest.json` has a 40-character hexadecimal `hf_revision` (`python -c "import json, re; m=json.load(open('ptbr_sampler/data/dataset_manifest.json')); assert re.fullmatch(r'[0-9a-f]{40}', m['hf_revision']), m['hf_revision']; print(m['hf_repo_id'], m['hf_revision'], len(m['artifacts']))"`).

- [ ] **Step 3: Build `ptbr_sampler-0.3.0-py3-none-any.whl` and assert `< 150 KiB` ultra-slim wheel budget**

Run:
1. `rm -rf /tmp/ptbr-wheel-check && uv build --dir /home/arthrod/workspace/ptbr-sampler --out-dir /tmp/ptbr-wheel-check`
2. Assert wheel size and manifest-only data payload:
```bash
python - <<'PY'
from pathlib import Path
import zipfile

whls = list(Path('/tmp/ptbr-wheel-check').glob('ptbr_sampler-0.3.0-*.whl'))
assert len(whls) == 1, whls
whl = whls[0]
size_bytes = whl.stat().st_size
assert size_bytes < 150 * 1024, f'Wheel exceeded 150 KiB slim budget: {size_bytes} bytes'

with zipfile.ZipFile(whl) as zf:
    names = set(zf.namelist())
assert 'ptbr_sampler/data/dataset_manifest.json' in names
data_entries = sorted(n for n in names if n.startswith('ptbr_sampler/data/'))
assert data_entries == ['ptbr_sampler/data/dataset_manifest.json'], f'Unexpected bundled data in wheel: {data_entries}'
assert not any(n.startswith('ptbr_sampler/tests/') for n in names)
print(f'Verified ultra-slim wheel: {whl.name} ({size_bytes / 1024:.1f} KiB), data_entries={data_entries}')
PY
```

- [ ] **Step 4: Install the slim `.whl` in a clean isolated virtualenv outside the repo and verify live Hugging Face runtime download, SHA-256 caching, and offline cache reuse**

Run from `/tmp` so local repository files cannot be touched:
```bash
rm -rf /tmp/ptbr-fresh-venv /tmp/ptbr-fresh-cache
uv venv /tmp/ptbr-fresh-venv
uv pip install --python /tmp/ptbr-fresh-venv/bin/python /tmp/ptbr-wheel-check/ptbr_sampler-0.3.0-py3-none-any.whl

# 1. Cold cache status shows remote-hf before first draw:
PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr datasets status --census-year 2022

# 2. Default Census 2022 generation lazily downloads ONLY touched partitions + geography from Hugging Face:
(cd /tmp && PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr generate --qty 3)
(cd /tmp && PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr generate --qty 3 --sex-conditioning F)
(cd /tmp && PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr generate --qty 3 --sex-conditioning population)
(cd /tmp && PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr generate --qty 3 --uf-conditioning --sex-conditioning F --conditioning-mode estimated)

# 3. Warm cache works strictly offline (PTBR_SAMPLER_OFFLINE=1) and passes full SHA-256 verification:
(cd /tmp && PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache PTBR_SAMPLER_OFFLINE=1 /tmp/ptbr-fresh-venv/bin/ptbr generate --qty 3)
PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr datasets status --census-year 2022 --verify

# 4. Historical Census 2010 opt-in also fetches lazily on demand:
(cd /tmp && PTBR_SAMPLER_CACHE_DIR=/tmp/ptbr-fresh-cache /tmp/ptbr-fresh-venv/bin/ptbr generate --qty 2 --census-year 2010)
```

- [ ] **Step 5: Record final discrepancy ledger, Hugging Face revision OID, `< 150 KiB` wheel size, and `0.3.0` release notes in `CHANGELOG.md` and handoff docs**

Update `CHANGELOG.md`, `docs/handoff-fetch-and-ingest.md`, and `docs/handoff-resume-with-claude.md` with:
- `v0.3.0` breaking/default notes: `census_year=2022` (`TimePeriod.ALL`) is now the default (`census_year=2010` preserved via explicit `--census-year 2010` / `census_year=2010`).
- Hugging Face Dataset Hub Coordinates (`arthrod/ptbr-sampler-data`, immutable 40-char `hf_revision`), `source_manifest.json` SHA-256 digests (`olob0/ibge-nomes-no-brasil-2022` @ `05efb85c92af43da2ed4ed088d1e0c9f17160e65`), exact `< 150 KiB` `.whl` byte count, Gemini `count=0` metadata fix, and 4-layer statistical validation metrics.

```bash
git -C /home/arthrod/workspace/ptbr-sampler add \
  ptbr_sampler/data/dataset_manifest.json \
  CHANGELOG.md docs/handoff-fetch-and-ingest.md docs/handoff-resume-with-claude.md
git -C /home/arthrod/workspace/ptbr-sampler commit -m "chore(release): pin Hugging Face dataset revision and finalize 0.3.0 release notes"
```

---

## Deliberately Deferred Work

- **No municipality-scale partitions:** Municipality tables (`5,570` localities, `< 10` threshold) would multiply remote partition counts by orders of magnitude for sparse, heavily censored tails.
- **No Cartesian `UF × cohort × sex` pre-materialization:** Lazy in-memory Bayes multiplication + LRU caching delivers identical `estimated` distributions in `< 5 ms` with `0 B` of extra Hugging Face repo or cache storage.
- **No LLM reclassification on Census 2022:** Directly observed IBGE 2022 sex counts cover `99.8207%` of national given-name mass; the remaining `0.18%` is explicitly tracked as disclosure-suppressed rather than guessed by a language model.
- **No surname co-occurrence or newborn-blend modeling in this plan:** Surname slot weights ($q_s$) and duplicate-stem prevention are documented as an explicit composition approximation; middle-name `30.99%` incidence retains its authorial provenance label.

## Completion Criteria

1. Package version is bumped to **`0.3.0`** across `pyproject.toml`, `ptbr_sampler/__init__.py`, user-agent headers, and `dataset_manifest.json`, with **Census 2022 (`census_year=2022`, `TimePeriod.ALL`)** as the primary default across Python (`sample()`, `BrazilianNameSampler.from_parquet()`, `BrazilianNameSampler.from_bundled_parquet()`) and CLI (`ptbr generate`), while `census_year=2010` remains an explicit historical opt-in.
2. All five pinned `olob0/ibge-nomes-no-brasil-2022` Parquet files (`05efb85c92af43da2ed4ed088d1e0c9f17160e65`) download reproducibly with HTTPS host allowlisting, SHA-256 verification, and `source_manifest.json`, and ingest into compact `float64`-normalized 1D observed partitions (`parquet/census_year=2022/`, `< 13 MiB`).
3. Runtime datasets are published to Hugging Face Hub (`arthrod/ptbr-sampler-data`) and pinned by an immutable 40-character commit OID + per-file SHA-256 digests in `ptbr_sampler/data/dataset_manifest.json`; the built `ptbr_sampler-0.3.0-py3-none-any.whl` is **`< 150 KiB`**, carries **zero** heavy `.parquet`/`.json` payloads, downloads only touched artifacts lazily into `~/.cache/ptbr-sampler/<hf_revision>/` under cross-process locks, strips `Authorization` headers across cross-origin CDN redirects, and supports `ptbr datasets status|prefetch|clear-cache` plus `PTBR_SAMPLER_OFFLINE=1`.
4. Birth cohorts align without the 10-year endpoint-vs-start shift (`decade=2000 -> ate2010`, `decade=2010 -> ate2020`, `decade=2020 -> 2020_2022`, `decade=1930 -> ate1940`), unobserved joint queries fail fast in `'strict'` mode and reweight lazily in `'estimated'` mode, and observed counts, exact-zero deductions, `< 20` / `< 15` suppressed cells, Bayes estimates, and legacy LLM gap-fills remain strictly separated.
5. Four-layer statistical validation (`Layer A` conservation, `Layer B` exact $O(M)$ alias reconstruction, `Layer C` exhaustive tail-pooled $\chi^2$ + Holm–Bonferroni + negative controls, `Layer D` cross-table coherence) passes end-to-end alongside the full test suite and isolated fresh-venv wheel smoke test.

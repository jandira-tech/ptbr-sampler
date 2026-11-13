# IBGE Census 2022 (`olob0/ibge-nomes-no-brasil-2022`) Empirical Availability & Discrepancy Ledger

## Pinned Upstream Compilation

`ptbr-sampler` `0.3.0` ingests IBGE Census 2022 given-name and surname tables from Gabriel Lobo's reproducible Parquet compilation [`olob0/ibge-nomes-no-brasil-2022`](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022) at immutable Hugging Face revision `05efb85c92af43da2ed4ed088d1e0c9f17160e65` (`8,630,643` bytes across 5 Parquet files):

| File | Bytes | Rows | SHA-256 | Observed Grain |
| --- | ---: | ---: | --- | --- |
| `name_ranking.parquet` | `1,738,567` | `330,059` | `635691d3ce52eb59c242ecb886dbaab62b4b42e6bed4b4f1766f8c6725636c64` | National given (`128,458`, sum `190,383,184`) + surname (`201,601`, sum `333,496,261`) |
| `name_detail.parquet` | `2,250,879` | `330,058` | `91518f2d0d1da8e438ab9f557127da06633e186914aecb717f1bbf7bfb6b2943` | National sex counts (`male_count`, `female_count`) + `median_age`; missing `('perl', 'surname')` due to IBGE WAF rule |
| `name_by_decade.parquet` | `910,784` | `221,524` | `9f852814bf42a47358841c054a70939c763c4fc70c7e38564ad44fb94b7fbdef` | National 2022 birth-cohort survivor counts (`decade` in `{1930, 1940, ..., 2020}`, sum `186,340,745`) |
| `name_by_state.parquet` | `3,729,128` | `828,567` | `5588f012d43bb38b07691044010eb7e96cb2bfc359dd3b53a6c3b0ea46f1504e` | UF given (`379,474`) + UF surname (`449,093`) across IBGE UF codes `11..53` |
| `state.parquet` | `1,285` | `27` | `5d4aa2a4faf4cdef421f2563de63cd8298b58113779774045a29b9e13ddebc55` | 2022 Census UF resident denominators (`sum = 203,080,756`) |

## Disclosure Thresholds (`IBGE Liv102228`)

Per [IBGE Technical Note Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf), cells are suppressed strictly below:
- **`< 20`** nationally and national-by-birth-decade (`name_ranking`, `name_detail`, `name_by_decade`),
- **`< 15`** per UF (`name_by_state`),
- **`< 10`** per municipality (not ingested in `ptbr-sampler` `0.3.0`).

Exact unrounded `100 * sum(frequency) / 203,080,756` equals `93.7475%` (`190,383,184 / 203,080,756`) for given names (because `6.2525%` = `12,697,572` residents carry names with national frequency `< 20`) and `164.2185%` (`333,496,261 / 203,080,756`) for surnames (because residents carry an average of `1.6422` recorded surname tokens), whereas summing upstream's 4-decimal-rounded `name_ranking.percentage` column directly yields `92.3126%` (given names) and `161.9529%` (surnames) due to tail rounding truncation. Sampling weights are therefore never read from `percentage` and are always normalized directly from integer `frequency` in `float64` using `math.fsum`.

## Four-Regime Sex-Cell Conservation Breakdown (`name_detail`)

Across all `128,458` national given names (`190,383,184` occurrences):

| Censoring regime | Distinct names | Mass / Residual | Handling in `ptbr-sampler` `0.3.0` |
| --- | ---: | ---: | --- |
| `both_observed` ($N_M \ge 20, N_F \ge 20$) | `10,582` | $N - (N_M + N_F) = 0$ identically | Exact empirical rates $p_M = N_M / N, p_F = N_F / N$ |
| `one_null_exact_zero` ($N - N_{\text{obs}} = 0$) | `55,210` | `0` residual | Deduced exact zero for opposite sex ($p_{\text{obs}} = 1.0, p_{\text{null}} = 0.0$) |
| `one_null_suppressed_positive` ($1 \le N - N_{\text{obs}} \le 19$) | `57,941` | `232,758` suppressed occurrences (`0.1223%`) | Observed sex keeps exact rate $N_{\text{obs}} / N < 1.0$; suppressed cell stays `None` / `NaN` (never imputed) |
| `both_null_suppressed` ($20 \le N \le 38$, both $< 20$) | `4,725` | `108,522` occurrences (`0.0570%`) | Retained in unconditioned national table; excluded (`NaN`) from sex-conditioned tables |

Directly observed sex counts (`male_count`: `60,954` names / `92,287,140` occurrences; `female_count`: `73,361` names / `97,754,764` occurrences) cover **`99.8207%`** (`190,041,904 / 190,383,184`) of published national given-name mass without any LLM gap-fill.

## Empirical Capability Matrix (`strict` vs `estimated`)

| Conditioning request (`census_year=2022`) | Observed in IBGE 2022? | `conditioning_mode='strict'` (default) | `conditioning_mode='estimated'` (opt-in) |
| --- | :---: | --- | --- |
| National whole-census (`TimePeriod.ALL`) | Yes | Served from `first_names/scope=national` | Served from `first_names/scope=national` |
| National by sex (`sex in {'M', 'F', 'mixed', 'population'}`) | Yes | Served from `first_names/sex={M,F}` | Served from `first_names/sex={M,F}` |
| National by birth cohort (`ate1940..2020_2022`) | Yes | Served from `first_names/period=<p>` | Served from `first_names/period=<p>` |
| UF whole-census (`uf=<UF>`, `sex=None`, `TimePeriod.ALL`) | Yes | Served from `first_names/uf=<UF>` + `surnames/uf=<UF>` | Served from `first_names/uf=<UF>` + `surnames/uf=<UF>` |
| `UF x sex` (`TimePeriod.ALL`) | No (1D marginals only) | Raises `ValueError` | Lazy Bayes reweighting with national `sex_prior` |
| `cohort x sex` (`uf=None`) | No (1D marginals only) | Raises `ValueError` | Lazy Bayes reweighting with national `sex_prior` |
| `UF x cohort` (with or without `sex`) | No | Raises `ValueError` | Raises `ValueError` (UF age structures vary) |
| `TimePeriod.UNTIL_1930` (`ate1930`) | Merged into `decade=1930` (`ate1940`) | Raises `ValueError` (use `ate1940` or `census_year=2010`) | Raises `ValueError` |

## Birth-Cohort Endpoint vs Decade-Start Alignment

Legacy 2010 `names_data.json` labels cohorts by upper endpoint (`ate2010` = born `2000-2009`), whereas `olob0` `name_by_decade.parquet` labels cohorts by decade start (`decade=2000` = born `2000-2009`; `decade=1930` = `<= 1939` with `2,541,671` survivors). Pairwise TVD confirms `TVD(2010 ate2010, 2022 decade=2000) = 0.133` (`Enzo`: `0.144%` vs `0.139%`), whereas comparing `2010 ate2010` against `2022 decade=2010` jumps `Enzo` to `1.079%`. Ingestion maps `1930 -> ate1940`, ..., `2000 -> ate2010`, `2010 -> ate2020`, and `2020 -> 2020_2022`.

## Discrepancy Ledger

1. **`('perl', 'surname')` absent from `name_detail.parquet`:** Present in `name_ranking.parquet` (`frequency=24`), blocked on IBGE's detail endpoint by an upstream WAF rule matching `/perl`. Tolerated explicitly in `scripts/audit_datasets.py`; surnames do not use `name_detail` sex counts.
2. **Diacritics stripped upstream by IBGE:** Official IBGE Nomes strings fold diacritics (`Joao`, `Goncalves`) while preserving distinct orthographic spellings (`Ana` vs `Anna`, `Luis` vs `Luiz`). `ptbr-sampler` Title-Cases display tokens without inventing heuristic accents.
3. **Surname token-slot share vs person-level presence:** `Silva` accounts for `34,030,104 / 203,080,756 = 16.76%` of residents, and `34,030,104 / 333,496,261 = 10.2040%` of recorded surname token slots. In 2-surname mode (`with_only_one_surname=False`), `census_year=2022` resamples slot 2 conditional on $s_2 \neq s_1$ to prevent duplicate stems (`"Silva Silva"`).

## Cross-Table Coherence Diagnostics (`scripts.audit_datasets --parquet-dir`)

- **Population-weighted UF mixture vs national given-name marginal:** $\text{TVD}(\sum_u w_u P(\cdot \mid u), P_{\text{nat}}) = 0.030919$ (`3.09%`), bounded strictly by per-UF `< 15` disclosure suppression across the 27 federative units.
- **Birth-cohort sum vs national given-name count sum:** `186,340,745 / 190,383,184 = 0.978767` (`97.88%`), with the `2.12%` difference accounted for by per-decade `< 20` cell suppression across the 10 birth-decade cohorts.


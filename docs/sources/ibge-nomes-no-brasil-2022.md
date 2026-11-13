# IBGE — Nomes no Brasil, 2022 Census release (November 2025)

**Publisher:** Instituto Brasileiro de Geografia e Estatística (IBGE).
**Release date:** 4 November 2025.
**Data reference date:** 1 August 2022 (`N_pop = 203,080,756` residents in the 2022 Census household register).
**Methodology note:** [IBGE Technical Note Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf).
**Relevance for `ptbr-sampler` `0.3.0`:** primary empirical source for the default `census_year=2022` first-name, surname, sex-prior, and UF tables.

## Official dissemination vs. pinned Parquet mirror

IBGE's *Nomes no Brasil* 2022 portal (<https://censo2022.ibge.gov.br/nomes/>) is backed by undocumented internal v3 web-application endpoints rather than a SIDRA bulk table or a formally versioned open-data CSV/Parquet dump (and its edge WAF blocks literal substrings such as `perl`, omitting the single surname key `('perl', 'surname')` from detail lookups).

However, **a complete, reproducible public Parquet compilation exists**: Gabriel Lobo's [`olob0/ibge-nomes-no-brasil-2022`](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022), pinned in `ptbr-sampler` at immutable commit `05efb85c92af43da2ed4ed088d1e0c9f17160e65` (`5` Parquet files, `8.23 MiB` total; full hashes and schemas in [`docs/sources/ibge-nomes-2022-availability.md`](ibge-nomes-2022-availability.md)). `python -m scripts.download_datasets --fetch-ibge-2022` fetches and SHA-256-verifies this exact snapshot, and `arthrod/ptbr-sampler-data` distributes the ingested runtime partitions on Hugging Face Hub.

## Confidentiality suppression thresholds (Liv102228)

Per [IBGE Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf), small cells are suppressed for statistical confidentiality at **decreasing** thresholds for finer geographic scopes:

| Geographic / tabular grain | Suppression rule | Published cells |
| --- | --- | --- |
| Brazil national (`name_ranking`, `name_detail`) | Suppressed when count `< 20` | `>= 20` |
| Brazil national by birth decade (`name_by_decade`) | Suppressed when count `< 20` | `>= 20` |
| Federation Unit / UF (`name_by_state`) | Suppressed when count `< 15` | `>= 15` |
| Municipality | Suppressed when count `< 10` | `>= 10` |

Note that regional thresholds (`< 15` per UF, `< 10` per municipality) are **lower**, not higher, than the national `< 20` threshold.

## Key statistics & surname token-slot vs. presence distinction

| Metric | Value | Notes |
| --- | ---: | --- |
| Resident population (`state.parquet`) | `203,080,756` | Exact 2022 Census denominator |
| Distinct given names (`>= 20` nationally) | `128,458` | Covers `190,383,184` residents (`93.7475%` of population) |
| Distinct surnames (`>= 20` nationally) | `201,601` | Sums to `333,496,261` surname tokens (`~1.6422` tokens/person) |
| `Silva` — person-level population presence | `16.76%` | `34,030,104 / 203,080,756` residents carry `Silva` in any position |
| `Silva` — single-slot token share ($q_{\text{Silva}}$) | `10.2040%` | `34,030,104 / 333,496,261` normalized over surname occurrences |
| `Santos` — single-slot token share ($q_{\text{Santos}}$) | `6.4071%` | `21,367,475 / 333,496,261` normalized over surname occurrences |
| Regional surname concentration (person presence) | Sergipe `Santos` `43.38%`, Alagoas `Silva` `35.75%`, Pernambuco `Silva` `34.23%` | Captured by `census_year=2022/surnames/uf=<UF>/part.parquet` |

Because `name_ranking.percentage` divides by `203,080,756` (`93.7475%` sum for given names; `161.9529%` sum for surnames), `scripts/ingest_to_parquet.py` always normalizes sampling weights in `float64` (`math.fsum`) directly from integer `frequency` over observed support. In two-surname mode (`with_only_one_surname=False`), `census_year=2022` resamples slot 2 conditional on $s_2 \neq s_1$ so identical stems (`"Silva Silva"`) are never emitted.

## Birth-cohort alignment (decade start vs. legacy 2010 upper endpoint)

In `name_by_decade.parquet`, `decade` is an `int16` marking the **start** of the birth decade (`1940` = `1940–1949`, ..., `2000` = `2000–2009`, `2010` = `2010–2019`, `2020` = `2020–1 Aug 2022`), with `decade=1930` (`2,541,671` survivors) merging `< 1930` and `1930–1939`. Legacy 2010 `names_data.json` labeled cohorts by **upper endpoint** (`ate2010` = `2000–2009`, aligning with 2022 `decade=2000`, *not* `decade=2010`). `ptbr-sampler` `0.3.0` maps:

- `TimePeriod.ALL` (`'all'`) → full 2022 resident stock (**default** when `census_year=2022`)
- `TimePeriod.UNTIL_1940`..`TimePeriod.UNTIL_2010` → 2022 `decade=1930`..`2000`
- `TimePeriod.UNTIL_2020` (`'ate2020'`) → 2022 `decade=2010` (`2010–2019`)
- `TimePeriod.PERIOD_2020_2022` (`'2020_2022'`) → 2022 `decade=2020` (`2020–1 Aug 2022`)
- `TimePeriod.UNTIL_1930` (`'ate1930'`) → legacy `census_year=2010` only (`ValueError` in `2022`).

## Sex-coverage taxonomy & exact conservation in `name_detail`

Instead of a single ambiguous "coverage %" claim, `ptbr-sampler` reports five distinct sex-coverage metrics across the `128,458` given names (`190,383,184` total occurrences):

1. **Vocabulary lookup coverage:** `123,733 / 128,458` (`96.32%`) distinct given-name types have at least one observed sex count (`65,792` exact + `57,941` partial); `4,725` rare types (`20 <= N <= 38`) have both sex cells suppressed.
2. **Directly observed empirical mass:** `190,041,904 / 190,383,184` = **`99.8207%`** (`60,954` male rows totaling `92,287,140`; `73,361` female rows totaling `97,754,764`).
3. **Deduced exact-zero mass:** **`55,210`** single-null given names satisfy $N - N_{\text{obs}} = 0$ identically (`one_null_exact_zero`), proving deductively that the opposite-sex count is `0` (`p_obs = 1.0`, `p_null = 0.0`).
4. **LLM-assigned uncalibrated mass:** **`0.0%`** in `census_year=2022` (LLM gap-fill is confined to legacy `census_year=2010`).
5. **Suppressed / excluded mass:** **`341,280`** occurrences (**`0.1793%`** of national given-name mass), comprising `232,758` residual occurrences across `57,941` `one_null_suppressed_positive` names ($1 \le N - N_{\text{obs}} \le 19$) plus `108,522` occurrences across `4,725` `both_null_suppressed` names.

In `conditioning_mode='strict'` (the `0.3.0` default), only observed marginals (`national`, `national × sex`, `national × cohort`, `UF`) are served; joint `UF × sex` and `cohort × sex` require explicit `conditioning_mode='estimated'` (lazy in-memory Bayes conditional independence using $\hat{p}_{\text{obs}}(i) = N_{i,\text{obs}} / N_i$).

## Access paths

- Interactive portal: <https://censo2022.ibge.gov.br/nomes/> / <https://www.ibge.gov.br/apps/nomes/>
- Technical Note Liv102228 (PDF): <https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf>
- Pinned Parquet mirror: <https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022> (`05efb85c92af43da2ed4ed088d1e0c9f17160e65`)
- Runtime dataset bundle: <https://huggingface.co/datasets/arthrod/ptbr-sampler-data>
- Availability & discrepancy ledger: [`docs/sources/ibge-nomes-2022-availability.md`](ibge-nomes-2022-availability.md)

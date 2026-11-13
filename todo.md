# Statistical Audit & `0.3.0` Methodology Checklist

Reconciled status for `ptbr-sampler` `0.3.0` against `deep-research-report(4).md`, [IBGE Technical Note Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf), and the pinned Census 2022 compilation (`olob0/ibge-nomes-no-brasil-2022` @ `05efb85c92af43da2ed4ed088d1e0c9f17160e65`).

---

## Completed / Addressed in `0.3.0`

1. **[x] Reproducible Census 2022 download + `float64` Parquet ingestion (`scripts/download_datasets.py`, `scripts/ingest_to_parquet.py`)**
   - `--fetch-ibge-2022` downloads and SHA-256-verifies all 5 upstream Parquet tables (`8.23 MiB`); ordinary reruns validate cached files and skip valid ones while `--overwrite` forces re-download.
   - `ingest_ibge_2022` writes `parquet/census_year=2022/` atomically in `pa.float64()` normalized with `math.fsum`.

2. **[x] Ultra-slim wheel (`< 150 KiB`) + Hugging Face runtime dataset hub (`ptbr_sampler/datasets.py`, `scripts/publish_hf_dataset.py`)**
   - Heavy Parquet and JSON payloads are excluded from the wheel; only `ptbr_sampler/data/dataset_manifest.json` ships in `.whl`, resolving partitions lazily from `arthrod/ptbr-sampler-data` (or `PTBR_SAMPLER_DATA_DIR` / local git checkout) with `ptbr datasets prefetch|status|clear-cache` and `PTBR_SAMPLER_OFFLINE=1`.

3. **[x] Census 2022 (`census_year=2022`, `TimePeriod.ALL`) promoted to primary default; `census_year=2010` preserved as opt-in**
   - Extends cohorts with `TimePeriod.ALL`, `TimePeriod.UNTIL_2020` (`2010–2019`), and `TimePeriod.PERIOD_2020_2022` (`2020–1 Aug 2022`), aligning legacy upper-endpoint keys (`ate2010` = `2000–2009`) with 2022 decade-start integers (`decade=2000`).

4. **[x] Exact Liv102228 disclosure-threshold & sex-censoring accounting (`< 20` national/decade, `< 15` UF, `< 10` municipality)**
   - Distinguishes `both_observed` (`10,582`), `one_null_exact_zero` (`55,210`), `one_null_suppressed_positive` (`57,941`, residual `232,758`), and `both_null_suppressed` (`4,725`, mass `108,522`). Directly observed empirical sex mass is `99.8207%` (`0.0%` LLM mass in 2022; legacy 2010 Gemini rows store `count_* = 0`).

5. **[x] Strict observed marginals vs. lazy Bayes conditional estimation (`conditioning_mode='strict' | 'estimated'`)**
   - `strict` serves only observed marginals (`national`, `national × sex`, `national × cohort`, `UF`) with zero silent condition dropping; `estimated` builds `UF × sex` (`time_period=ALL`) and `cohort × sex` (`uf=None`) lazily in memory, while rejecting `UF × cohort`.

6. **[x] Regional UF-conditioned surnames, `top_40` slicing, and distinct two-slot surname draws**
   - `census_year=2022` routes UF-conditioned surname draws to `census_year=2022/surnames/uf=<UF>/part.parquet`, slices `top_40=True` via `AliasTable.top_k(40)`, documents token-slot share ($q_{\text{Silva}} = 10.2040\%$) vs. person-level presence (`16.76%`), and resamples slot 2 when $s_2 = s_1$.

7. **[x] Four-layer statistical validation (`ptbr_sampler/sampling/validation.py`, `tests/test_distribution_validation.py`, `scripts/audit_datasets.py`)**
   - Replaces permutation-sensitive `ks_2samp` and rescaled top-50 truncation with exact $O(M)$ alias probability reconstruction, exhaustive tail-pooled multinomial $\chi^2$ ($E_j \ge 5$) with Holm–Bonferroni FWER control, and negative controls.

---

## Remaining Open Assumptions (Documented, Not Overclaimed)

- **Observed multi-axis Census 2022 joints (`UF × sex`, `cohort × sex`, `UF × cohort`):** IBGE's public *Nomes no Brasil* 2022 dissemination exposes 1D/2D marginals rather than full cross-tabulated microdata cubes; `UF × cohort` remains unsupported unless derived from restricted/raw microdata (`censobr`).
- **Mixed reference dates (`2022` names vs. `2024` geography):** Names reflect 1 August 2022 Census resident stock (`203,080,756`), whereas municipal/UF location weights reflect 1 July 2024 IBGE population estimates (`212.6M`).
- **Orthographic diacritic folding in IBGE 2022:** Upstream IBGE 2022 tables fold diacritics (`Joao`, `Goncalves`) while keeping distinct letter spellings (`Ana`/`Anna`, `Luis`/`Luiz`); `ptbr-sampler` does not heuristically guess accents.
- **Authorial middle names & surname connectives:** `middle_names.json` (`percentage_with_second = 30.99%`, cleaned via `vocabulary.py`) and `SURNAME_PREFIXES` (`da`, `de`, `dos`) remain civil-registry/authorial conventions outside IBGE's first-name-only scope.

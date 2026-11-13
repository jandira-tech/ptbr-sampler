# Handoff — `ptbr-sampler` `0.3.0` Dataset & Release Status

This document records the reconciled `0.3.0` state for maintainers or coding agents resuming work on `ptbr-sampler`, replacing the obsolete `0.2.x` off-sandbox `servicodados.ibge.gov.br` handoff checklist.

---

## 1. Current `0.3.0` Architecture & Data State

- **Default vintage:** `census_year=2022` (`TimePeriod.ALL`, `conditioning_mode='strict'`) across `sample()`, `BrazilianNameSampler.from_parquet()`, `BrazilianNameSampler.from_bundled_parquet()`, and `ptbr generate`. Historical `census_year=2010` (`TimePeriod.UNTIL_2010`) remains available as an explicit opt-in (`--census-year 2010`).
- **Upstream Census 2022 source:** [`olob0/ibge-nomes-no-brasil-2022`](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022) pinned at `05efb85c92af43da2ed4ed088d1e0c9f17160e65` (`5` Parquet files, `8,630,643` bytes; SHA-256 digests verified in `scripts/download_datasets.py` and `scripts/audit_datasets.py`).
- **Runtime dataset delivery (`< 150 KiB` wheel):** Heavy Parquet and JSON payloads are excluded from the built wheel via `[tool.uv.build-backend]` `wheel-exclude` (`ptbr_sampler-0.3.0-py3-none-any.whl` is `~100 KiB`, `< 150 KiB`). Only `ptbr_sampler/data/dataset_manifest.json` ships in the wheel (`195` artifacts pinned at [`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data) @ `c30ef6ac3dbf2d1508e41dce7b6a6e47d8e6dbde`); `ptbr_sampler/datasets.py` resolves partitions lazily from `PTBR_SAMPLER_DATA_DIR`, a local repo checkout, or `~/.cache/ptbr-sampler/<hf_revision>/`.
- **RNG injection, `Faker` integration, & MIT licensing:** Every sampler and utility accepts `rng=random.Random(...)` without mutating global `random` or `numpy.random` state; caches are synchronized with `threading.RLock`; `ptbr_sampler.faker` (`PTBRProvider`, `install_ptbr(fake, aliases=False)`) ships behind the `[faker]` extra; `uf=` / `--uf` filters names, surnames, cities, CEPs, DDDs, and RGs consistently; and the software is licensed under MIT (`LICENSE`) paired with `THIRD_PARTY_NOTICES.md`.
- **Statistical validation & metadata integrity:** Four-layer validation suite (`tests/test_distribution_validation.py`, `scripts/audit_datasets.py`) verifies exact `pa.float64` probability vectors, exact Vose alias reconstruction (`L_inf < 1e-14`), exhaustive multinomial GoF with Holm-Bonferroni FWER (`alpha=0.001`), negative controls, and Layer D cross-table coherence (`uf_weighted_vs_national_given_tvd = 0.030919`, `decade_sum_to_national_given_ratio = 0.978767`). Legacy 2010 `data_origin.json` metadata counts `count=0` Gemini rows as `gemini_classified` (`unmatched_names=0`, `coverage_pct=100.0`).

---

## 2. Verification Commands When Resuming a Session

```bash
# 1. Verify raw Census 2022 cache (skips valid files; use --overwrite to force re-download)
uv run python -m scripts.download_datasets --fetch-ibge-2022

# 2. Rebuild Parquet partitions and inspect statistical audit summary
uv run python -m scripts.ingest_to_parquet
uv run python -m scripts.audit_datasets \
  --raw-dir ptbr_sampler/data/raw/ibge_nomes_2022 \
  --parquet-dir ptbr_sampler/data/parquet

# 3. Check runtime dataset manifest / cache health
uv run ptbr datasets status --verify
uv run ptbr sources --census-year 2022

# 4. Run lint and test suite (including slow Monte Carlo GoF if validating statistical changes)
uv run ruff check
uv run pytest -n auto -q
```

---

## 3. Key Invariants & Documented Assumptions Not to Regress

1. **Liv102228 confidentiality thresholds:** `< 20` nationally and national-by-decade, `< 15` per UF, `< 10` per municipality. Never treat IBGE 2022 `NULL` sex counts as observed zeros unless $N - N_{\text{obs}} = 0$ (`55,210` `one_null_exact_zero` names), and never impute `< 20` counts on the `57,941` `one_null_suppressed_positive` names (`232,758` residual occurrences) or `4,725` `both_null_suppressed` names (`108,522` occurrences).
2. **Observed vs. estimated conditioning:** Keep `conditioning_mode='strict'` free of unobserved joint assumptions; keep `conditioning_mode='estimated'` restricted to lazy in-memory `UF × sex` (`time_period=ALL`) and `cohort × sex` (`uf=None`), while rejecting `UF × cohort`.
3. **10-year cohort convention:** Legacy `ate2010` (`2000–2009`) aligns with `olob0` `decade=2000`, whereas `olob0` `decade=2010` maps to `TimePeriod.UNTIL_2020` (`'ate2020'`) and `decade=2020` maps to `TimePeriod.PERIOD_2020_2022` (`'2020_2022'`).
4. **Surname slot vs. presence:** National `Silva` token-slot probability is $q_{\text{Silva}} = 34,030,104 / 333,496,261 = 10.2040\%$ (`16.76%` is person-level presence across `~1.6422` tokens/person); two-surname mode in `2022` resamples slot 2 when $s_2 = s_1$.
5. **Mixed reference dates & authorial components:** Names default to 1 August 2022 Census stock (`203.08M`), geography uses 1 July 2024 IBGE municipal estimates (`212.6M`), and `middle_names.json` (`30.99%`) plus `SURNAME_PREFIXES` remain authorial/civil-registry conventions.

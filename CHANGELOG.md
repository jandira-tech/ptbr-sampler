# Changelog

All notable changes to `ptbr-sampler` are documented in this file.

## [0.3.0] - 2026-11-13

### Added
- **IBGE Censo Demográfico 2022 Default (`census_year=2022`):** Ingested 128,458 given names, 201,601 surnames, 9 birth cohorts (`ate1940`..`ate2020`, `2020_2022`) plus `TimePeriod.ALL`, 27 UF state marginals (`first_names/uf=*` and `surnames/uf=*`), national sex-specific given-name marginals (`sex=M`, `sex=F`), empirical 2022 sex-prior table (`both_observed`, `one_null_exact_zero`, `one_null_suppressed_positive`, `both_null_suppressed`), and 27-UF 2022 resident population (`203,080,756`) across 70 Census 2022 Parquet partitions (101 Parquet partitions total including historical 2010).
- **Runtime Dataset Delivery via Hugging Face Hub (`arthrod/ptbr-sampler-data`):** Pinned SHA-256 manifest (`ptbr_sampler/data/dataset_manifest.json` @ `c30ef6ac3dbf2d1508e41dce7b6a6e47d8e6dbde`, 195 runtime artifacts) with lazy per-artifact download, atomic multi-process caching (`PTBR_SAMPLER_CACHE_DIR`), strict offline mode (`PTBR_SAMPLER_OFFLINE=1`), and `ptbr datasets status | prefetch | clear-cache` CLI commands.
- **Ultra-Slim Wheel (`< 150 KiB`):** Stripped runtime Parquet and JSON payloads from wheel builds (`ptbr_sampler-0.3.0-py3-none-any.whl` is `94,409 bytes` / `92.2 KiB`, shipping only `ptbr_sampler/data/dataset_manifest.json` under `ptbr_sampler/data/`).
- **Explicit Conditioning Modes (`strict` vs `estimated`):** Strict mode (default) guarantees sampling only from directly observed IBGE tables; `conditioning_mode='estimated'` explicitly enables Bayes reweighting for unobserved 2022 `UF × sex` and `cohort × sex` combinations.
- **Four-Layer Statistical Validation Suite:** Exact probability vector and Vose alias-table reconstruction (`L_inf < 1e-14` via bulk C-level `math.fsum` hub absorption + Kahan compensation), exhaustive grouped multinomial Pearson GOF with Holm-Bonferroni FWER control (`alpha=0.001`), negative controls, and Layer D cross-table coherence auditing (`uf_weighted_vs_national_given_tvd = 0.030919`, `decade_sum_to_national_given_ratio = 0.978767`).

### Changed
- **Breaking Default Vintage:** `sample()`, `BrazilianNameSampler.from_parquet()`, `BrazilianNameSampler.from_bundled_parquet()`, and `ptbr generate` now default to `census_year=2022` (`TimePeriod.ALL`) and `conditioning_mode='strict'`. Pass `census_year=2010` (`--census-year 2010`) for legacy 2010 vintage reproduction.
- **True `float64` Ingestion:** Parquet weight columns now serialize as `pa.float64()` (`sum == 1.0` within `1e-12`) with staging-directory atomic swap.

### Fixed
- Corrected 2010 `data_origin.json` metadata reporting where `count=0` Gemini-classified rows were miscounted as unmatched rather than `gemini_classified` (`unmatched_names=0`, `coverage_pct=100.0`).
- Added third-party attribution and provenance documentation (`NOTICE.md`, `docs/sources/ibge-nomes-2022-availability.md`) for IBGE Censo Demográfico 2022, Gabriel Lobo (`olob0/ibge-nomes-no-brasil-2022`), and Álvaro Justen (`brasil.io/genero-nomes`, CC BY-SA 4.0).

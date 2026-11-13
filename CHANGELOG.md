# Changelog

All notable changes to `ptbr-sampler` are documented in this file.

## [0.3.0] - 2026-11-13

### Added
- **IBGE Censo Demográfico 2022 Default (`census_year=2022`):** Ingested 128,458 given names, 201,601 surnames, 9 birth cohorts (`ate1940`..`ate2020`, `2020_2022`) plus `TimePeriod.ALL`, 27 UF state marginals (`first_names/uf=*` and `surnames/uf=*`), national sex-specific given-name marginals (`sex=M`, `sex=F`), empirical 2022 sex-prior table (`both_observed`, `one_null_exact_zero`, `one_null_suppressed_positive`, `both_null_suppressed`), and 27-UF 2022 resident population (`203,080,756`) across 70 Census 2022 Parquet partitions (101 Parquet partitions total including historical 2010).
- **Runtime Dataset Delivery via Hugging Face Hub (`arthrod/ptbr-sampler-data`):** Pinned SHA-256 manifest (`ptbr_sampler/data/dataset_manifest.json` @ `c30ef6ac3dbf2d1508e41dce7b6a6e47d8e6dbde`, 195 runtime artifacts) with lazy per-artifact download, atomic multi-process caching (`PTBR_SAMPLER_CACHE_DIR`), read-only container mount support (`PTBR_SAMPLER_DATA_DIR`), strict offline mode (`PTBR_SAMPLER_OFFLINE=1`), and `ptbr datasets status | prefetch | clear-cache` CLI commands.
- **Ultra-Slim Wheel (`< 150 KiB`):** Stripped runtime Parquet and JSON payloads from wheel and sdist builds (`~100 KiB` `.whl`, shipping only `ptbr_sampler/data/dataset_manifest.json` under `ptbr_sampler/data/`).
- **First-Class `Faker` Provider (`ptbr_sampler.faker`, `[faker]` extra):** Added `PTBRProvider` and `install_ptbr(fake, aliases=False, ...)` exposing coherent demographic profiles (`ptbr_profile`) and $O(1)$ scalar formatters (`ptbr_name`, `ptbr_first_name`, `ptbr_first_name_female`, `ptbr_first_name_male`, `ptbr_middle_name`, `ptbr_surname`, `ptbr_state`, `ptbr_state_abbr`, `ptbr_city`, `ptbr_cep`, `ptbr_postcode`, `ptbr_street`, `ptbr_street_address`, `ptbr_neighborhood`, `ptbr_building_number`, `ptbr_address`, `ptbr_cpf`, `ptbr_pis`, `ptbr_cnpj`, `ptbr_cei`, `ptbr_rg`, `ptbr_phone`, `ptbr_phone_number`), preserving standard `Faker('pt_BR')` methods by default unless `aliases=True` is explicitly opted in, with full `Faker.seed()` / `fake.seed_instance()` determinism and multi-locale proxy support.
- **Isolated `random.Random` Injection (`rng=`) & Concurrency Safety:** Threaded `rng: random.Random | None = None` across `sample()`, `BrazilianNameSampler`, `BrazilianLocationSampler`, `PartitionStore`, `AliasTable`, `DocumentSampler`, `BrazilianRG`, and CPF/PIS/CNPJ/CEI/phone/address utilities without mutating module-global `random` or `numpy.random` state; synchronized `PartitionStore` and sampler caches with `threading.RLock`; added synchronous offline fast paths safe inside running `asyncio` event loops (Jupyter, FastAPI, marimo).
- **Fixed `uf=` / `--uf` Filtering & Rich CLI Output:** Pinning a Federation Unit (`sample(uf='SP')`, `ptbr generate --uf SP`) aligns given names, regional surnames, municipalities, CEPs, DDD area codes, and state-specific RG formats; `ptbr generate --format table` renders structured `rich.table.Table` output.
- **Explicit Conditioning Modes (`strict` vs `estimated`):** Strict mode (default) guarantees sampling only from directly observed IBGE tables; `conditioning_mode='estimated'` explicitly enables lazy in-memory Bayes reweighting for unobserved 2022 `UF × sex` and `cohort × sex` combinations.
- **Four-Layer Statistical Validation Suite:** Exact probability vector and Vose alias-table reconstruction (`L_inf = 1.39e-17 < 1e-14` via bulk C-level `math.fsum` hub absorption + Kahan compensation), exhaustive grouped multinomial Pearson GoF with Holm-Bonferroni FWER control (`alpha=0.001`), negative controls, and Layer D cross-table coherence auditing (`uf_weighted_vs_national_given_tvd = 0.030919`, `decade_sum_to_national_given_ratio = 0.978767`).
- **Documentation, ReadTheDocs, & Technical Monograph:** Reconciled bilingual `README.md` (PT-BR) and `README.en.md` (EN), authored `docs/technical-report.md` and bilingual data-science blog posts, and added `[docs]` optional dependencies (`mkdocs`, `mkdocs-material`, `pymdown-extensions`).

### Changed
- **Breaking Default Vintage:** `sample()`, `BrazilianNameSampler.from_parquet()`, `BrazilianNameSampler.from_bundled_parquet()`, and `ptbr generate` now default to `census_year=2022` (`TimePeriod.ALL`) and `conditioning_mode='strict'`. Pass `census_year=2010` (`--census-year 2010`) for legacy 2010 vintage reproduction.
- **MIT Software License & PyPI Metadata:** Standardized `LICENSE` and `pyproject.toml` under the MIT License (`Copyright (c) 2026 Jandira Tech`), paired with `THIRD_PARTY_NOTICES.md`, PyPI project URLs/classifiers, Python `>=3.12`, and `uv>=0.13.7` (`uv 0.13.8` in `uv.lock`).
- **True `float64` Ingestion:** Parquet weight columns now serialize as `pa.float64()` (`sum == 1.0` within `1e-12`) with staging-directory atomic swap.

### Fixed
- Corrected 2010 `data_origin.json` metadata reporting where `count=0` Gemini-classified rows were miscounted as unmatched rather than `gemini_classified` (`unmatched_names=0`, `coverage_pct=100.0`).
- Added third-party attribution and provenance documentation (`THIRD_PARTY_NOTICES.md`, `docs/sources/ibge-nomes-2022-availability.md`) for IBGE Censo Demográfico 2022, Gabriel Lobo (`olob0/ibge-nomes-no-brasil-2022`), Álvaro Justen (`brasil.io/genero-nomes`, CC BY-SA 4.0), Arpen-Brasil, Correios/ViaCEP, and Anatel.

---

## [0.2.0] - 2025-10-30

### Added
- Migrated package layout from `src/` to `ptbr_sampler/`, switched build backend to `uv_build`, and added the `ptbr` Typer CLI (`ptbr generate`, `ptbr sources`).
- Introduced `PartitionStore` + Apache Parquet partitions + vectorized Walker/Vose `AliasTable` (`ptbr_sampler/sampling/`), vocabulary sanitization (`vocabulary.py`), `random=True` uniform sampling mode, and IBGE 2010 sex conditioning via `brasil.io/genero-nomes` (`91.9%`) + Gemini `gemini-3.1-flash-lite-preview` (`8.1%`).

---

## [0.1.0] - 2025-02-15

### Added
- Initial prototype generating Brazilian names (IBGE 2010 Census JSON tables), municipalities/CEPs, offline addresses, phone numbers, and synthetic CPF/RG/PIS/CNPJ/CEI identifiers with async JSONL export.

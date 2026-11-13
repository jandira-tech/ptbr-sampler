# Data and sampling architecture (`ptbr-sampler` `0.3.0`)

`ptbr-sampler` `0.3.0` combines five design pillars so realistic Brazilian demographic sampling scales across `128,458` Census 2022 given names and `201,601` surnames without shipping an `80 MiB` wheel:

1. **Ultra-slim wheel (`< 150 KiB`) + pinned Hugging Face runtime dataset hub (`arthrod/ptbr-sampler-data`)**
2. **Versioned, 1D-marginal `float64` Parquet partitions** (`parquet/census_year=2022/` default + legacy `parquet/` for `census_year=2010`)
3. **Kahan-compensated Walker/Vose $O(1)$ vectorized alias tables** (`ptbr_sampler/sampling/alias.py`) wrapped in a thread-safe condition-keyed LRU (`PartitionStore`)
4. **Strict observed vs. lazy Bayes conditional estimation** (`conditioning_mode='strict' | 'estimated'`)
5. **Isolated `random.Random` stream determinism (`rng=`), `RLock` concurrency, & first-class `Faker` integration** (`ptbr_sampler/faker.py`)

---

## 1. Storage & Runtime Dataset Resolution

```text
ptbr_sampler/data/
├── dataset_manifest.json              # ONLY data file shipped inside the <150 KiB wheel (~16 KiB)
└── parquet/                           # Fetched lazily per partition into ~/.cache/ptbr-sampler/<hf_revision>/
    ├── census_year=2022/              # PRIMARY DEFAULT (IBGE Census 2022 @ 1 Aug 2022)
    │   ├── first_names/
    │   │   ├── scope=national/part.parquet
    │   │   ├── sex=<M|F>/part.parquet
    │   │   ├── period=<ate1940..ate2020|2020_2022>/part.parquet
    │   │   └── uf=<UF>/part.parquet
    │   ├── sex_prior/scope=national/part.parquet
    │   ├── surnames/
    │   │   ├── scope=national/part.parquet
    │   │   └── uf=<UF>/part.parquet
    │   └── states/part.parquet
    ├── first_names/...                # Historical opt-in (census_year=2010)
    ├── surnames/scope=national/...
    ├── middle_names/part.parquet
    └── states/part.parquet            # IBGE 2024 population estimates
```

Each marginal partition stores `(name: str, count: int64, weight: float64)` normalized via `math.fsum` so $\|\mathbf{w}\|_1 - 1 < 10^{-15}$. We deliberately **never** materialize the `27 × 10 × 2 = 540` Cartesian `UF × cohort × sex` product on disk (`< 13 MiB` total 2022 Parquet footprint).

### Resolution hierarchy (`ptbr_sampler/datasets.py`)

When `PartitionStore` or `BrazilianLocationSampler` touches a file, `ensure_data_file(relpath)` checks:

1. `PTBR_SAMPLER_DATA_DIR/<relpath>` (air-gapped / container mount),
2. Local git checkout `ptbr_sampler/data/<relpath>` (zero network I/O when running inside the repository),
3. User cache `<PTBR_SAMPLER_CACHE_DIR or ~/.cache/ptbr-sampler>/<hf_revision>/<relpath>`,
4. Streaming HTTPS download from `https://huggingface.co/datasets/<PTBR_SAMPLER_HF_REPO or arthrod/ptbr-sampler-data>/resolve/<hf_revision>/<relpath>` under a cross-process `fcntl.flock` lock, verifying exact byte length and SHA-256 into `<dest>.<pid>.part` before atomic `os.replace`. `Authorization` headers (`HF_TOKEN`) are stripped on cross-origin CDN redirects (`*.hf.co`), and `PTBR_SAMPLER_OFFLINE=1` disables all network access.

Pre-warm or audit caches explicitly with `ptbr datasets prefetch --census-year 2022`, `ptbr datasets status --verify`, and `ptbr datasets clear-cache`.

---

## 2. Sampling — Kahan-Compensated Walker/Vose Alias Method, `RLock` LRU, & `Faker`

`ptbr_sampler/sampling/alias.py` builds `(prob, alias)` in $O(m)$ using Shewchuk's exact floating-point summation (`math.fsum`), bulk C-level hub absorption when a high-multiplicity bucket ($q_\ell \ge 2.0$, such as `Silva` at $q_{\text{Silva}} \cdot M \approx 20{,}571$) absorbs thousands of tail buckets, and per-bucket Kahan (1965) compensated subtraction (`L_inf = 1.39e-17` on Census 2022 partitions). It draws `k` samples in vectorized $O(k)$ NumPy operations independent of support size $m$. `AliasTable.induced_probabilities()` reconstructs the exact categorical distribution induced by `(prob, alias)` in $O(m)$, and `AliasTable.top_k(40)` slices top-40 surname tables directly from 2022 national or UF partitions.

### Thread Safety, Isolated `random.Random` Streams, & `asyncio` Safety

- **Zero global RNG mutation:** Every public and internal entry point accepts `rng: random.Random | None = None`. When `rng` is supplied, vectorized `AliasTable` batches derive ephemeral child NumPy generators via `np.random.default_rng(rng.getrandbits(128))` without reading or mutating module-global `random` or `numpy.random` state.
- **Synchronized caches:** `PartitionStore` (`ptbr_sampler/sampling/store.py`) and the reusable sampler caches in `ptbr_sampler/sampler.py` protect LRU lookups, insertions, and evictions behind `threading.RLock`, while sorting `(uf, sex)` buckets deterministically so seeded outputs are invariant to dictionary iteration order.
- **Event-loop safety:** Offline `sample(..., save_to_jsonl=None)` executes through a synchronous fast path (`_generate_offline_address_batch`), avoiding nested `asyncio.run()` errors inside Jupyter, marimo, or FastAPI loops.
- **Fixed `uf=` alignment:** Passing `uf='SP'` (or `--uf SP` on the CLI) pins location draws, given names, UF-conditioned 2022 surnames, postal CEP ranges, Anatel DDD area codes, and state-specific RG patterns (`SSP-SP`, `DETRAN-RJ`, probabilistic `MG` prefix) to the requested Federation Unit.

### First-Class `Faker` Provider (`ptbr_sampler.faker`)

`PTBRProvider` and `install_ptbr(fake, aliases=False, ...)` wrap the cached `BrazilianNameSampler`, `BrazilianLocationSampler`, and `DocumentSampler` instances directly, routing all randomness through `self.generator.random` so `Faker.seed(...)` and `fake.seed_instance(...)` are bit-reproducible across fresh instances. By default (`aliases=False`), only namespaced `ptbr_*` formatters (`ptbr_profile`, `ptbr_name`, `ptbr_cpf`, `ptbr_rg`, `ptbr_cep`, `ptbr_address`, `ptbr_phone`, etc.) are registered, leaving standard `Faker('pt_BR')` locale providers untouched unless `aliases=True` is explicitly requested. Multi-locale proxy `Faker(['pt_BR', 'en_US'])` instances and repeated `install_ptbr(...)` reconfigurations clean up prior `PTBRProvider` instances idempotently.

---

## 3. Conditioning Modes & Statistical Semantics (`census_year=2022`)

- **`conditioning_mode='strict'` (default):** serves only directly published 2022 marginals (`national`, `national × sex`, `national × cohort`, `UF`). Requesting unobserved multi-axis intersections (`UF × sex`, `cohort × sex`, `UF × cohort`) raises `ValueError` instead of silently dropping an axis.
- **`conditioning_mode='estimated'` (opt-in):** lazily constructs `UF × sex` (`time_period=ALL`) and `cohort × sex` (`uf=None`) in memory (`< 5 ms`) by multiplying the marginal `weight` vector against the 2022 national `sex_prior` empirical rate $\hat{p}_{\text{obs}}(i) = N_{i,\text{obs}} / N_i$ (`NaN` for suppressed cells, never imputing withheld `< 20` counts). `UF × cohort` remains rejected in all modes.
- **Surname slot share vs. presence:** IBGE's `Silva = 16.76%` is person-level presence across `~1.6422` recorded surname tokens/person; the normalized single-slot weight is $q_{\text{Silva}} = 10.2040\%$. In `census_year=2022` two-surname mode (`with_only_one_surname=False`), slot 2 is resampled conditional on $s_2 \neq s_1$ to eliminate duplicate stems (`"Silva Silva"`).
- **Realism vs. `random=True`:** `random=False` (default) samples population-weighted geography (2024 IBGE municipal estimates) and frequency-weighted 2022 Census names; `random=True` switches geography, names, and middle-name incidence (`50%` vs `30.99%`) to uniform draws.

---

## 4. Four-Layer Statistical Validation

1. **Layer A (Deterministic conservation):** `scripts/audit_datasets.py` & `tests/test_dataset_audit.py` verify schema, SHA-256 digests, Liv102228 censoring regimes (`both_observed`, `one_null_exact_zero`, `one_null_suppressed_positive`, `both_null_suppressed`), and weight normalization $\|\mathbf{w}\|_1 = 1$.
2. **Layer B (Exact $O(M)$ alias reconstruction):** `tests/test_distribution_validation.py` verifies $\mathrm{TVD}(p_{\text{alias}}, w) < 10^{-13}$ with zero Monte Carlo noise in `< 50 ms`.
3. **Layer C (`@pytest.mark.slow` exhaustive Monte Carlo GoF):** tail-pooled multinomial $\chi^2$ with all expected bin counts $E_j \ge 5$, Holm–Bonferroni FWER control ($\alpha_{\text{FWER}} = 0.001$), and two mandatory negative controls (head-to-tail mass leak and `top_40` truncation).
4. **Layer D (Cross-table demographic coherence):** UF-sum vs. national bounds and 2010-vs-2022 cohort alignment TVD in `scripts/audit_datasets.py`.

---

## 5. Remaining Boundaries & Methodological Caveats

1. **Mixed reference dates (`2022` names vs. `2024` geography):** Names come from the 1 August 2022 Census (`203.08M` residents), whereas `locations_data.json` / `cities_with_ceps.json` use 1 July 2024 IBGE population estimates (`212.6M`).
2. **Confidentiality suppression (`Liv102228`):** Cells `< 20` nationally/by-decade, `< 15` per UF, and `< 10` per municipality are suppressed by IBGE (`0.1793%` = `341,280` national given-name occurrences lack observed sex breakdown).
3. **Diacritics in 2022 IBGE strings:** IBGE disseminates folded uppercase/ASCII roots (`Joao`, `Goncalves`), while preserving distinct spelling roots (`Ana`/`Anna`, `Luis`/`Luiz`). `ptbr-sampler` preserves IBGE's orthographic equivalence classes without heuristic accent restoration.
4. **Authorial middle names & surname connectives:** `middle_names.json` (`percentage_with_second = 30.99%`) and `SURNAME_PREFIXES` (`da`, `de`, `dos`) remain authorial/civil-registry conventions because IBGE disseminates only the first given name and bare surname tokens.

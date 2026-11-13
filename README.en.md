# 🇧🇷 `ptbr-sampler` `0.3.0` — Realistic Brazilian Demographic Data Generator

Generate Brazilian names, addresses, CPFs, CNPJs, RGs, PIS, and CEIs **proportional to empirical population distributions** and grounded in auditable public datasets. Starting in **`0.3.0`**, **IBGE Census 2022** (`census_year=2022`, `TimePeriod.ALL`) is the primary default, and runtime datasets are served from Hugging Face Hub ([`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data)) with streaming `SHA-256` verification — keeping the published Python wheel **under `150 KiB`**.

Full source citations live in [`docs/sources/bibliography.md`](docs/sources/bibliography.md) and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); storage, conditioning, and four-layer statistical validation are detailed in [`docs/architecture.md`](docs/architecture.md) and [`docs/data-origins.md`](docs/data-origins.md).

*Leia em Português: [README.md](README.md)*

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.3.0-green.svg)](pyproject.toml)

---

## ✨ What's New in `0.3.0`

- 👤 **Census 2022 by Default (`census_year=2022`, `TimePeriod.ALL`)**: `128,458` given names (`99.8207%` directly observed sex mass) and `201,601` national + UF-conditioned surnames (`Santos` in Sergipe, `Silva` in Alagoas/Pernambuco), ingested from [`olob0/ibge-nomes-no-brasil-2022`](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022) (`05efb85c92af43da2ed4ed088d1e0c9f17160e65`). Census 2010 remains supported via `--census-year 2010` / `census_year=2010`.
- 📦 **Ultra-Slim Wheel (`< 150 KiB`) + Hugging Face Runtime Cache**: Only `ptbr_sampler/data/dataset_manifest.json` (`~16 KiB`) ships inside the `.whl`. Touched Parquet/JSON artifacts download lazily from `arthrod/ptbr-sampler-data` (pinned by an immutable 40-char commit SHA + per-file `SHA-256`) into `~/.cache/ptbr-sampler/<hf_revision>/`, with explicit Docker/offline pre-warming via `ptbr datasets prefetch`.
- 🧭 **Strict Observed Marginals vs. Lazy Bayes Estimation**: `conditioning_mode='strict'` (default) serves only directly observed IBGE marginals (`national`, `national × sex`, `national × cohort`, `UF`); `conditioning_mode='estimated'` enables lazy in-memory `UF × sex` and `cohort × sex` Bayes conditioning with zero Cartesian partition bloat.
- 📍 **Population-Weighted Geography & Valid Synthetic Documents**: States and municipalities weighted by 2024 IBGE Population Estimates (`212.6M`), paired with check-digit-valid synthetic CPF, state-specific RG, PIS, CNPJ, and CEI generators.

---

## 📦 Installation & Offline / Docker Dataset Pre-Warming

```bash
# Fast install (< 150 KiB wheel)
uv add ptbr-sampler
# or inside a local development checkout:
uv sync --extra test --extra dev
```

Outside a git checkout, `ptbr-sampler` downloads only the partitions touched on first call (`~3.1 MiB` for the default national path). For **Docker images, CI runners, or air-gapped environments**:

```bash
# Pre-download and SHA-256-verify all Census 2022 runtime artifacts
ptbr datasets prefetch --census-year 2022

# Inspect cache location and verify SHA-256 digests
ptbr datasets status --verify

# Enforce zero runtime network calls
PTBR_SAMPLER_OFFLINE=1 ptbr generate --qty 5 --uf-conditioning
```

Environment controls:
- `PTBR_SAMPLER_CACHE_DIR`: user cache root (default: `$XDG_CACHE_HOME/ptbr-sampler` or `~/.cache/ptbr-sampler`).
- `PTBR_SAMPLER_DATA_DIR`: pre-populated runtime data directory (read-only container layers).
- `PTBR_SAMPLER_HF_REPO`: override Hugging Face dataset repository (default: `arthrod/ptbr-sampler-data`).
- `PTBR_SAMPLER_OFFLINE`: when `1`/`true`, forbids all network calls and raises `RuntimeError` on cache misses.

---

## 🎯 Quick Start

### Command Line Interface (`ptbr`)

```bash
# 0.3.0 default: Census 2022 (full resident stock TimePeriod.ALL) + weighted geography
ptbr generate --qty 5

# Empirical UF conditioning (2022 UF given names and regional UF surnames)
ptbr generate --qty 5 --uf-conditioning

# Observed sex conditioning ('M', 'F', balanced 'mixed' 50/50, or empirical 'population')
ptbr generate --qty 5 --sex-conditioning population

# Joint UF × sex conditioning via Bayes conditional independence (explicit opt-in)
ptbr generate --qty 5 --uf-conditioning --sex-conditioning F --conditioning-mode estimated

# Historical Census 2010 opt-in (defaults to TimePeriod.UNTIL_2010)
ptbr generate --qty 5 --census-year 2010

# Uniform escape hatch ("realism off") and data provenance inspection
ptbr generate --qty 5 --random
ptbr sources --census-year 2022
```

### Python API

```python
from ptbr_sampler.br_name_class import BrazilianNameSampler, TimePeriod
from sample import sample

# End-to-end sampling (defaults: census_year=2022, time_period=TimePeriod.ALL, conditioning_mode='strict')
records = sample(q=5, uf_conditioning=True)

# Joint cohort × sex conditioning (explicit 'estimated' opt-in)
cohort_f = sample(
    q=5,
    time_period=TimePeriod.UNTIL_2020,  # born 2010–2019 in Census 2022
    sex_conditioning='F',
    conditioning_mode='estimated',
)

# Direct Parquet name sampler (lazily resolves from HF cache when installed from wheel)
name_sampler = BrazilianNameSampler.from_parquet(census_year=2022)
person = name_sampler.get_random_name(uf='SE', return_components=True)

# Historical Census 2010 opt-in
legacy_records = sample(q=5, census_year=2010)
```

---

## 📐 Statistical Methodology, Liv102228 Thresholds, & Coverage

Per [IBGE Technical Note Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf), IBGE suppresses cells with count **`< 20` nationally and national-by-decade**, **`< 15` per UF**, and **`< 10` per municipality** (regional thresholds are *lower*, not higher, than the national threshold).

### Five distinct sex-coverage metrics (`census_year=2022`)
1. **Vocabulary lookup coverage (distinct types):** `123,733 / 128,458` (`96.32%`) given-name types have at least one non-null sex count.
2. **Directly observed empirical mass:** **`99.8207%`** (`190,041,904 / 190,383,184` occurrences; `60,954` male rows and `73,361` female rows).
3. **Deduced exact-zero mass (`R = 0`):** **`55,210`** single-null names satisfy $N - N_{\text{obs}} = 0$ identically (`one_null_exact_zero`).
4. **LLM-assigned uncalibrated mass:** **`0.0%`** in Census 2022 (Gemini gap-fill is confined to historical `census_year=2010` with `count_* = 0`).
5. **Suppressed / excluded mass:** **`341,280`** occurrences (**`0.1793%`**, totaling `232,758` residual occurrences across `57,941` `one_null_suppressed_positive` names plus `108,522` across `4,725` `both_null_suppressed` names).

### Cohort boundaries, surname slot vs. presence, and reference dates
- **10-year cohort convention:** Legacy 2010 (`names_data.json`) labeled cohorts by upper endpoint (`ate2010` = `2000–2009`), whereas `olob0` `name_by_decade` labels by decade start (`decade=2000` = `2000–2009` → `TimePeriod.UNTIL_2010`, `decade=2010` = `2010–2019` → `TimePeriod.UNTIL_2020`, `decade=2020` = `2020–1 Aug 2022` → `TimePeriod.PERIOD_2020_2022`, and `decade=1930` = `<= 1939` → `TimePeriod.UNTIL_1940`).
- **Surname token-slot share vs. person-level presence:** IBGE's headline `Silva = 16.76%` (`34,030,104 / 203,080,756`) is **person-level presence** across `~1.6422` recorded surname tokens/person; the normalized single-slot token share is $q_{\text{Silva}} = 10.2040\%$ ($q_{\text{Santos}} = 6.4071\%$). In `census_year=2022` two-surname mode (`with_only_one_surname=False`), slot 2 is resampled conditional on $s_2 \neq s_1$ so duplicate stems (`"Silva Silva"`) never occur.
- **Mixed reference dates & authorial components:** Default names reflect **1 August 2022** Census resident stock (`203.08M`), while geography (`locations_data.json` / `cities_with_ceps.json`) uses **1 July 2024** IBGE population estimates (`212.6M`). Middle names (`percentage_with_second = 30.99%`) and surname prepositions (`da`, `de`, `dos`) come from authorial/civil-registry conventions because IBGE disseminates only the first given name and bare surname stems.

---

## 🛠️ Maintainer Rebuild & Validation Commands

```bash
# Fetch pinned Census 2022 Parquet snapshot, ingest float64 partitions, and run statistical audit
python -m scripts.download_datasets --fetch-ibge-2022
python -m scripts.ingest_to_parquet
python -m scripts.audit_datasets --raw-dir ptbr_sampler/data/raw/ibge_nomes_2022 --parquet-dir ptbr_sampler/data/parquet/census_year=2022

# Run fast suite (including exact O(M) alias probability reconstruction) and slow Monte Carlo GoF
uv run pytest -n auto -q
uv run pytest -m slow tests/test_distribution_validation.py -v
```

---

## 📄 License & Third-Party Notices

Repository source code is governed by [`LICENSE`](LICENSE). Attribution and provenance notices for public statistical disseminations and third-party compilations (IBGE, `olob0/ibge-nomes-no-brasil-2022`, `brasil.io/genero-nomes`, Arpen-Brasil, and `arthrod/ptbr-sampler-data`) are documented in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

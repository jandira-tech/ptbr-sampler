# 🇧🇷 Brazilian Realistic Data Generator

Generate names, addresses, CPFs, CNPJs, and other Brazilian documents that are **proportional to actual population distribution** and based **exclusively on existing, verified data**. Every generated name exists in Brazilian historical records, and locations are sampled proportionally to each region's population.

Full citations live in [`docs/sources/bibliography.md`](docs/sources/bibliography.md); the sampling architecture (partitioned Parquet, Walker/Vose alias method, condition-keyed LRU) is described in [`docs/architecture.md`](docs/architecture.md). The statistical audit that motivated the current release is in [`deep-research-report(4).md`](deep-research-report(4).md).

*Leia aqui em Português: [Português](README.md)*

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Key Features

- 📍 **Location Generation**: Realistic Brazilian addresses with population-weighted sampling
- 👤 **Name Generation**: Historically accurate Brazilian names with period-specific sampling
- 📄 **Document Generation**: Valid Brazilian documents (CPF, RG, PIS, CNPJ, CEI)
- 🎯 **Statistical Accuracy**: Based on real demographic data and historical statistics
- 🔧 **Flexible Output**: Structured data in various formats (CLI, Python dictionaries, API-ready)
- ⚡ **High Performance**: Efficient sampling with pre-calculated weights
- 🧪 **Thoroughly Tested**: Comprehensive test suite for reliability

## 🚀 Perfect For

- 🏢 **Enterprise Applications**: Generate realistic test data for Brazilian market applications
- 🧪 **Testing**: Create diverse datasets for thorough application testing
- 📊 **Data Science**: Generate statistically accurate samples for analysis and modeling
- 🎓 **Education**: Learn about Brazilian document formats and validation rules
- 🔄 **API Development**: Ready-to-use structured data for API responses

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/your-username/ptbr-sampler.git
cd ptbr-sampler

# Install dependencies (recommended to use a virtual environment)
uv sync
```

## 🎯 Quick Start

### Command Line Interface

```bash
# Generate a complete profile (name, location, documents)
uv run ptbr sample --qty 1

# Generate specific documents only
uv run ptbr sample --only-cpf --only-rg --qty 3

# "Realism off" mode (intentionally non-realistic output): uniform
# location across states/cities, uniform name draws, flat 50/50
# middle-name flag instead of the empirical 30.99%.
uv run ptbr sample --qty 5 --random
```

### Python API

```python
from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import BrazilianNameSampler, TimePeriod
from ptbr_sampler.document_sampler import DocumentSampler

# Initialize samplers
location_sampler = BrazilianLocationSampler("data/cities_with_ceps.json")
name_sampler = BrazilianNameSampler("data/names_data.json", 
                                   middle_names_path="data/middle_names.json")
doc_sampler = DocumentSampler()

# Generate data
state_name, state_abbr, city_name = location_sampler.get_state_and_city()
name_components = name_sampler.get_random_name(
    time_period=TimePeriod.UNTIL_2010,
    return_components=True
)

# Get formatted output
result = {
    "name": name_components.first_name,
    "middle_name": name_components.middle_name,
    "surnames": name_components.surname,
    "city": city_name,
    "state": state_name,
    "state_abbr": state_abbr,
    "cep": location_sampler.format_full_location(
        city_name, state_name, state_abbr
    ).split(',')[-1].strip(),
    "cpf": doc_sampler.generate_cpf(),
    "rg": doc_sampler.generate_rg(state_abbr)
}
```

## 🎛️ Features In-Depth

### Location Generation
- Population-weighted selection of states and cities
- Realistic CEP (postal code) generation
- Flexible output formatting
- Support for specific region filtering

### Name Generation
- Historical period-based sampling
- Support for full names, middle names, and surnames
- Case formatting options (title case, uppercase)
- Top 40 surnames list option

### Document Generation
- CPF (Brazilian Individual Taxpayer ID)
- RG (Brazilian ID Card) with state-specific formats
- PIS (Social Integration Program Number)
- CNPJ (Brazilian Company ID)
- CEI (Employer Registration Number)

### Data Output
- Structured dictionary format
- CLI with rich formatting
- Batch generation support
- Customizable output fields

## 🏗️ Project Structure

```plaintext
src
├── br_location_class.py         # Location sampling
├── br_name_class.py             # Name sampling
├── br_rg_class.py              # RG generation
├── cli.py                      # Command-line interface
├── document_sampler.py         # Document generation
├── __init__.py                 # Package initialization
└── utils/                      # Utility functions
    ├── cpf.py                  # CPF handling
    ├── pis.py                  # PIS handling
    ├── cnpj.py                 # CNPJ handling
    ├── cei.py                  # CEI handling
    ├── util.py                 # Helper functions
    └── __init__.py
```

## 🧪 Testing

Comprehensive test suite covering all components:

```bash
uv run pytest
```

## 📚 Requirements

- Python 3.9+
- Dependencies:
  - Typer (CLI framework)
  - Rich (Terminal formatting)
  - pytest (Testing)

## 📖 Documentation

Detailed documentation for all features and components:

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Main Features](#main-features)
- [Command Line Interface](#command-line-interface)
- [Data Output](#data-output)
- [Testing and Validation](#testing)
- [Installation and Dependencies](#installation)
- [Usage Examples](#quick-start)

## 📊 Sources and citations

Every distribution bundled with this repository was built from primary
Brazilian official sources. The main ones are:

| Source | Scope | URL |
|---|---|---|
| IBGE — *Nomes no Brasil*, 2022 Census (2025 relaunch) | Names and surnames by sex, period of birth, UF, and municipality | <https://www.ibge.gov.br/apps/nomes/> |
| IBGE News Agency (PT) | 2022 Census *Nomes no Brasil* release | <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/44929-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil> |
| IBGE Highlights (EN) | 2022 Census *Nomes no Brasil* release | <https://www.ibge.gov.br/en/highlights/44662-on-november-4-2025-ibge-will-release-2022-population-census-names-in-brazil.html> |
| IBGE — Nomes API v2 | Frequency by decade and locality (2010 Census) | <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2> |
| IBGE — Population Estimates 2024 | UF and municipal totals as of 1 July 2024 | <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/41111-populacao-estimada-do-pais-chega-a-212-6-milhoes-de-habitantes-em-2024> |
| IBGE FTP DOU 2024 | Canonical per-municipality PDF table | <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf> |
| Arpen-Brasil | National 2024 newborn ranking | <https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/> |
| IPEA — `censobr` | 2022 Census microdata in Parquet | <https://ipeagit.github.io/censobr/> |
| IPEA — `geobr` | Official municipal geometries | <https://ipeagit.github.io/geobr/> |

Per-source write-ups with the full tables (UF-level surname percentages,
methodology, reference dates):

- [`docs/sources/bibliography.md`](docs/sources/bibliography.md) — index.
- [`docs/sources/ibge-nomes-no-brasil-2022.md`](docs/sources/ibge-nomes-no-brasil-2022.md) — surnames by UF (`Silva` 16.76% Brazil; `Santos` 43.38% Sergipe; `Silva` 35.75% Alagoas; `Silva` 34.23% Pernambuco; > 200k surnames surveyed).
- [`docs/sources/ibge-estimativas-populacao-2024.md`](docs/sources/ibge-estimativas-populacao-2024.md) — 212.6 million inhabitants on 1 July 2024.
- [`docs/sources/arpen-2024-rankings.md`](docs/sources/arpen-2024-rankings.md) — national 2024 top 10: Helena, Miguel, Gael, Ravi, Theo, Heitor, Cecília, Arthur, Noah, Maitê.

## 🏛️ Data and sampling architecture

The current release replaces nested Python dicts with three decisions that
scale up to IBGE 2022 data conditioned on `(UF × decade × sex)`:

1. **Storage.** Partitioned Parquet under `ptbr_sampler/data/parquet/`
   (`first_names/period=<x>/`, `surnames/scope=national/`, `middle_names/`,
   `states/`). Reads go through `pyarrow.dataset` with filter pushdown —
   only the partitions actually touched are materialised. Ingestion script:
   [`scripts/ingest_to_parquet.py`](scripts/ingest_to_parquet.py).
2. **Sampling primitive.** Walker/Vose alias method in
   [`ptbr_sampler/sampling/alias.py`](ptbr_sampler/sampling/alias.py): O(m) build, **O(1)
   per draw**, fully vectorised over NumPy. `k=1` and `k=100_000` have the
   same cost structure per sample.
3. **Lazy-load bounded LRU.**
   [`ptbr_sampler/sampling/store.py`](ptbr_sampler/sampling/store.py) wraps partitions behind
   a bounded LRU cache. Hot conditions (SP/MG/RJ) stay resident, cold ones
   page from disk on first touch.

The `middle_names.json` file is filtered through a given-names whitelist
maintained in
[`ptbr_sampler/sampling/vocabulary.py`](ptbr_sampler/sampling/vocabulary.py), stripping
surname leakage (`Araújo`, `Borges`, `Bezerra`, …), the administrative
token `Cancelado`, and non-name artefacts (`-`). Statistical validation
via `scipy.stats.chisquare` / `ks_2samp` lives in
[`tests/test_distribution_validation.py`](tests/test_distribution_validation.py).

To materialise the Parquet layout from the legacy JSON files:

```bash
python -m scripts.ingest_to_parquet
```

## 🧭 Realism by default (and an explicit random escape hatch)

The default path is **realism-by-default**:

1. geography is sampled first, weighted by population (state and city);
2. names are drawn from alias tables that encode the empirical IBGE /
   civil-registry distributions, conditioned on whichever dimensions are
   actually available in the bundled data.

Callers that want intentionally less realistic output can opt in via
`random=True` (Python) or `--random` (CLI):

```python
from sample import sample
sample(q=5)                 # realism by default (recommended)
sample(q=5, random=True)    # explicit random mode
```

In random mode the sampler **ignores** population weights for location,
**ignores** frequency weights for names/surnames, and replaces the
empirical 30.99% middle-name flag with a flat 50/50 coin flip. This is
deliberate: realism remains the project's goal, and the flag makes the
escape hatch explicit.

The realistic path **only** conditions on dimensions that actually
exist in the bundled data: `period` for first names, `scope=national`
for surnames, and population shares for geography. UF- and
sex-conditioned realism are blocked on data ingest, not on code — see
"Known realism gaps" below.

## 📥 Download data and rebuild the Parquet layout

To rebuild the bundled artefacts from scratch (`todo.md` items 1 and 11):

```bash
# 1. Inventory: what's present locally, and what does each dataset power?
python -m scripts.download_datasets

# 2a. (Optional, EXPERIMENTAL) Download the IBGE Nomes v2 UF x sex x
#     decade rankings (~540 calls, top-20 per condition). Unlocks UF /
#     sex conditioning for first names — see caveat below.
python -m scripts.download_datasets --fetch-ibge-nomes

# 2b. For any [MISS] row from step 1, fetch the source URL and drop it
#     under ptbr_sampler/data/raw/<name>/. Datasets distributed only as
#     web apps (IBGE Nomes 2022, Arpen 2024) stay manual by design.

# 3. Rebuild the partitioned Parquet layout from JSON sources + raw rankings:
python -m scripts.ingest_to_parquet

# 4. Re-run the tests:
uv run --extra test pytest -q
```

Each dataset's source URL, raw local path, and what it powers are
tabulated in [`docs/data-origins.md`](docs/data-origins.md) under
"Download-and-rebuild walkthrough".

**Network requirements:** the fetcher hits `servicodados.ibge.gov.br`
over HTTPS. Sandboxes that restrict outbound egress (the one this repo
is developed in, for example) fail with `Host not in allowlist` / 403.
Run on a machine with general internet egress.

> **Cross-machine handoff.** If you are running the fetch on a separate
> machine and returning to Claude Code afterwards, follow the runbook
> in [`docs/handoff-fetch-and-ingest.md`](docs/handoff-fetch-and-ingest.md)
> and the return template in
> [`docs/handoff-resume-with-claude.md`](docs/handoff-resume-with-claude.md).

### UF / sex conditioning (experimental)

Once the step 2a rankings are ingested, the sampler can condition
first-name draws on `(UF, period, sex)` — but it's **opt-in**:

```python
from sample import sample
sample(q=5, experimental_uf_sex_conditioning=True)
```

```bash
uv run ptbr sample --qty 5 --experimental-uf-sex
```

**Caveat (important):** the IBGE Nomes v2 ranking endpoint returns only
the **top 20** names per condition. The conditioned pool is therefore
much narrower than the period-only table (~thousands of names per
period), so turning the flag on trades distribution breadth for
regional/sex realism. That's why the default stays on the period-only
path.

When a specific `(UF, period, sex)` partition is missing, the sampler
silently falls back to the period-only table for that row — so the flag
is safe to enable after a partial fetch.

## ⚠️ Known realism gaps

Operational summary of where the available data **limits** sampling
realism today. Full details live in `docs/data-origins.md`,
`docs/architecture.md`, and `deep-research-report(4).md`.

- **UF / sex conditioning for *first names* — experimental, top-20.**
  The IBGE Nomes v2 ranking endpoint exposes top-20 names per
  `(UF, sex, decade)` condition. The ingester writes them to
  `parquet/first_names/uf=<UF>/period=<P>/sex=<S>/` and the sampler
  uses them via `experimental_uf_sex_conditioning=True`. Default stays
  on the period-only path because ~20 names per condition is much
  narrower than ~thousands per period in the unconditioned table.
- **No UF conditioning for *surnames*.** The IBGE 2022 release
  publishes UF-level surname distributions only in the web app (no
  API or bulk download). Surnames stay on the pooled-national
  distribution today — this understates strong regional effects
  (`Santos` 43.38% in Sergipe, `Silva` 35.75% in Alagoas). Blocked on
  data, not on code.
- **No sex conditioning on the default path.** Same reason as above:
  `names_data.json` is sex-mixed. Sex only enters when the
  experimental flag is on AND the conditioned partitions exist.
- **Time horizon capped at `UNTIL_2010`.** The latest bucket covers
  births up to 2010 (IBGE stock). Recent cohorts (2011–2024) sit
  outside; the Arpen 2024 ranking is a newborn-flow benchmark, not a
  population-stock replacement.
- **`top_40` is a historical-data mode.** It exists because, in the
  legacy extract, only the top-40 surnames were consolidated reliably.
  The full ~86k-entry table tracks the empirical distribution more
  faithfully. `top_40` is kept for convenience; do not read it as the
  realism-preserving path.
- **Two-surname convention.** Brazilian civil naming overwhelmingly
  uses **at least two surnames** (one per parental line). The default
  preserves this. `with_only_one_surname=True` is a
  compatibility / convenience override, **not** the realistic default.
- **`middle_names.json` provenance.** Civil-registry extract filtered
  through the given-name whitelist and surname blocklist in
  `ptbr_sampler/sampling/vocabulary.py`; the cleaning pipeline is
  reproducible via `python -m scripts.ingest_to_parquet`. IBGE *Nomes
  no Brasil* disseminates first name only, so this dataset is
  authorial by necessity. Detailed provenance in `docs/data-origins.md`.
- **`percentage_with_second = 30.99%`.** Computed directly from the
  raw extract (`1,640,514 / 5,293,204`). Transparent for that corpus,
  but the corpus itself is the authorial extraction. Read it as a
  transparent estimate, not as an IBGE-published statistic.
- **`random=True` relaxes every conditioning dimension.** It is the
  honest counterpart of realism-by-default: callers who want uniform
  output have an explicit way to ask for it.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

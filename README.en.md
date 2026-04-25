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

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

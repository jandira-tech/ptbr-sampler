# ptbr-sampler

Generate synthetic Brazilian profiles with names, locations, addresses, phone
numbers, and documents. Version 0.3.0 uses IBGE 2022 Census distributions,
2025 Arpen-Brasil birth registrations, and 2026 population estimates. Inputs and
transformations are auditable; results do not represent real people or official
population-name estimates.

*Leia em Português: [Português](README.md).*

[![Python 3.12 or later](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![MIT license](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Open the demo in Colab](https://img.shields.io/badge/Colab-Open%20demo-F9AB00?logo=googlecolab)](https://colab.research.google.com/github/jandira-tech/ptbr-sampler-notebooks/blob/main/notebooks/ptbr_sampler_demo.ipynb)
[![Open the demo in molab](https://img.shields.io/badge/molab-Open%20demo-green)](https://molab.marimo.io/github/jandira-tech/ptbr-sampler-notebooks/blob/main/notebooks/ptbr_sampler_demo.py)

These deterministic notebook URLs target the future publication of
`jandira-tech/ptbr-sampler-notebooks`. marimo/WASM and Pyodide compatibility has
not been verified, so no `/wasm` link is advertised.

## Installation

Install the public PyPI package with Python 3.12 or later:

```bash
python -m pip install ptbr-sampler==0.3.0
```

For the optional Faker integration:

```bash
python -m pip install 'ptbr-sampler[faker]==0.3.0'
```

The `jandira-tech/ptbr-sampler` source repository is private; the PyPI package
and public notebook repository are separate distributions. You do not need to
clone the source repository to use the CLI, packaged data, or Faker provider.

## CLI

`ptbr sample` and `ptbr generate` are equivalent:

```bash
ptbr sample --qty 1
ptbr generate --qty 5 --uf SP --cohort census2022 --sex-conditioning F
ptbr sample --qty 3 --time-period after2010 --return-only-name
ptbr sample --qty 5 --random --save-to-jsonl samples.jsonl
ptbr sample --only-cpf --only-rg --qty 3
ptbr sources
```

Run `ptbr sample --help` for every selector. Generation is offline by default.
`--make-api-call` resolves CEPs through ViaCEP; `--easy` also enables these
calls, includes all fields, and writes to `output/output.jsonl`.

## `sample()` API

The `sample(q=...)` convenience wrapper lives in `sample.py` at the private
source repository root. These examples are valid in an authorized checkout:

```python
from sample import Cohort, TimePeriod, sample
```

The 0.3.0 wheel also exposes classes from `ptbr_sampler` and the low-level
`ptbr_sampler.sampler.sample` function, but does not install the top-level
`sample` module. For a concise installed Python API, use the Faker provider below
or the CLI.

```python
from random import Random
from sample import Cohort, TimePeriod, sample

# Current cohort, population-sampled UF, and no sex conditioning.
profile = sample(q=1, rng=Random(42))

# A fixed UF applies to location, first names, and surnames.
profiles = sample(q=10, cohort=Cohort.NEWBORN2025, uf='SP', sex_conditioning='F')

# An explicit historical period selects history instead of a cohort blend.
historical = sample(q=3, time_period=TimePeriod.AFTER_2010)

# Uniform over the final selected support; second-name incidence is unchanged.
uniform = sample(q=5, random=True)
```

`q=1` returns a dictionary; larger quantities return a list. Defaults are
`cohort='current'`, `time_period=None`, `random=False`, and
`sex_conditioning=None`. The wrapper includes CPF, RG, and phone by default.
Combining `census2022` or `newborn2025` with `time_period` raises `ValueError`;
only `current + time_period` is compatible.

### Cohorts, periods, and sex

| Selector | Meaning |
|---|---|
| `current` | Synthetic blend of 2022 Census and 2025 births; default |
| `census2022` | Observed 2022 Census frequencies without recency adjustment |
| `newborn2025` | Arpen UF top 50 plus modeled national 2011–2020 tail |
| `ate1930` … `ate2020` | National IBGE historical stocks and stock differences |
| `after2010` | `stock2020 - stock2010`, covering 2011–2020 |
| `M`, `F` | Renormalized national empirical IBGE 2022 sex prior |
| `mixed` | 50/50 M/F draw per row; does not add a `sex` output field |

Sex conditioning uses **national** evidence, not observed UF-by-sex tables.
Names without sex counts remain in unconditioned distributions and are omitted
only from M/F tables. `experimental_uf_sex_conditioning=True` remains as a
compatibility option and only selects `mixed` when no explicit sex was supplied.
UF conditioning is always active. To migrate, use `sex_conditioning='mixed'`
and remove the experimental flag.

For each UF, the current blend is:

```text
alpha_uf = Arpen2025_registrations_uf / official_IBGE_POP2026_population_uf
current_uf = (1 - alpha_uf) * census2022_uf + alpha_uf * newborn2025_uf
```

The SIMPLE top-50 residual is distributed across the national `after2010` tail,
excluding labels observed in that UF. No compound-name or second-name incidence
is inferred. `current` is not an official future population-name estimate.

Surnames use only IBGE 2022 national/UF distributions, independently of the
first-name cohort. `top_40=True` selects the 40 largest surnames from the final
UF probabilities and renormalizes; it is not a fixed national top 40.
`with_only_one_surname=True` is an output option, not a claim about the real
incidence of one versus two surnames.

`random=True` samples locations and the final first-name/surname support
uniformly. The legacy 30.99% second-name incidence remains unchanged. It comes
from `1,640,514 / 5,293,204` in an old extract, has not been validated as a
population statistic, and must not be inferred from Arpen rankings.

## Faker provider

Install the `faker` extra, register the provider on each desired instance, and
then set the seed:

```python
from faker import Faker
from ptbr_sampler.faker import install_ptbr

fake = Faker('pt_BR')
install_ptbr(fake, uf='SP', cohort='current')
fake.seed_instance(42)

profile = fake.ptbr_profile()       # one coherent, complete dict[str, str]
name = fake.ptbr_name()             # str
unformatted_cpf = fake.ptbr_cpf(formatted=False)
cep = fake.ptbr_cep()
```

`Faker.seed(42)` and `fake.seed_instance(42)` reproduce results across fresh
instances when configuration and call sequence match. The provider uses
`self.generator.random` for every field and does not mutate Python's or NumPy's
global RNG. Scalar calls are independent; only `ptbr_profile()` guarantees that
name, UF, CEP, DDD/phone, and RG come from the same row.

Available namespaced methods:

- Profile and names: `ptbr_profile`, `ptbr_name`, `ptbr_first_name`,
  `ptbr_middle_name`, `ptbr_surname`.
- Locations: `ptbr_city`, `ptbr_state`, `ptbr_state_abbr`, `ptbr_cep`,
  `ptbr_postcode`, `ptbr_address`, `ptbr_street`, `ptbr_neighborhood`,
  `ptbr_building_number`.
- Documents and phone: `ptbr_cpf`, `ptbr_rg`, `ptbr_pis`, `ptbr_cnpj`,
  `ptbr_cei`, `ptbr_phone`, `ptbr_phone_number`.

Installation with `formatted=False` removes document punctuation by default;
configure `cep_without_dash=True` separately for CEPs. Document methods accept
per-call `formatted=True/False`; `ptbr_cep` and `ptbr_postcode` accept
`cep_without_dash=True/False`.

Installation options forwarded to the sampler include `cohort`, `time_period`,
`uf`, `sex_conditioning`, `random`, `top_40`, `name_raw`, `always_middle`,
`with_only_one_surname`, `cep_without_dash`, `include_issuer`, and
`make_api_call`. `uniform` and `top40` are compatibility aliases for `random`
and `top_40`; canonical names take precedence.

By default, `aliases=False` does not alter existing Faker methods or locales.
With `aliases=True`, the instance also overrides `name`, `first_name`,
`last_name`, `city`, `state`, `state_abbr`, `postcode`, `address`, `cpf`,
`cnpj`, `pis`, and `phone_number`. Reinstalling replaces only that instance's
PTBR providers, removes earlier aliases when requested, and preserves later
third-party overrides. Multi-locale proxies are supported; each generator keeps
its own RNG.

The provider works offline inside an active asynchronous event loop. With
`make_api_call=True`, synchronous `sample()` cannot resolve CEPs inside an
already-running loop and raises `RuntimeError`; make that call outside the loop
or on a separate thread.

## Data, limits, and reproducibility

- Official geography: 5,571 municipalities and 214,211,951 people in POP2026.
  The runtime CEP base covers 5,570 municipalities and 214,205,968 people.
  Boa Esperança do Norte (IBGE `5101837`, MT, 5,983 residents) lacks legacy CEP
  metadata and cannot be drawn as a city. UF denominators and `alpha_uf` still
  use the complete official population.
- Names: 128,458 national IBGE 2022 rows; surnames: 201,601 national rows and
  459,233 aggregated rows across 27 UFs. Source suppression and omissions are
  not treated as new observations.
- Sex: 123,733 national names have M/F counts; 4,725 null-sex names are removed
  only from M/F conditionals.
- Arpen 2025: 2,537,697 registered births and SIMPLE/COMPOUND/ALL top-50
  rankings for Brazil and all 27 UFs. Only SIMPLE enters the cohort model.
- Second names: 885 cleaned tokens from a legacy 1,187-token extract; 30.99%
  remains a data gap, not an official national statistic.

See [origins, counts, and formulas](docs/data-origins.md),
[architecture](docs/architecture.md), [sources](docs/sources/bibliography.md),
and [third-party notices](THIRD_PARTY_NOTICES.md).

### Rebuild the data

The package already contains the compact artifacts it needs. Maintainers can
run:

```bash
ptbr-data status
ptbr-data fetch
ptbr-data validate
ptbr-data build
ptbr-data validate
```

`ptbr-data fetch --official` also probes the official IBGE v3 API and reports
network failures explicitly. The validated build uses a commit-pinned,
SHA-256-verified IBGE mirror, POP2026, and Arpen. The cache lives outside the
package; the 97,566,720-byte SQLite file supports the build and is not
redistributed. See the [workflow and network limitations](docs/data-origins.md#rebuild-the-artifacts).

## Development and license

Contributors with access to the private repository can run:

```bash
git clone https://github.com/jandira-tech/ptbr-sampler.git
cd ptbr-sampler
uv sync --extra test --extra faker --extra dev
uv run ruff check --no-fix .
uv run ruff format --check .
uv run pytest -q
```

Node.js and `npm install` are needed only for online CEP resolution through
`cep-promise`; its runtime packages are also vendored in the wheel.

The **code** uses the [MIT license](LICENSE), Copyright (c) 2026 Jandira Tech.
IBGE and Arpen data, the third-party mirror, and npm packages have their own
attributions and terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
The code license does not change data licenses or usage conditions.

# Usage

Every example below was executed against the published `ptbr-sampler==0.3.0` wheel from PyPI.
Install with:

```bash
pip install "ptbr-sampler[faker]==0.3.0"     # core + Faker provider
# or
uv add "ptbr-sampler[faker]==0.3.0"
```

The wheel is **102.8 KiB** (`< 150 KiB`); the 195 runtime datasets are fetched lazily from
the SHA-256-pinned Hugging Face repo
[`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data) on
first use and cached under `~/.cache/ptbr-sampler/<hf_revision>/`.

## Python API: `sample()`

```python
import random
from ptbr_sampler import sample

# Full coherent profile (name, UF, city, CEP, street, phone, CPF, RG, PIS, CNPJ, CEI).
# rng= gives a deterministic, thread-safe stream without touching global random state.
profile = sample(q=1, all_data=True, uf_conditioning=True, rng=random.Random(2026))
```

```python
from ptbr_sampler import TimePeriod, sample

# Fixed UF + joint UF x sex conditioning (2022 has no direct UF x sex table,
# so opt into Bayes composition explicitly):
batch = sample(
    q=5, uf='RJ', sex_conditioning='F',
    conditioning_mode='estimated', formatted=False,   # raw digits for documents
    rng=random.Random(42),
)

# Birth cohort 2020-2022 (Census 2022):
cohort = sample(q=5, time_period=TimePeriod.PERIOD_2020_2022, rng=random.Random(7))

# Legacy Census 2010 vintage (explicit opt-in):
legacy = sample(q=3, census_year=2010, rng=random.Random(1))

# Determinism check: same seed -> identical output, global RNG untouched.
a = sample(q=2, all_data=True, rng=random.Random(42))
b = sample(q=2, all_data=True, rng=random.Random(42))
assert a == b
```

`sex_conditioning` accepts `'M'`, `'F'`, `'mixed'` (50/50), and `'population'`
(observed 2022 national sex share; requires `census_year=2022`). In the default
`conditioning_mode='strict'`, asking for an unobserved joint (e.g. `uf` + `sex_conditioning`)
raises a `ValueError` that tells you to pass `conditioning_mode='estimated'`.

## Name sampling directly

```python
import random
from ptbr_sampler import BrazilianNameSampler

sampler = BrazilianNameSampler.from_parquet(census_year=2022)   # default vintage

components = sampler.get_random_name(uf='SE', return_components=True, rng=random.Random(99))
# NameComponents(first_name='Gustavo', middle_name=None, surname='da Silva Araujo')

batch = sampler.batch_sample_names(3, rng=random.Random(7))     # vectorized O(1) draws
```

## Locations

```python
import random
from ptbr_sampler import BrazilianLocationSampler
from ptbr_sampler.datasets import ensure_data_file

loc = BrazilianLocationSampler(ensure_data_file('cities_with_ceps.json'))
loc.get_random_location(uf='SP', rng=random.Random(5))
# 'São Bernardo do Campo, São Paulo (SP), 09853-450'
loc.get_state_and_city(uf='RJ', rng=random.Random(5))
# ('Rio de Janeiro', 'RJ', 'Rio de Janeiro')
```

## Documents (check-digit valid)

```python
import random
from ptbr_sampler.utils.cpf import random_cpf
from ptbr_sampler.utils.cnpj import random_cnpj

random_cpf(rng=random.Random(3))    # '355.512.575-33'  (modulo-11 valid)
random_cnpj(rng=random.Random(3))   # '41.939.071/0005-65'
```

PIS/PASEP, CEI, state-specific RG, and phone numbers are in `ptbr_sampler.utils.*`
(`random_pis`, `random_cei`, `random_rg`, `generate_random_phone`, ...), all accepting `rng=`.

## Faker integration

```python
from faker import Faker
from ptbr_sampler.faker import install_ptbr

fake = install_ptbr(
    Faker('pt_BR'),
    uf_conditioning=True,
    sex_conditioning='population',
    conditioning_mode='estimated',
)
fake.seed_instance(12345)

profile = fake.ptbr_profile()        # coherent dict: UF <-> city <-> CEP <-> DDD <-> RG
name = fake.ptbr_name()              # Census 2022 frequency-weighted full name
surname = fake.ptbr_surname()        # two-slot surname without stem duplication
cpf = fake.ptbr_cpf(formatted=True)  # modulo-11 valid synthetic CPF
rg_sp = fake.ptbr_rg(uf='SP')        # SSP-SP state-specific RG format

# Opt-in: also bind standard aliases (fake.name(), fake.cpf(), fake.city(), ...)
fake_aliased = install_ptbr(Faker('pt_BR'), aliases=True, uf='MG')
```

By default (`aliases=False`) standard `Faker('pt_BR')` methods are untouched; the `ptbr_*`
formatters are namespaced. `fake.seed_instance(S)` reproduces isolated sequences; for
multi-locale proxies (`Faker(['pt_BR', 'en_US'])`) use `Faker.seed(S)`.

## CLI

```bash
# Rich table (default), JSON, or JSONL output
ptbr generate -n 5                     # 5 full profiles as a table
ptbr generate -n 2 --uf SP --format json --quiet
ptbr generate -n 100 -a -sj out.jsonl  # all fields, streamed to JSONL

# Conditioning
ptbr generate -n 5 --uf RJ --sex-conditioning F --conditioning-mode estimated
ptbr generate -n 5 --sex-conditioning population        # default census 2022
ptbr generate -n 3 --census-year 2010 --time-period ate1990

# Data provenance and runtime cache
ptbr sources                            # origin of every dataset
ptbr sources -k surname --census-year 2022
ptbr datasets status --census-year 2022 [--verify]      # cache vs remote, SHA-256 check
ptbr datasets prefetch --census-year 2022               # warm the cache (Docker builds)
ptbr datasets prefetch --all-vintages
ptbr datasets clear-cache
```

## Runtime environment variables

| Variable | Effect |
| --- | --- |
| `PTBR_SAMPLER_DATA_DIR` | Read-only override directory with runtime files (container mount, e.g. `/opt/ptbr-data`) |
| `PTBR_SAMPLER_IGNORE_LOCAL_DATA=1` | Ignore a source-checkout `ptbr_sampler/data/` and use only the override/cache |
| `PTBR_SAMPLER_CACHE_DIR` | Cache root override (default `~/.cache/ptbr-sampler` or `$XDG_CACHE_HOME/ptbr-sampler`) |
| `PTBR_SAMPLER_OFFLINE=1` | Block all runtime HTTP; use only local override/cache |
| `PTBR_SAMPLER_HF_REPO` / `PTBR_SAMPLER_HF_REVISION` | Override the pinned dataset repo / 40-char commit SHA |

Typical air-gapped container:

```bash
ptbr datasets prefetch --all-vintages          # at image build time
PTBR_SAMPLER_OFFLINE=1 ptbr generate -n 10     # at run time, zero network
```

## Privacy note

All output is synthetic, sampled from aggregate census marginals (cells `>= 20` nationally,
`>= 15` per UF) plus algorithmic check digits. No real-person microdata exists anywhere in the
pipeline; do not treat generated values as real identities.

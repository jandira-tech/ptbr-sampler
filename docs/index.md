# ptbr-sampler

**Realistic Brazilian synthetic data from IBGE Census 2022** — given names, surnames,
locations, CEPs, phones, and check-digit-valid documents (CPF, RG, PIS/PASEP, CNPJ, CEI) —
in an ultra-slim **< 150 KiB** Python wheel whose 195 runtime datasets are fetched lazily
from a SHA-256-pinned Hugging Face repository
([`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data)).

- **PyPI:** [`pip install "ptbr-sampler[faker]"`](https://pypi.org/project/ptbr-sampler/)
- **Source:** [github.com/jandira-tech/ptbr-sampler](https://github.com/jandira-tech/ptbr-sampler) (MIT License, © 2026 Jandira Tech)
- **Technical report:** [docs/technical-report.md](technical-report.md)

## Quickstart

```python
from ptbr_sampler import sample

# Deterministic, thread-safe, and fully offline-capable (runtime data is cached
# after the first draw or via `ptbr datasets prefetch`).
profiles = sample(n=3, uf='SP', sex='F', rng=__import__('random').Random(42))
for p in profiles:
    print(p['name'], '|', p['cpf'], '|', p['city'], '-', p['state'])
```

```python
from faker import Faker
from ptbr_sampler.faker import PTBRProvider, install_ptbr

fake = Faker('pt_BR')
install_ptbr(fake)          # adds ptbr_name, ptbr_cpf, ptbr_city, ... formatters
fake.seed_instance(7)
print(fake.ptbr_profile())  # coherent name + documents + address for one persona
```

## Why Census 2022 by default?

Starting with `0.3.0`, `ptbr-sampler` samples from the **IBGE Demographic Census 2022**
(`census_year=2022`, `TimePeriod.ALL`, $N = 203{,}080{,}756$ residents): `128,458` given
names and `201,601` surnames with observed male/female counts (`99.8207%` of national
mass directly observed, `0.0%` LLM-imputed), 27 UF marginals, and 9 birth cohorts. The
legacy `census_year=2010` vintage remains available as an explicit opt-in.

The mathematical foundations — IBGE `Liv102228` confidentiality censoring, `strict` vs
`estimated` conditioning, Kahan-compensated Walker–Vose alias tables
($L_\infty = 1.39 \times 10^{-17}$), and the four-layer goodness-of-fit validation suite —
are derived in the [Technical Report](technical-report.md).

## Site contents

- [Technical Report](technical-report.md) — statistical methodology, numerical analysis,
  and runtime architecture across `0.1.0` → `0.3.0`
- [Architecture](architecture.md) — package layout, runtime dataset resolution, and CI gates
- [Data Origins & Provenance](data-origins.md) — per-dataset estimands and license boundaries
- [Data Sources](sources/bibliography.md) — IBGE, `olob0/ibge-nomes-no-brasil-2022`,
  Brasil.IO `genero-nomes`, Arpen-Brasil, Correios/ViaCEP, Anatel

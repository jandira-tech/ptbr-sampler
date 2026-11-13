# A 102.8 KiB wheel with census-grade data: pinned Hugging Face runtime, seedable RNG, and Faker

*Part 3 of the `ptbr-sampler` `0.3.0` series (English).*

```bash
pip install "ptbr-sampler[faker]==0.3.0"   # wheel: 102.8 KiB (< 150 KiB)
```

The wheel ships **only** `ptbr_sampler/data/dataset_manifest.json` (~16 KiB). The `195`
runtime artifacts (Parquet partitions + JSON support tables) live in the Hugging Face dataset
[`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data) at an
**immutable 40-character commit SHA** (`c30ef6ac3dbf2d1508e41dce7b6a6e47d8e6dbde`) and are
fetched lazily on first use.

## Cryptographic runtime resolution

Each artifact entry in the manifest carries its `sha256` and `size_bytes`. At runtime,
`ptbr_sampler/datasets.py::ensure_data_file` resolves in strict order:

1. **`PTBR_SAMPLER_DATA_DIR`** — read-only container/volume mount (e.g. `/opt/ptbr-data`);
   containment-checked and, with `verify_sha256=True`, digest-verified.
2. **Local source checkout** (`ptbr_sampler/data/...`), unless `PTBR_SAMPLER_IGNORE_LOCAL_DATA=1`.
3. **Verified HF cache** `~/.cache/ptbr-sampler/<hf_revision>/` (override:
   `PTBR_SAMPLER_CACHE_DIR`).

Downloads stream into `<dest>.<pid>.part` under a cross-process `fcntl.flock` on
`<dest>.lock`, are checked for exact byte count **and** SHA-256 against the manifest, then
atomically committed with `os.replace` — safe for concurrent `pytest -n auto` workers and
Gunicorn/Uvicorn processes. `PTBR_SAMPLER_OFFLINE=1` deterministically blocks all HTTP egress
(air-gapped/Docker operation), and `ptbr datasets prefetch --census-year 2022` pre-warms the
cache at image build time (`ptbr datasets status | clear-cache` inspect/clear it).

```bash
ptbr datasets prefetch --census-year 2022   # warm the runtime cache
PTBR_SAMPLER_DATA_DIR=/opt/ptbr-data ptbr generate -n 5   # container override
```

## Seedable, zero-global-mutation randomness

Shared global RNGs break reproducibility in multi-tenant apps. Every public API accepts
`rng: random.Random | None`:

```python
import random
from ptbr_sampler import sample

a = sample(q=3, all_data=True, rng=random.Random(42))
b = sample(q=3, all_data=True, rng=random.Random(42))
assert a == b                       # bit-identical; global random/numpy state untouched
```

Internally, an injected `random.Random` spawns an ephemeral
`np.random.default_rng(rng.getrandbits(128))` for vectorized alias draws — without reading,
reseeding, or restoring module-global `random` or `numpy.random`. `PartitionStore` LRU
mutations and sampler caches are guarded by `threading.RLock`, and batch groups are sorted
lexicographically before drawing so output depends only on the seed, never on hash ordering.

## First-class Faker integration

```python
from faker import Faker
from ptbr_sampler.faker import PTBRProvider, install_ptbr

fake = Faker('pt_BR')
install_ptbr(fake)                    # namespaced: fake.ptbr_name(), fake.ptbr_cpf(), ...
fake.seed_instance(7)
print(fake.ptbr_profile())            # coherent persona: name + CPF + city + address
print(fake.ptbr_name())
```

`PTBRProvider` adds `ptbr_profile` plus $O(1)$ formatters (`ptbr_name`, `ptbr_first_name`,
`ptbr_first_name_female`, `ptbr_first_name_male`, `ptbr_middle_name`, `ptbr_surname`,
`ptbr_state`, `ptbr_city`, `ptbr_cep`, `ptbr_address`, `ptbr_cpf`, `ptbr_pis`, `ptbr_cnpj`,
`ptbr_cei`, `ptbr_rg`, `ptbr_phone`, ...) and preserves standard `Faker('pt_BR')` methods
unless you explicitly opt into `aliases=True`. Seeding is fully deterministic:
`fake.seed_instance(S)` reproduces isolated sequences; for multi-locale proxies
(`Faker(['pt_BR', 'en_US'])`) use `Faker.seed(S)`.

## Release engineering

`0.3.0` landed on `main` as `5362c94` via [PR #46](https://github.com/jandira-tech/ptbr-sampler/pull/46)
with the SonarCloud Quality Gate **PASS** (0 new issues, 0 security hotspots, 0.6%
duplication), Socket Security **PASS**, all 25 CodeRabbit findings resolved and replied, and
**554 tests passing (90% coverage)** under `uv run pytest -n auto -q`. The published wheel is
`102.8 KiB` with only `dataset_manifest.json` inside `ptbr_sampler/data/`; documentation is
built with MkDocs Material (`mkdocs build --strict` clean) and hosted at
<https://ptbr-sampler.readthedocs.io/>.

*Read the full derivations in the [Technical Report](../../technical-report.md).*

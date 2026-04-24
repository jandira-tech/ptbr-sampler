# Data and sampling architecture

The sampler was previously built around nested Python dictionaries loaded from
JSON. That design does not scale once names are conditioned on
`(uf × decade × sex)` and surnames on `(uf × period)` — roughly 540 first-name
tables and 270 surname tables, most with 200–50,000 entries each. Python dict
overhead alone (~240 B per entry) eats the memory budget before the raw
numbers do.

This document describes the architecture that replaces it. Three decisions
collapse the problem:

## 1. Storage — partitioned Parquet

```
src/data/parquet/
├── first_names/uf=<UF>/decade=<decade>/sex=<M|F>/part.parquet
├── surnames/uf=<UF>/period=<period>/part.parquet
├── middle_names/part.parquet
├── states/part.parquet
└── cities/part.parquet
```

Columns in each partition: `name` (dictionary-encoded string), `count` (u32),
`weight` (f32, pre-normalised within the partition so it sums to 1).

Read via `pyarrow.dataset` with filter pushdown — only the partitions actually
referenced by the conditioning tuple are materialised. The rest stays on disk.
The same files can be queried ad-hoc through DuckDB without re-ingestion.

JSON is fine up to ~10 MB. Above that, Python dict overhead alone (≈240 B per
entry) eats you before the raw numbers do. The 2022 Census surname data
conditioned by UF × period is several hundred MB as JSON but under ~50 MB as
Parquet with dictionary encoding.

## 2. Sampling — Walker/Vose alias method

`random.choices` and `numpy.random.choice(p=…)` both rebuild cumulative
weights on every call — O(m) per draw, where m is the support size. For a
50k-entry surname distribution that is tens of milliseconds per sample and
scales linearly with m.

The alias method is O(m) to build once, O(1) per draw forever after, and
fully vectorisable. See `src/sampling/alias.py` for the implementation.

The cost structure is now identical for `k=1` and `k=100_000` — the property
we want. See the scaling table in `README.md`.

## 3. Lazy-load with bounded LRU

Population is concentrated — SP/MG/RJ alone cover ~40% of state draws, which
means most `(uf, period, sex)` tuples are rarely hit. `PartitionStore` wraps
partition loading in a bounded LRU keyed on the conditioning tuple. Hot
conditions stay resident, cold ones page from disk and build their alias
tables on first touch.

See `src/sampling/store.py`.

## Cost profile

| n | Cold (first time this condition seen) | Warm |
|---:|---|---|
| 1 | ~50–200 ms | ~1–10 µs |
| 1,000 | ~50–200 ms | ~1 ms |
| 100,000 | ~50–200 ms | ~20–50 ms (memory-bandwidth bound) |

Cold cost is disk I/O plus alias construction. It is **fixed**, not
proportional to `n`. Cold-start amortises across a run as more conditions get
cached.

## What `--batch` means now

The old sampler branched statistically on batch size:

```python
if actual_qty > 1:
    batch_sample_names(...)
else:
    get_random_name(...)
```

Both paths are now the same vectorised alias lookup with `k=1` or `k=N`. The
`--batch` flag is kept purely as a **flush-to-disk cadence** for JSONL writes
(how often `fsync` is called, how many records sit in the in-memory buffer).
This removes a latent source of statistical drift between the two paths.

## Validation

`tests/test_distribution_validation.py` uses `scipy.stats.chisquare` and
`scipy.stats.ks_2samp` to verify that 100k-sample empirical marginals match
the ingested weights per condition. This catches alias-table bugs and
data-ingestion regressions.

## Known gaps (not fixed by the architecture)

1. **Middle-name vocabulary contamination.** `src/data/middle_names.json`
   contains surnames (`Araújo`, `Borges`, `Bezerra`, …), the administrative
   token `Cancelado`, and a bare `-`. No alias table fixes dirty tokens. A
   vocabulary-filtering pass against the first-name whitelist lives in
   `src/sampling/vocabulary.py` and `scripts/clean_middle_names.py`.
2. **Sex conditioning in the current first-name file.** The committed
   `names_data.json` has no sex dimension. The IBGE 2022 release does. Until
   2022-conditioned data is ingested into `first_names/uf=…/decade=…/sex=…/`,
   first names will be sex-mixed in output.

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
ptbr_sampler/data/parquet/
├── first_names/uf=<UF>/decade=<decade>/sex=<M|F>/part.parquet
├── surnames/uf=<UF>/period=<period>/part.parquet
├── middle_names/part.parquet
├── states/part.parquet
└── cities/part.parquet
```

Columns in each partition: `name` (dictionary-encoded string), `count` (uint64),
`weight` (f32, pre-normalised within the partition so it sums to 1).

Read via `pyarrow.dataset` with filter pushdown — only the partitions actually
referenced by the conditioning tuple are materialised. The rest stays on disk.
The same files can be queried ad-hoc through DuckDB without re-ingestion.

`BrazilianNameSampler` consults the Parquet store before falling back to the
JSON payload. In practice the production entry point
(`ptbr_sampler.sampler.sample`) is wired to the bundled tree, so every first
name, surname, and middle-name draw is materialised from a Parquet partition
on first use. Pass `parquet_root=None` (or construct with a bespoke dict) to
force JSON-only mode — that's the path exercised by `mock_name_data` unit
tests that need to override the distribution.

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
fully vectorisable. See `ptbr_sampler/sampling/alias.py` for the implementation.

The cost structure is now identical for `k=1` and `k=100_000` — the property
we want. See the scaling table in `README.md`.

## 3. Lazy-load with bounded LRU

Population is concentrated — SP/MG/RJ alone cover ~40% of state draws, which
means most `(uf, period, sex)` tuples are rarely hit. `PartitionStore` wraps
partition loading in a bounded LRU keyed on the conditioning tuple. Hot
conditions stay resident, cold ones page from disk and build their alias
tables on first touch.

See `ptbr_sampler/sampling/store.py`.

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

## Realism vs. random mode

The default sampler path is **realism-by-default**: geography is drawn first
(population-weighted state, then population-weighted city within that state),
and names are drawn from the alias tables that encode the IBGE-derived
empirical frequencies.

Callers can opt out of realism via `random=True` (Python API) or `--random`
(CLI). The escape hatch:

- draws states and cities **uniformly** instead of population-weighted,
- draws first names, middle names, and surnames **uniformly** across the
  alias tables (`AliasTable.sample_uniform`) instead of frequency-weighted,
- replaces the empirical 30.99% middle-name flag with a flat 50% coin flip.

This is intentional: `random=True` is for callers who explicitly want
maximally non-deterministic, distribution-free output. The default
remains realism-tracking.

The realistic default only conditions on **dimensions that actually exist
in the bundled data**: `period` for first names, `scope=national` for
surnames, and population shares for geography. UF-, sex-, and
period-conditioned surname realism remain blocked on the IBGE 2022
ingest (see `docs/data-origins.md` and the README "Known realism gaps").

## Known gaps (not fixed by the architecture)

1. **Middle-name vocabulary contamination.** `ptbr_sampler/data/middle_names.json`
   contains surnames (`Araújo`, `Borges`, `Bezerra`, …), the administrative
   token `Cancelado`, and a bare `-`. No alias table fixes dirty tokens. A
   vocabulary-filtering pass against the first-name whitelist lives in
   `ptbr_sampler/sampling/vocabulary.py`; ingestion through
   `scripts/ingest_to_parquet.py` applies it by default and writes the
   cleaned distribution to `parquet/middle_names/`. Pass
   `--skip-middle-names-filter` to inspect the raw distribution.
2. **Sex conditioning — experimental, top-20.** The committed
   `names_data.json` has no sex dimension; the default path stays
   sex-mixed. The IBGE Nomes v2 ranking endpoint exposes
   `(UF, sex, decade)` triples (top-20 each), and
   `scripts/download_datasets.py --fetch-ibge-nomes` ingests them into
   `first_names/uf=<UF>/period=<P>/sex=<S>/`. Turn it on with
   `experimental_uf_sex_conditioning=True` (Python) or
   `--experimental-uf-sex` (CLI). The sampler still falls back to the
   period-only table per row when a specific partition is missing.
3. **UF-conditioned surnames.** The 2022-Census surname tables by UF
   live in the IBGE web app only — no public API, no bulk download.
   Surnames stay on the pooled-national distribution today.
4. **Time horizon capped at `UNTIL_2010`.** The bundled first-name buckets
   stop at the 2010 Census. Recent cohorts (born 2011–2024) are not
   directly represented; whole-population realism for "people alive
   today" is still useful, but newborn-flow realism for 2024 needs the
   Arpen 2024 ranking as a separate benchmark (`docs/sources/arpen-2024-rankings.md`).
5. **`percentage_with_second = 30.99%`.** Computed from the raw
   `total_with_second_names / total_people` ratio in `middle_names.json`;
   transparent for that corpus, but the corpus itself is the authorial
   extraction, not an IBGE dissemination. Read it as a transparent
   estimate, not as a population-level statistic.

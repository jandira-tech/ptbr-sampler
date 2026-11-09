# Archived Brasil.IO / `genero-nomes` sex-prior investigation (2026-05-09)

> **Legacy provenance, not the current sex source.** The old period-by-sex
> generation described below was superseded in 0.3.0 by empirical national IBGE
> 2022 counts: 123,733 names, with 4,725 null-sex names excluded only from M/F
> conditionals. Legacy files remain packaged for compatibility/audit; the
> current Arpen/IBGE cohort build does not fall back to Brasil.IO or Gemini.
> Coverage percentages and commands below are historical and are not required
> for normal sampling or the supported `ptbr-data` rebuild. See [current sex
> provenance](../data-origins.md#suppression-and-sex) and
> [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

## What it is

A per-name male/female frequency table for Brazilian first names, curated by
Álvaro Justen (`@turicas`) and published by [Brasil.IO](https://brasil.io/)
under the dataset slug **`genero-nomes`**. It contains 100,787 unique first
names with `frequency_male`, `frequency_female`, `frequency_total`,
classification (`F`/`M`), and grouped alternative spellings.

## Why it's bundled

The IBGE Nomes API v2 ranking endpoint exposes per-name counts conditioned on
`(localidade, sexo, decada)` — but only as **top-20** results per condition.
To condition our period-only sampler on sex *while preserving the long tail*,
we need a per-name sex prior that covers the full ~40k-name distribution
already in `names_data.json`.

Brasil.IO's `genero-nomes` is the only public dataset that meets this
requirement: it was built by hitting the same IBGE Nomes API per-name endpoint
across the full long tail (see Brasil.IO's
[blog post on the methodology](https://blog.brasil.io/2019/05/31/classificando-nomes-por-genero-usando-dados-publicos/index.html)).
Provenance is therefore **the same IBGE Nomes API as our period data, just
covering a different axis** — not an unrelated dataset.

## Source URLs

- Dataset landing page: <https://brasil.io/dataset/genero-nomes/files/>
- Direct CSV download: <https://data.brasil.io/dataset/genero-nomes/nomes.csv.gz>
  (~1.8 MB compressed; ~6.5 MB uncompressed)
- Methodology + source code (turicas/genero-nomes):
  <https://github.com/turicas/genero-nomes>
- Brasil.IO methodology blog post:
  <https://blog.brasil.io/2019/05/31/classificando-nomes-por-genero-usando-dados-publicos/index.html>

## How to fetch it

```bash
python -m scripts.download_datasets --fetch-genero-nomes
# Writes ptbr_sampler/data/raw/genero_nomes/nomes.csv.gz and gunzips to nomes.csv.
```

The downloader prints the source URL and the local target path so the
provenance is captured in stdout, not just inside the script.

## How it's consumed

`scripts/ingest_to_parquet.py` produces two artefacts from this CSV:

1. **`parquet/sex_prior/scope=national/part.parquet`** — the raw sex prior
   table with columns
   `(name, count_male, count_female, count_total, p_male, p_female,
   classification, group_name)`. This is the auditable "what we read"
   partition; downstream code joins on `name` to look up `p_sex`.
2. **`parquet/first_names/period=<P>/sex=<S>/part.parquet`** — period × sex
   national first-name partitions, derived from the period-only IBGE Nomes
   percentages multiplied by `p_sex(name)` and renormalised within
   `(period, sex)`. The full long tail is preserved (8k–24k rows per
   partition); names absent from the genero-nomes dump are dropped because
   we have no defensible sex prior for them.

Each new partition gets a `data_origin.json` sidecar with the source URL,
fetch timestamp, row count, and the derivation formula — so a reviewer
unfamiliar with the codebase can confirm the partition wasn't generated out
of thin air.

## Sampler integration

Pass `sex_conditioning='M'`, `'F'`, or `'mixed'` to
`ptbr_sampler.sampler.sample(...)`, or `--sex-conditioning {M,F,mixed}` on the
CLI. See `docs/data-origins.md` §1 for the resolution chain and
`docs/sources/bibliography.md` for the cross-reference to the IBGE Nomes API.

## Coverage caveat

Across all (name, period) cells in `names_data.json`, the genero-nomes
prior matches **91.9 %** (203,314 of 221,346 cells). The 8.1 % unmatched are
typically very rare names that were never returned by IBGE's per-name endpoint
when Brasil.IO ran the scrape; they're dropped from the period × sex
partitions but remain available in the period-only partition (so disabling
`sex_conditioning` falls back cleanly).

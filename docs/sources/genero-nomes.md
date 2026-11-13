# brasil.io / `genero-nomes` (sex prior)

## What it is

A per-name male/female frequency table for Brazilian first names, curated by
Álvaro Justen (`@turicas`) and published by [Brasil.IO](https://brasil.io/)
under the dataset slug **`genero-nomes`**. It contains 100,787 unique first
names with `frequency_male`, `frequency_female`, `frequency_total`,
classification (`F`/`M`), and grouped alternative spellings.

## Why it's supported (legacy `census_year=2010` vintage)

> **Scope note (`0.3.0`):** Default `census_year=2022` sampling does **not** use `brasil.io/genero-nomes`; it uses directly published 2022 Census `male_count` / `female_count` observations (`99.8207%` empirical mass coverage; see [`ibge-nomes-no-brasil-2022.md`](ibge-nomes-no-brasil-2022.md)). `genero-nomes` powers sex conditioning when callers explicitly opt into `--census-year 2010` / `census_year=2010`.

The IBGE Nomes API v2 ranking endpoint exposes per-name counts conditioned on
`(localidade, sexo, decada)` — but only as **top-20** results per condition.
To condition the historical 2010 period-only sampler on sex *while preserving the long tail*,
we need a per-name sex prior that covers the ~64k-name distribution
in legacy `names_data.json`.

**Important CSV parsing distinction:** In `brasil.io/genero-nomes`, blank `frequency_male` / `frequency_female` CSV fields arise from Brasil.IO's scraper joining single-sex API responses and are parsed as `0` within the 2010 scrape's schema. That convention applies **only** to `genero-nomes` CSV parsing — never to IBGE Census 2022 `name_detail.parquet`, where `NULL` denotes confidentiality-censored cells `< 20` (`one_null_exact_zero` when $N - N_{\text{obs}} = 0$ vs. `one_null_suppressed_positive` when $1 \le N - N_{\text{obs}} \le 19$).

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
uv run python -m scripts.download_datasets --fetch-genero-nomes
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
2. **`parquet/first_names/period=<P>/sex=<S>/part.parquet`** — legacy `census_year=2010`
   period × sex national first-name partitions, derived from the period-only IBGE Nomes
   percentages multiplied by `p_sex(name)` and renormalised within
   `(period, sex)`. The full long tail is preserved (8k–24k rows per
   partition); for the ~8.1% of `(name, period)` cells absent from `genero-nomes`,
   `scripts/ingest_to_parquet.py` merges the LLM gap-fill table documented in
   [`gemini-gender-classifications.md`](gemini-gender-classifications.md)
   (`count=0` prior rows tagged with `source='gemini-3.1-flash-lite-preview'`),
   dropping unmatched names only when `classifications.jsonl` is absent (default
   `census_year=2022` uses IBGE `name_detail` directly with zero LLM gap-fill).

Each new partition gets a `data_origin.json` sidecar with the source URL,
fetch timestamp, row count, and the derivation formula — so a reviewer
unfamiliar with the codebase can confirm the partition wasn't generated out
of thin air.

## Sampler integration

Pass `sex_conditioning='M'`, `'F'`, `'mixed'`, or `'population'` with
`census_year=2010` to `ptbr_sampler.sampler.sample(...)`, or
`--census-year 2010 --sex-conditioning {M,F,mixed,population}` on the
CLI. See `docs/data-origins.md` §1 for the resolution chain and
`docs/sources/bibliography.md` for the cross-reference to the IBGE Nomes API.

## Coverage caveat

Across all `(name, period)` cells in legacy `names_data.json`, the empirical
`genero-nomes` prior matches **91.9 %** (203,314 of 221,346 cells). The
remaining **8.1 %** unmatched cells (`< 1%` probability mass, mostly civil-registry
spelling variants) are gap-filled in the published `census_year=2010` partitions by
[`gemini-gender-classifications.md`](gemini-gender-classifications.md) (`count=0`
prior rows with `source='gemini-3.1-flash-lite-preview'`) and are dropped only if
ingestion runs without `classifications.jsonl`.

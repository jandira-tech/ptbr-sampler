# Maintainer Runbook — Fetch, Ingest, Audit, and Publish Datasets (`0.3.0`)

This runbook documents the end-to-end dataset workflow for `ptbr-sampler` `0.3.0`: fetching the pinned Census 2022 compilation (`olob0/ibge-nomes-no-brasil-2022`), building `float64` Parquet partitions, running the four-layer statistical audit, and publishing runtime artifacts to Hugging Face Hub (`arthrod/ptbr-sampler-data`).

---

## Prerequisites

- Python `3.12+` and `uv`
- Outbound HTTPS access to `huggingface.co` (`*.hf.co` CDN)
- For publishing only: `HF_TOKEN` with write permission to `arthrod/ptbr-sampler-data`

```bash
uv sync --extra test --extra dev
```

---

## Step 1 — Fetch Pinned Census 2022 Parquet Tables (`8.23 MiB`)

`scripts.download_datasets --fetch-ibge-2022` downloads the 5 Parquet files from `olob0/ibge-nomes-no-brasil-2022` at immutable commit `05efb85c92af43da2ed4ed088d1e0c9f17160e65`:

```bash
python -m scripts.download_datasets --fetch-ibge-2022
```

- Ordinary reruns **validate** existing files in `ptbr_sampler/data/raw/ibge_nomes_2022/` against their pinned SHA-256 digests, row counts, and Parquet schemas, skipping valid cached files and refusing corrupt ones; pass `--overwrite` to force a fresh network download.
- Writes `ptbr_sampler/data/raw/ibge_nomes_2022/source_manifest.json` recording per-file SHA-256, byte size, row count, and `fetched_at_utc`.

| File | Rows | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| `name_ranking.parquet` | `330,059` | `1,738,567` | `635691d3ce52eb59c242ecb886dbaab62b4b42e6bed4b4f1766f8c6725636c64` |
| `name_detail.parquet` | `330,058` | `2,250,879` | `91518f2d0d1da8e438ab9f557127da06633e186914aecb717f1bbf7bfb6b2943` |
| `name_by_decade.parquet` | `221,524` | `910,784` | `9f852814bf42a47358841c054a70939c763c4fc70c7e38564ad44fb94b7fbdef` |
| `name_by_state.parquet` | `828,567` | `3,729,128` | `5588f012d43bb38b07691044010eb7e96cb2bfc359dd3b53a6c3b0ea46f1504e` |
| `state.parquet` | `27` | `1,285` | `5d4aa2a4faf4cdef421f2563de63cd8298b58113779774045a29b9e13ddebc55` |

*(Optional for historical `census_year=2010` sex conditioning: `python -m scripts.download_datasets --fetch-genero-nomes`.)*

---

## Step 2 — Ingest `float64` Partitioned Parquet Layout

```bash
python -m scripts.ingest_to_parquet
```

This atomically stages and swaps `ptbr_sampler/data/parquet/census_year=2022/` (`69` partitions across `first_names`, `sex_prior`, `surnames`, and `states`) alongside the legacy 2010 partitions (`first_names/period=ate*`, `surnames/scope=national`, `middle_names`, `states`).

---

## Step 3 — Run Raw & Cross-Table Statistical Audit + Tests

```bash
python -m scripts.audit_datasets \
  --raw-dir ptbr_sampler/data/raw/ibge_nomes_2022 \
  --parquet-dir ptbr_sampler/data/parquet/census_year=2022

uv run pytest -n auto -q
```

---

## Step 4 — Update Manifest / Publish Runtime Bundle to Hugging Face Hub

```bash
# Local manifest refresh only (no upload):
python -m scripts.publish_hf_dataset --manifest-only

# Publish to Hugging Face Hub and pin the returned 40-char commit OID in dataset_manifest.json:
python -m scripts.publish_hf_dataset --publish --repo-id arthrod/ptbr-sampler-data
```

---

## Step 5 — Verify Slim Wheel (`< 150 KiB`) & Runtime Cache Prefetch

```bash
uv build
ptbr datasets prefetch --census-year 2022
ptbr datasets status --verify
PTBR_SAMPLER_OFFLINE=1 ptbr generate --qty 5 --uf-conditioning
```

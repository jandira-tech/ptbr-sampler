# Gemini gender classifications (gap-fill source)

## What it is

A per-name `M` / `F` / `U` classification produced by the Google Gemini
model `gemini-3.1-flash-lite-preview` for the **8 % of names** in
`names_data.json` that are not present in
[`brasil.io/genero-nomes`](genero-nomes.md). Stored as
`ptbr_sampler/data/raw/gemini_gender/classifications.jsonl`, one row per
name.

These rows are **LLM-derived, not empirical IBGE data**. Every parquet
partition that pulls them in carries a `source` column distinguishing them
from genero-nomes rows so reviewers can audit the provenance.

## Why we use it (legacy `census_year=2010` gap-fill only)

> **Scope note (`0.3.0`):** Gemini gender classifications are **never** used in the default `census_year=2022` pipeline (`0.0%` LLM-assigned mass in 2022, where empirical IBGE `male_count` / `female_count` already cover `99.8207%` of national given-name occurrences; see [`ibge-nomes-no-brasil-2022.md`](ibge-nomes-no-brasil-2022.md)). This gap-fill applies strictly to explicit `census_year=2010` historical mode.

For the 2010 Census vintage, the legacy IBGE Nomes API v2 ranking endpoint (`servicodados.ibge.gov.br/api/v2/censos/nomes/ranking`) exposes only top-20 rankings per `(UF, sex, decade)` and has been intermittently unreachable. In `census_year=2010`, sex conditioning is therefore derived from period-only 2010 percentages multiplied by a per-name sex prior. `brasil.io/genero-nomes` empirically matches **91.9%** (`203,314 / 221,346`) of `(name, period)` cells in `names_data.json`; the remaining ~8.1% are mostly civil-registry typos and spelling variants (`AARECIDA` for *Aparecida*, `ABRUNA` for *Abriana*, `AERIQUE` for *Henrique*…).

To distinguish empirical census counts from uncalibrated LLM labels across the five sex-coverage metrics:
1. **Vocabulary lookup coverage (`2010`):** reaches `100.0%` of `names_data.json` types only after combining `genero-nomes` (`91.9%` of `(name, period)` cells) with Gemini (`8.1%` of cells, `< 1%` probability mass).
2. **Zero fabricated empirical counts:** `scripts/ingest_to_parquet.py` records `count_male = 0`, `count_female = 0`, `count_total = 0` on every `source = 'gemini-3.1-flash-lite-preview'` row (`p_male` / `p_female` carry only the prior direction `1.0/0.0` or `0.5/0.5` for `U`), so synthetic LLM classifications are never mistaken for 1-person IBGE observations.

## Methodology

### Model

```text
gemini-3.1-flash-lite-preview
```

### Concurrency

100 worker threads (`concurrent.futures.ThreadPoolExecutor(max_workers=100)`),
classifying one name per request.

### Prompt (verbatim)

```text
You are classifying Brazilian Portuguese first names by gender. The name is "{name}". Reply with EXACTLY one character — and nothing else:
  M  -> commonly given to males in Brazil
  F  -> commonly given to females in Brazil
  U  -> truly ambiguous unisex in Brazil; use this only exceptionally, because most Portuguese-language given names are gendered. If a name has a clear majority sex even with rare crossover use, return that majority sex (M or F), not U.
Output exactly one character: M, F, or U.
```

The prompt is intentionally restrictive: `U` should be the **exception**,
not a refuge. Across the 7,146 names we ran through, only 123 (1.7 %)
came back as `U` — those are genuinely common-gender or unrecognisable
strings.

### Concurrency limits

The Gemini quota for `gemini-3.1-flash-lite` is **4,000 requests per
minute per project**. The first run of 100 workers burst at ~130 RPS (=
~7,800 RPM) and triggered 480 `429 RESOURCE_EXHAUSTED` errors. The script
honours the server-suggested `retryDelay` (parsed from the SDK's
`ClientError` payload — typically ~30 s) and retries up to 6 times. After
the retry pass, **0 / 7,146 names ended in an error state**.

If you re-run on a key with a stricter quota, drop concurrency with
`--workers 60` (≈ 65 RPS = 3,900 RPM, comfortably under 4,000).

## Idempotency

The script reads its own JSONL on every invocation and skips any name
already present. Re-running is safe; re-running after refreshing
`names_data.json` or `genero-nomes` will only classify the new gap.

To **force re-classification** of a subset (e.g., rows tagged with
`error`), strip those rows from `classifications.jsonl` first and re-run:

```python
import json
from pathlib import Path
src = Path('ptbr_sampler/data/raw/gemini_gender/classifications.jsonl')
keep = [json.loads(l) for l in src.read_text().splitlines() if l]
keep = [r for r in keep if 'error' not in r]
src.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in keep) + '\n')
```

## Output schema

```jsonl
{"name": "AARECIDA", "gender": "F", "model": "gemini-3.1-flash-lite-preview", "classified_at_utc": "2026-05-09T06:55:18+00:00", "raw_response": "F"}
{"name": "AARÃO", "gender": "M", "model": "gemini-3.1-flash-lite-preview", "classified_at_utc": "2026-05-09T06:55:18+00:00", "raw_response": "M"}
```

`raw_response` is the first 64 characters of the model's literal output
(after stripping); useful when auditing why a particular name was
classified the way it was.

Failed rows (after all retries) carry an additional `error` field with
the exception class + message; they're treated as `U` until manually
re-run.

## Audit trail in the parquet layout

When `scripts/ingest_to_parquet.py` runs, it merges the genero-nomes CSV
and this JSONL. The resulting partitions carry the provenance
explicitly:

- `parquet/sex_prior/scope=national/part.parquet` — gains a `source`
  column with values `'brasil.io/genero-nomes'` or
  `'gemini-3.1-flash-lite-preview'`.
- `parquet/first_names/period=<P>/sex=<S>/data_origin.json` — sidecar
  reports `rows_from_genero_nomes` and `rows_from_gemini` separately, so
  any partition's row count breaks down at audit time.
- `parquet/sex_prior/scope=national/data_origin.json` — sidecar carries a
  `source_counts` map: `{genero, gemini_M, gemini_F, gemini_U}`.

Want only the empirical rows? Filter the parquet on `source ==
'brasil.io/genero-nomes'`.

## Current numbers (2026-05-09)

| Bucket | Count | Share |
|---|---:|---:|
| genero-nomes (empirical) | 100,787 | 93.4 % |
| Gemini → M | 3,870 | 3.6 % |
| Gemini → F | 3,153 | 2.9 % |
| Gemini → U | 123 | 0.1 % |
| **sex_prior total** | **107,933** | **100 %** |

After Gemini gap-fill, sex-prior coverage of `(name, period)` cells in
`names_data.json` is **100.0 %** (was 91.9 % from genero-nomes alone).

## Reproducing

```bash
# 1. Get a Gemini API key: https://aistudio.google.com/apikey
export GEMINI_API_KEY=...

# 2. Install the SDK (not a runtime dep of ptbr_sampler).
uv pip install google-genai

# 3. Run the classifier.
python -m scripts.classify_unmatched_names_gemini
# Total runtime for 7,146 names @ 100 workers: ~80 s + retries.

# 4. Fold the results into parquet.
python -m scripts.ingest_to_parquet
```

## Limitations

- **Not empirical.** A model classification is a model judgment. We use
  it only for the names we have no empirical data for, and we mark every
  row so consumers can filter it out if they need strict empirical
  realism.
- **Long-tail rarity.** The unmatched names are heavily skewed toward
  typo'd / single-attestation names. Their period weight is
  proportionally tiny, so even sustained Gemini errors would only
  marginally affect sampling. (Across 17,708 (name, period) cells now
  filled by Gemini, the cumulative weight is < 1 % of total mass per
  partition.)
- **Single-shot prompt.** No chain-of-thought, no examples. We rely on
  the model knowing Brazilian Portuguese name conventions out of the
  box. A re-run with a richer prompt may move ~10 names from `U` into
  `M` / `F`, but the impact on the sampler is negligible.

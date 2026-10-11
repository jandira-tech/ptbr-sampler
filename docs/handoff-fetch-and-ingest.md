# Handoff — fetch raw datasets on a network-enabled machine

This doc lists every action the user needs to take on a machine with
public internet egress. The Claude Code sandbox blocks `ibge.gov.br`,
`arpenbrasil.org.br`, and similar hosts (HTTP 403 / "Host not in
allowlist"), so the fetches must be done off-sandbox. Once these steps
are done, see `docs/handoff-resume-with-claude.md` for what to send
back so Claude can resume implementation.

## Prerequisites

- Python 3.12+
- `uv` installed (or substitute `pip install -e ".[test]"`)
- General internet egress (no IBGE / Anatel / Correios firewall rules)
- Repo checked out at the head of `main`, on a new branch for the data
  (`<data-branch>` below)
- Working directory: repo root

```bash
git switch main
git pull origin main
git switch -c <data-branch>
uv sync --extra test
```

## Task 1 — Inventory the bundled datasets

This step is read-only and confirms what's already in the repo.

```bash
python -m scripts.download_datasets
```

Expected output ends with something like:

```
2 dataset(s) not present locally — see source URLs above.
Once raw datasets are in place, rebuild Parquet with:
    python -m scripts.ingest_to_parquet
To fetch IBGE Nomes API v2 UF x sexo x decada rankings (~486 calls):
    python -m scripts.download_datasets --fetch-ibge-nomes
```

The `[MISS]` rows are informational; we'll address them below.

## Task 2 — Fetch the IBGE Nomes v2 rankings (UF × sexo × década)

This is the big one. The script makes ~486 HTTP requests
(27 UFs × 9 decades × 2 sexes). Each call returns the top 20 names for
that condition.

```bash
python -m scripts.download_datasets --fetch-ibge-nomes
```

What you should see:

- One line per request, e.g. `[ 1/486] wrote ptbr_sampler/data/raw/ibge_nomes_v2/uf=RO/period=ate1930/sex=M.json (20 rows)`
- 486 small JSON files written under
  `ptbr_sampler/data/raw/ibge_nomes_v2/uf=<UF>/period=<P>/sex=<S>.json`
- Total runtime: ~3–5 minutes (script sleeps 0.2s between calls to be a
  good API citizen — change `--sleep-seconds` if needed)

If the IBGE API rate-limits or returns 5xx for some triples, the
script logs and continues. Re-run with `--overwrite` to retry only the
failed ones (it skips already-saved files by default).

**If you see** `network fetch failed ... Host not in allowlist` or a
`URLError` early in the run, you're on a restricted-egress machine —
move to a different one.

## Task 3 — Manually download IBGE *Nomes no Brasil* 2022 (optional)

The 2022-Census surname tables by UF live in the IBGE web app at
<https://www.ibge.gov.br/apps/nomes/>. There is **no public API or bulk
download** — surname realism by UF is currently blocked on this front.

If you want to populate
`ptbr_sampler/data/raw/ibge_nomes_2022/`, you can:

1. Use the web app to look up the per-UF surname rankings of interest
   and capture them as CSV / JSON (manual transcription).
2. Drop the resulting files under
   `ptbr_sampler/data/raw/ibge_nomes_2022/uf=<UF>/<period>.csv` (or
   `.json`).

Once a non-trivial sample is available, send Claude the file layout and
a small payload sample so an ingester analogous to
`ingest_first_names_uf_sex` can be written.

This task is optional — skipping it is fine; surname conditioning will
just stay national-pooled.

## Task 4 — Manually download Arpen 2024 newborn ranking (optional)

The Arpen press release is at:
<https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/>

It's distributed as an HTML page; no API. If you want to capture it:

1. Fetch the HTML and extract the top-10 male / female ranking tables.
2. Save them as `ptbr_sampler/data/raw/arpen_2024/top10_<sex>.json`
   with shape `[{"rank": 1, "name": "Helena", "count": ...}, ...]`.

This is for benchmark / validation purposes and to extend the time
horizon beyond `UNTIL_2010` for newborn-flow realism (`todo.md` task 5).
Optional like Task 3.

## Task 5 — Rebuild the Parquet layout

Once Task 2 completed (and optionally Tasks 3/4):

```bash
python -m scripts.ingest_to_parquet
```

Expected new output line in addition to the existing per-period ingest:

```
Ingesting first names (UF x period x sex) from .../raw/ibge_nomes_v2...
  partitions written: 486
```

Verify the new partitions exist:

```bash
find ptbr_sampler/data/parquet/first_names -mindepth 4 -maxdepth 4 -type d | head -5
# Expected: ptbr_sampler/data/parquet/first_names/uf=AC/period=ate1930/sex=F  (etc.)

find ptbr_sampler/data/parquet/first_names -name part.parquet | wc -l
# Should be at least 486 + 9 = 495
#  - 486 (UF × period × sex)
#  - 9   (period-only fallback)
```

## Task 6 — Run the tests

```bash
uv run --extra test pytest -q
```

The full test suite should still pass. The new partitions should not change
default sampler behaviour (the experimental flag is off by default), so
this is mostly a regression check.

Spot-check the experimental conditioning end-to-end:

```bash
uv run ptbr sample --qty 20 --experimental-uf-sex --return-only-name --name-raw
```

Names should still be plausibly Brazilian, but the diversity is
narrower than the default path — that's expected (top-20 per
condition).

Quick sanity script:

```python
# save as scripts/spot_check_uf_conditioning.py
from sample import sample
from collections import Counter

default = sample(q=200)
exp = sample(q=200, experimental_uf_sex_conditioning=True)

print('default unique first names:', len({r['name'] for r in default}))
print('experimental unique first names:', len({r['name'] for r in exp}))
print('top 5 experimental by state:', Counter((r['state_abbr'], r['name']) for r in exp).most_common(5))
```

(Optional — useful for a sanity check.)

## Task 7 — Commit the new partitions

The bundled Parquet files are ~50 KB compressed each, so 486 of them is
~25 MB. That fits in a regular git repo, though you may want to think
about Git LFS if the team prefers.

```bash
git add ptbr_sampler/data/parquet/first_names ptbr_sampler/data/raw/ibge_nomes_v2
git status   # confirm what's about to be committed
git commit -m "Ingest IBGE Nomes v2 UF x período x sexo rankings"
git push -u origin <data-branch>   # then open a PR into main
```

If you'd rather not commit raw + parquet, push only the parquet
artefacts; the raw JSONs can be re-fetched any time via Task 2.

If the size is a concern: skip the commit, just keep the parquet files
locally and tell Claude what shape they ended up taking — see the
handoff-back doc for what to report.

## Failure modes / troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Host not in allowlist` early in Task 2 | Egress-restricted environment | Run on a different machine |
| `urllib.error.HTTPError 429` mid-run | IBGE API rate limit | Re-run with `--sleep-seconds 1.0`; the script skips already-fetched files |
| `urllib.error.HTTPError 403` consistently | IP block or User-Agent rejection | Open an issue; the request currently identifies as `ptbr-sampler/0.2 (...)` |
| Some triples return 0 rows | Thin data for that (UF, decade, sex) | Expected — those partitions are skipped during ingestion |
| Parquet ingestion succeeds, sampler still uses period-only | Did you set `experimental_uf_sex_conditioning=True`? | Default is off — the flag is the opt-in |

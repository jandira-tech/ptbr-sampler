# Archived handoff — legacy fetch results (2026-05-09)

> **Historical snapshot; not current implementation guidance.** The proposed
> follow-ups below were superseded: version 0.3.0 already has UF-conditioned
> cohorts and surnames, explicit `sex_conditioning='M'|'F'|'mixed'`, historical
> selectors through 2020, Arpen 2025, and `ptbr-data validate`. The experimental
> flag now only provides `mixed` compatibility. Use
> [current data origins](data-origins.md), [architecture](architecture.md), and
> [the current task checklist](../todo.md); do not add a sex output field or
> execute the old fetch instructions on the assumption that they remain needed.

After completing the steps in `docs/handoff-fetch-and-ingest.md` on a
network-enabled machine, share the items below in a fresh Claude Code
session so it can resume implementation. The goal is to give Claude
enough information to act without asking back-and-forth.

## What to share

### 1. Did the fetch succeed end-to-end?

Reply yes / no, plus:

- Number of (UF, period, sex) rankings actually written
  (`find ptbr_sampler/data/raw/ibge_nomes_v2 -name '*.json' | wc -l`).
- Number of Parquet partitions produced
  (`find ptbr_sampler/data/parquet/first_names -name part.parquet | wc -l`).
- Whether the test suite still passes (`uv run --extra test pytest -q`
  exit code).
- Whether the partitions were committed to the branch (and which
  commit), or kept local-only.

A one-liner is enough — Claude just needs to know whether to assume the
data is available on the branch or not.

### 2. Sample of the ingested data

Paste the output of:

```bash
uv run python -c "
import pyarrow.parquet as pq
from pathlib import Path

p = Path('ptbr_sampler/data/parquet/first_names/uf=SP/period=ate2010/sex=F/part.parquet')
print('rows:', pq.read_table(p).num_rows)
print('top:', pq.read_table(p).to_pydict()['name'][:5])
"
```

Plus the same for one or two other UFs (e.g. `uf=BA`, `uf=RS`) so
Claude can sanity-check the shape across regions.

### 3. Anything unexpected

- IBGE API errors that didn't auto-retry away.
- Triples that came back with empty `res` (the script logs which ones).
- Surprises in the data shape (e.g. accents not preserved, empty
  ranking arrays).
- Network artefacts (e.g. a corporate proxy that altered the response).

If Task 3 (IBGE 2022 surnames) or Task 4 (Arpen 2024) was attempted,
share the file layout used so Claude can write a matching ingester.

## What Claude will do next, given the data

The follow-up implementation work falls into clear chunks. Pick whichever
matches your priority and tell Claude which to do; or paste the whole
list and let it propose an order.

### A. Promote `experimental_uf_sex_conditioning` from experimental → supported

Once the parquet partitions are real and committed, Claude can:

- Drop the `experimental_` prefix from the flag (with backwards-compat
  alias for one release).
- Move the README / docs treatment from "experimental, top-20 caveat"
  to "default available; pass `uf_sex_conditioning=True` to enable".
- Add a statistical-validation test (chi-square against the ingested
  counts per UF, like the existing `tests/test_distribution_validation.py`).
- Wire UF/sex conditioning into the *non-batch* sample paths
  (`only_document`, `only_surname`, `only_middle`, `return_only_name`)
  — the current commit only threads it through the batch path.

### B. Add a sex-aware output column

Today, `experimental_uf_sex_conditioning=True` draws sex internally
50/50 but doesn't surface it in the output dict. Claude can:

- Add a `sex` field to the parsed result.
- Make sex optionally caller-controlled instead of always 50/50
  (`sample(..., sex='F')` should pin every row to female draws).

### C. Ingest IBGE *Nomes no Brasil* 2022 surnames (if Task 3 was done)

Given the file layout the user produced, Claude will:

- Add `ingest_surnames_uf_period(...)` mirroring
  `ingest_first_names_uf_sex`.
- Wire the `surnames/uf=<UF>/period=<P>/` partitions into
  `BrazilianNameSampler._surnames_table(...)` with the same
  fall-back-on-miss semantics.
- Document the unblocked realism in the README "Known realism gaps"
  list.

### D. Ingest Arpen 2024 (if Task 4 was done)

- Add an `Arpen2024` benchmark loader.
- Add a `time_period=NEWBORN_2024` value backed by the Arpen ranking,
  separate from IBGE stock data.
- Add a comparison test that checks Arpen names appear in the new
  bucket but not in `UNTIL_2010`.

### E. Surface a `--validate` mode in `download_datasets.py`

- Cross-check the bundled Parquet against the ingested counts.
- Print first-name distribution chi-square per UF.
- Useful for catching ingest regressions.

### F. Add a CHANGELOG.md entry

Once the data lands, summarise in CHANGELOG.md:

- What dimensions of realism are now empirically supported.
- What the breaking changes are (none expected; the experimental flag
  was opt-in).
- The top-20 caveat and how to opt out (use the default path).

## Template message to paste into a new Claude Code session

```
We ran the fetches off-sandbox. Here's the state:

Branch: <data-branch> @ <commit-sha>
Raw JSON files written: <N>
Parquet partitions: <M>
Test suite: <pass/fail>
Committed to branch: <yes/no, commit-sha>

Sample (uf=SP/period=ate2010/sex=F): rows=<R>, top=[<n1>, <n2>, ...]
Sample (uf=BA/period=ate2010/sex=F): rows=<R>, top=[<n1>, <n2>, ...]

Unexpected: <none | bullets>

IBGE 2022 surnames (Task 3): <skipped | layout: ...>
Arpen 2024 (Task 4): <skipped | layout: ...>

Please proceed with handoff items A and B from
docs/handoff-resume-with-claude.md.
```

That's enough context for Claude to pick up, verify with a smoke test,
and start on the chosen follow-ups without asking back.

# Statistical audit tasks

This checklist splits the statistical audit into concrete tasks.

Rules followed in this document:

- Includes every actionable item supported by the audit and current repository docs.
- Excludes only items that depended on educated guesses or on unrecoverable internal distributions.
- Focuses on realism by default, while preserving an explicit escape hatch for users who want more random output.
- Adds dataset download + Parquet conversion as the first step.

---

## 1. Download the datasets and convert them to Parquet

- [ ] Add a reproducible "download datasets + build Parquet" workflow.
  - **What is wrong:** the repository documents data sources and mentions Parquet ingestion, but it does not yet present a single explicit first-step workflow that starts from downloading the datasets and ends with the Parquet layout used by the sampler.
  - **Solution:** document and script the full pipeline:
    1. download the raw datasets,
    2. store them in a reproducible raw-data location,
    3. validate presence and shape,
    4. convert them to the Parquet layout,
    5. make the sampler use Parquet by default.
  - **Dataset(s) to download:**
    - IBGE *Nomes no Brasil* / API-based first-name data
    - IBGE *Nomes no Brasil* 2022/2025 surname data where available
    - IBGE population estimates 2024
    - Arpen 2024 rankings as a benchmark, not as a replacement for stock-population data
    - the project's middle-name raw extraction source
    - city/CEP/DDD supporting inputs already referenced by the project
  - **Current repo hooks:** `python -m scripts.ingest_to_parquet`, `docs/data-origins.md`, `docs/architecture.md`
  - **Done when:** a contributor can start from zero and rebuild the packaged Parquet datasets end-to-end.

---

## 2. Keep realism as the default, but allow explicit random mode

- [ ] Make realistic conditional sampling the default, while allowing `random=True` for intentionally less realistic output.
  - **What is wrong:** the goal of the project is realism, but users may also want deliberately random data generation. The docs should make the default behavior explicit and the non-realistic mode opt-in.
  - **Solution:** keep the realistic path as default (`random=False`) and add or document an explicit `random=True` mode that relaxes realism-oriented conditioning.
  - **Clarification:** the realistic default should follow the existing intended logic: sample geography realistically first (for example via population-weighted location / CEP-related logic), then sample names according to the relevant period and available conditioning dimensions.
  - **Important constraint:** only condition on dimensions that truly exist in the dataset. Do not invent unavailable conditioning dimensions.
  - **Done when:** the default path is clearly documented as "realistic", and users can intentionally request random behavior.

- [ ] Make the hierarchical conditional sampler the documented default realism mode.
  - **What is wrong:** the audit originally framed this as "replace the independent national-pool sampler with a hierarchical conditional sampler", but your intended behavior is that realism-by-default already is, or used to be, the goal.
  - **Solution:** document the realistic default as:
    1. sample geography first,
    2. sample names conditioned on the dimensions that are actually available,
    3. allow a separate `random=True` path for users who prefer less realistic output.
  - **Important note:** this task should not claim conditioning dimensions that are not confirmed by the data.
  - **Done when:** docs and implementation agree that realism is the default and random generation is an explicit override.

---

## 3. Add state-conditioned first-name distributions only if the data really exists

- [WON'T PURSUE] **UF × sex × decade first-name partitions sourced from the
  IBGE Nomes API ranking endpoint.** The endpoint
  `https://servicodados.ibge.gov.br/api/v2/censos/nomes/ranking` is the only
  public source of (UF, sex, decade) first-name conditioning data — no other
  mirror exists.
  - **Empirical confirmation (2026-05-09):** the host
    `servicodados.ibge.gov.br` (170.84.40.205) drops every TCP SYN to :443
    from this network, from Anthropic's `WebFetch` egress, and via direct IP
    probe. Other IBGE hosts (`ftp.ibge.gov.br`) are reachable, so this is a
    server-side or upstream block specific to the API host, not a local
    firewall issue. The Wayback Machine has zero captures of the ranking
    endpoint. The 2010-Census microdata available on `ftp.ibge.gov.br` does
    not include the per-name aggregations the API exposes.
  - **No public mirror found.** Verified absence of pre-aggregated UF × sex ×
    decade rankings on:
    - `datasets-br/prenomes` (national, decade only — no UF, no sex)
    - `brasil.io/genero-nomes` (national name × sex — no UF, no decade)
    - `basedosdados / br_ibge_nomes_brasil` (municipality × name with one
      cumulative count — no decade, no sex)
    - `turicas/genero-nomes` (scraper with no committed data)
  - **Top-20 caveat (even if reachable):** the API only ever exposes the top
    20 names per (UF, sex, decade) condition, so even a successful fetch
    would produce a much narrower distribution than the period-only long
    tail (~thousands per period). The realistic alternative — period × sex
    national with full long tail — is now bundled (task 4 / `--sex-conditioning`).
  - **Code path retained:** `scripts.download_datasets --fetch-ibge-nomes`
    and the `experimental_uf_sex_conditioning` flag still exist as
    forward-compatible shims; if IBGE re-opens the host they continue to
    work without changes. We just don't depend on them.

- [x] State / sex realism via the alternative sources we *can* reach.
  - **What we ship:** sex-conditioned first-name sampling at full long-tail
    cardinality, derived from `names_data.json` percentages × the
    `brasil.io/genero-nomes` per-name sex prior (see task 4 for details).
  - **Coverage:** 91.9 % of (name, period) cells matched empirically;
    remaining 8.1 % filled in via Gemini gender classification (LLM-tagged,
    audit-traceable — see `docs/sources/gemini-gender-classifications.md`).
  - **What we don't ship:** UF-conditioned first names. Documented as
    blocked-on-data in `docs/data-origins.md`.

---

## 4. Include sex only if the dataset actually includes it

- [x] Sex-conditioned first-name sampling, sourced from a verified empirical
  dataset (no inferred / synthetic split).
  - **Implementation:** uses the `brasil.io/genero-nomes` dump
    (curated by Álvaro Justen / `@turicas`, built from the public IBGE Nomes
    per-name endpoint — same IBGE Nomes API our period data comes from). The
    ingester multiplies period percentages by `p_male(name)` / `p_female(name)`
    and writes `parquet/first_names/period=<P>/sex=<S>/` partitions at full
    long-tail cardinality (8k–24k rows per partition).
  - **Coverage:** 91.9 % of (name, period) cells in `names_data.json` are
    matched in genero-nomes; the remaining 8.1 % gracefully fall back to the
    period-only table (no synthetic sex assignment).
  - **Activation:** `sex_conditioning='M' | 'F' | 'mixed'` (Python) or
    `--sex-conditioning {M,F,mixed}` (CLI). Default off.
  - **Provenance:** every ingested partition ships a `data_origin.json`
    sidecar capturing source URL, fetch timestamp, row count, and derivation
    formula. See `docs/sources/genero-nomes.md` and `docs/data-origins.md` §1.

---

## 5. Extend the time horizon beyond `UNTIL_2010`

- [ ] Update the time benchmark beyond `UNTIL_2010`.
  - **What is wrong:** a realism-oriented default capped at `UNTIL_2010` is stale for recent cohorts.
  - **Solution:** extend support to newer periods when the dataset supports it, and document the difference between:
    - whole-population realism (IBGE stock-like data),
    - newborn or recent-cohort realism (Arpen flow data).
  - **Dataset(s) to download:** IBGE 2022/2025 data where available, plus Arpen 2024 for benchmark/validation.
  - **Done when:** recent cohorts are not silently forced into pre-2010 assumptions.

---

## 6. Replace pooled national surname sampling when better distribution data is actually available

- [ ] Move away from a single pooled national surname law when geography-conditioned surname data is available.
  - **What is wrong:** a single national surname pool misses strong regional concentration effects.
  - **Solution:** if UF- and/or period-conditioned surname data can be downloaded and validated, use that as the realism path.
  - **Dataset(s) to download:** IBGE *Nomes no Brasil* 2022/2025 surname data.
  - **Done when:** surname realism is tied to the best available observed distribution rather than a single pooled approximation.

---

## 7. Keep `top_40` as a parameter for now, but document the limitation clearly

- [ ] Keep `top_40` as an available parameter and explain why it exists.
  - **What is wrong:** `top_40` is not realism-preserving if fuller surname-distribution data exists, but it may reflect the best distribution information that was actually available at the time.
  - **Solution:** document this explicitly:
    - `top_40` remains available as a parameter,
    - explain that at some point the available information may only have supported a top-40-style list,
    - after confirming whether fuller surname-distribution data now exists and is ingestible, reevaluate whether `top_40` should remain, be demoted, or be dropped.
  - **Important note:** do not remove it prematurely.
  - **Done when:** users understand whether `top_40` is a historical-data limitation, a convenience mode, or both.

- [ ] Confirm whether surname-distribution data beyond the top 40 is available and reliable enough to replace `top_40`-style assumptions.
  - **What is wrong:** the project should not keep a weaker mode out of inertia if better data is now available.
  - **Solution:** explicitly verify current surname data coverage before deciding whether `top_40` should continue to exist.
  - **Done when:** the project has a documented reason either to keep or to retire `top_40`.

---

## 8. Do not keep the "one-surname simplification mode" task, but add a realism note about two surnames

- [ ] Add documentation that people are more likely than not to have at least two surnames.
  - **What is wrong:** the previous task framed `one-surname` as a simplification mode; you asked to remove that framing, but the realism note is still important.
  - **Solution:** add an explicit note in docs and task tracking that realistic generation should assume that having at least two surnames is more likely than not.
  - **Done when:** the repo communicates the realism expectation clearly, even if the parameter itself remains for compatibility or convenience.

---

## 9. Rebuild or rigorously clean `middle_names.json`

- [ ] Rebuild or rigorously clean `middle_names.json`.
  - **What is wrong:** the raw middle-name dataset mixes true second given names with surnames and obvious noise.
  - **Solution:** create or document a reproducible cleaning pipeline that:
    - removes non-name artifacts,
    - blocks surname leakage,
    - normalizes variants,
    - regenerates the cleaned distribution.
  - **Dataset(s) to download:** the original raw middle-name extraction source used by the project.
  - **Done when:** the middle-name distribution is auditable and reproducible.

- [ ] Document provenance for `middle_names.json`.
  - **What is wrong:** the source and transformation steps are not documented strongly enough for a realism-critical dataset.
  - **Solution:** add provenance, extraction method, filtering rules, and rebuild steps.
  - **Done when:** the file is no longer a black box.

---

## 10. Revisit `percentage_with_second = 30.99%`

- [ ] Revisit the `percentage_with_second = 30.99%` default.
  - **What is wrong:** the current rate may be useful, but if its provenance cannot be clearly indicated, it should not be presented as a strongly grounded statistical fact.
  - **Solution:** revisit the value and do one of the following:
    - document a clear provenance and keep it,
    - replace it with a better-supported estimate,
    - or explicitly label it as an educated guess if provenance cannot be established.
  - **Done when:** the default is either supported or honestly labeled as an estimate.

---

## 11. Add a clear download-and-rebuild section to the docs

- [ ] Add a documentation section listing every dataset, where to download it, and what it powers.
  - **What is wrong:** data origins are documented, but there is no single concise operational checklist tying source URLs to repo artifacts and rebuild steps.
  - **Solution:** add a section that lists, for each dataset:
    - source URL,
    - what it powers in the repo,
    - raw file location,
    - ingestion script,
    - Parquet output path,
    - validation notes.
  - **Done when:** a maintainer can rebuild data assets without reverse-engineering the docs.

---

## 12. Add a concise "known realism gaps" checklist to the main documentation

- [ ] Add a "known realism gaps" checklist to the README.
  - **What is wrong:** the audit findings are rich, but users need a concise summary in the main entry point of the project.
  - **Solution:** summarize the supported actionable gaps, especially:
    - data that still needs downloading / rebuilding,
    - missing confirmed state-conditioned first-name data,
    - incomplete surname conditioning,
    - middle-name provenance/cleaning limitations,
    - uncertainty around `percentage_with_second`,
    - realism-vs-random mode behavior.
  - **Done when:** the main docs set correct expectations.

---

## Items intentionally excluded

The following were intentionally not turned into hard tasks because they depended on educated guesses or unrecoverable internal distributions:

- exact row-by-row fixes for `names_data.json` without the recoverable underlying distribution
- exact row-by-row fixes for `surnames_data.json` without the recoverable underlying distribution
- any conditioning dimension that cannot be confirmed to exist in the downloadable data
- any undocumented claim that would overstate what the current data can support

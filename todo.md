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

- [ ] Verify whether state-conditioned first-name data really exists before promising it.
  - **What is wrong:** this was not reliably available before, so the project should not assume UF-conditioned first-name distributions without confirming the dataset exists and is usable.
  - **Solution:** add a verification task before implementation:
    - confirm whether first-name data by state/UF is actually available in a form the repo can ingest,
    - confirm its coverage and stability,
    - only then add it to the sampler.
  - **Dataset(s) to download/check:** IBGE *Nomes no Brasil* releases and/or API endpoints that expose locality-conditioned first-name rankings.
  - **Done when:** the repository either:
    - implements UF-conditioned first-name sampling from a verified dataset, or
    - explicitly documents that this conditioning is unavailable and therefore not used.

- [ ] Add state-conditioned first-name sampling only after the dataset is confirmed to exist.
  - **What is wrong:** realism is reduced if geography-conditioned first names are possible but not used; however, pretending the data exists would be worse.
  - **Solution:** make this conditional:
    - if verified UF-conditioned first-name data exists, ingest it and partition it;
    - if it does not, document that this realism improvement remains blocked by data availability.
  - **Done when:** the project does not overclaim data support.

---

## 4. Include sex only if the dataset actually includes it

- [ ] Only add sex-conditioned sampling if the underlying dataset includes sex.
  - **What is wrong:** the earlier version of the task list assumed sex-conditioned first-name sampling, but that should only be included if the actual dataset used by the repository provides it.
  - **Solution:** treat sex as an optional conditioning dimension:
    - if the downloaded dataset includes sex, support sex-aware partitions and sampling;
    - if it does not, do not include sex in the conditioning model.
  - **Constraint:** no inferred or synthetic sex split should be introduced.
  - **Done when:** the sampler only uses empirically available dimensions.

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

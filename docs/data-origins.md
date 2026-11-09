# Data origins

This is the current provenance reference for ptbr-sampler 0.3.0. The generated
`ptbr_sampler/data/manifest.json` and each `data_origin.json` sidecar are the
machine-readable baseline. `ptbr sources` summarizes the same runtime catalogue.
Code and dataset terms are separated in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Source inventory and exact counts

| Input | Reference and acquisition | Current use | Verified inventory |
|---|---|---|---|
| IBGE *Nomes no Brasil*, 2022 Census, released 2025 | Pinned `alexsantee/nomes_do_brasil_2022` mirror at `db1f66f397d00d4a6653204f8669c9e8c3adb256`; acquired 2026-11-09 | First names, surnames, national historical stocks, national empirical sex counts | 128,458 national first-name rows; 201,601 national surname rows; 379,611 first-name and 459,233 surname rows across 27 UFs |
| IBGE population estimates 2026 | `POP2026_20261029.xlsx`, TCU-corrected 2026-10-29; DOU workbook retained for comparison | UF selection, city weights, national marginals, per-UF alpha | 5,571 source municipalities, 27 UFs, population 214,211,951 |
| Arpen-Brasil Transparency 2025 | Primary record API, acquired 2026-11-09 | Newborn model | 2,537,697 registered births; national and 27 UF SIMPLE/COMPOUND/ALL rankings, up to 50 rows each; 84 rankings in 85 cached responses including births |
| Legacy 2010 names, Brasil.IO, Gemini | Older project files | Compatibility and historical provenance only for current cohort construction | Do not replace current IBGE 2022 national sex evidence |
| Legacy city/CEP/DDD metadata | Existing city base, Correios/Anatel references | CEP, DDD, coordinates and related runtime metadata | 5,570 CEP-covered cities |

The IBGE mirror archive is 33,835,666 bytes with SHA-256
`c9d139e3281db5405590b668885bfd7d453a9e4c6e7d86d208e7b82c56c84bca`.
Its extracted SQLite is 97,566,720 bytes with SHA-256
`5c00b169e39affcdac15508ee32ea201501221152471b62947a88275bf439c48`.
These checksums validate bytes; neither the mirror's code license nor a checksum
grants rights to the underlying IBGE dataset.

## First names and surnames

`parquet/ibge2022/first_names/` and `parquet/ibge2022/surnames/` hold direct
national and all-27-UF 2022 frequencies. Weights are `count / sum(count)` within
the selected partition. No UF-period or UF-sex observation is inferred.

The national first-name frequency sum is 190,383,184 and the national surname
frequency sum is 333,496,261. They are not interchangeable with Census resident
population totals: source availability/suppression affects first names, and a
person can contribute multiple surname occurrences. Missing and suppressed rows
are not treated as zero-observation proof or repaired with invented counts.

IBGE's official release reports more than 200,000 surnames, which agrees with
the 201,601-row mirror inventory. High-level sampling uses national or sampled/
fixed-UF surnames from these tables. Surname distributions do not change with
the first-name cohort or historical period.

### Suppression and sex

The IBGE 2022 mirror contains **123,733 national names** with empirical male/
female counts and **4,725 null-sex names**. Null-sex rows remain in
unconditioned distributions; they are omitted only when M/F conditioning is
selected. Known zero-probability labels can remain in derived support with zero
weight. Conditioning computes `selected_weight * national_sex_prior` and then
renormalizes. It is not UF-sex empirical evidence.

`mixed` chooses M/F with probability 1/2 per row. That is a sampling choice,
not a measured Brazilian sex ratio.

## Historical periods

National stocks are retained for 1930, 1940, …, 2020. Decade bins are endpoint
differences:

```text
stock1930
stock1940 - stock1930
…
stock2020 - stock2010
after2010 = stock2020 - stock2010
until2020 = stock2020
```

`after2010` therefore covers 2011–2020, not 2021–2022 or later. The historical
stock tables have 61,469 labels. They are national derived stock bins, not
independent decade-by-sex or UF-period observations. M/F historical tables use
the same national empirical sex prior described above.

`TimePeriod.UNTIL_2020` uses selector `ate2020`; `TimePeriod.AFTER_2010` uses
`after2010`. The older `ate1930` through `ate2010` selectors remain. An explicit
period is compatible only with the default `current` selector and bypasses the
2025 blend; `census2022` or `newborn2025` plus a period is rejected.

## Arpen newborn model and current blend

Only Arpen **SIMPLE** atomic first-name rows are observed input. COMPOUND and ALL
remain inspectable artifacts but never determine first-name probabilities or
second-name incidence.

For each UF:

```text
p_observed[i,u] = Arpen_SIMPLE_count[i,u] / registrations_2025_u
residual_u = 1 - sum_top50(p_observed[i,u])
p_newborn_tail[i,u] = residual_u * IBGE_national_after2010[i]
                      / sum(IBGE_national_after2010 excluding UF top50 labels)
alpha_u = registrations_2025_u / official_POP2026_population_u
p_current[i,u] = (1-alpha_u)*p_census2022[i,u] + alpha_u*p_newborn2025[i,u]
```

The top 50 is incomplete; residual mass is modeled rather than observed by
name. Top-50 labels absent from the national tail retain their observed mass.
The tail is **national 2011–2020 evidence**, not UF-observed post-2010 history.
Each cohort sidecar records registrations, official UF denominator, alpha,
residual, tail coverage, and formulas.

National marginals combine all 27 UF distributions using official POP2026 UF
populations, not Arpen registrations or artifact row counts. `current` is a
recency-adjusted synthetic distribution and must not be described as an official
future population-name estimate.

## Second given names

`middle_names.json` is a legacy authorial civil-registry extract, not an IBGE
dissemination of second names. Its ratio remains:

```text
1,640,514 / 5,293,204 = 30.992835…%
```

This is **legacy, corpus-specific, and not validated as a national population
statistic**. Truncated Arpen rankings provide no basis for a replacement. The
rate remains 30.99% in both default and `random=True` modes.

The legacy file reports 1,187 second-name tokens; filtering leaves **885** in
`parquet/middle_names/part.parquet`. The vocabulary filter in
`ptbr_sampler/sampling/vocabulary.py` removes surname leakage, `Cancelado`, bare
hyphens, and tokens absent from the first-name whitelist. Cleaning improves the
vocabulary but does not establish representative incidence. Prefix choices such
as `da`, `de`, and `dos` are separate authorial style heuristics.

## Geography and the CEP coverage gap

POP2026 is joined to legacy CEP metadata only by exact seven-digit IBGE
municipality codes, never fuzzy names. The DOU 2026 comparison has zero national
population delta and 5,571 unchanged source rows.

| Measure | Value |
|---|---:|
| Official source municipalities | 5,571 |
| Runtime CEP-covered municipalities | 5,570 |
| Official national population / UF blend denominator | 214,211,951 |
| Population represented by runtime CEP city rows | 214,205,968 |
| Source-only population | 5,983 |

Boa Esperança do Norte, Mato Grosso (`5101837`), was added to the official source
but has no legacy CEP-base row. It remains in official table totals and UF alpha
denominators but cannot be drawn as a runtime city. Therefore "5,570 cities"
does **not** mean every current IBGE municipality is selectable. Runtime
percentages use population reconciled to the CEP base; official UF totals remain
214,211,951 in aggregate. `ptbr_sampler/data/cities_with_ceps.data_origin.json`
records the MT reconciliation (`delta=-5,983` for CEP-covered joins).

CEP ranges and DDD values are metadata, not proof of an actual residence.
Offline addresses are synthetic. Online ViaCEP calls are optional, can fail,
and are not required to use bundled data.

## Documents, addresses, and phone numbers

CPF, CNPJ, PIS, CEI, and RG check digits follow public formatting/validation
rules; generated values are synthetic and are not evidence of a registered
identity. DDD comes from the sampled city where available; subscriber numbers
are synthetic. Offline street and neighborhood strings come from the project's
Faker-style corpus and editorial curation. Authorial formatting choices should
not be cited as official demographic measurements.

## Rebuild the artifacts

Install the project in a maintainer checkout with Python 3.12+, then run:

```bash
uv sync --extra test
uv run ptbr-data status
uv run ptbr-data fetch
uv run ptbr-data validate
uv run ptbr-data build
uv run ptbr-data validate
uv run pytest -q
```

- `status` reports raw, sanitized, and derived artifacts without fetching.
- `fetch` downloads `ibge2022`, `pop2026`, `estimativa_dou_2026`, and
  `arpen2025`, resumes verified cache entries, and verifies pinned IBGE bytes.
  Use `--source <key>` to fetch selected raw sources or `--refresh` to replace
  verified cache inputs. Downloads use a 90-second per-request timeout; this is
  not a promise that an entire build finishes in 90 seconds.
- `fetch --official` additionally probes the official IBGE v3 ranking endpoint.
  It exits explicitly on an unreachable or invalid response. The documentation
  reconciliation did **not** claim a new successful live official-v3 run.
- `build` creates staged deterministic Parquet/JSON artifacts, sidecars, and the
  manifest. It can contact Arpen if its cached response is absent.
- `validate` verifies hashes, artifact inventory, Parquet totals/weights,
  geography reconciliation, and births.

The default cache is `${XDG_CACHE_HOME:-~/.cache}/ptbr-sampler`; override paths
with `--cache-dir`. The package needs only its compact runtime artifacts. The
97 MB SQLite file stays in cache, is not a runtime dependency, and is not packed
into the wheel or sdist. Do not copy repository-local cache files into a release.

The mirror build is the verified reproducibility path for the recorded 2026-11-09
acquisition. Official v3 and every network fetch can be unavailable because of
timeouts, egress restrictions, service changes, or rate limits. A failed live
probe does not invalidate existing hash-checked artifacts, but it must be
reported rather than described as a successful official refresh.

## Source links

- IBGE application: <https://www.ibge.gov.br/apps/nomes/>
- Pinned mirror: <https://github.com/alexsantee/nomes_do_brasil_2022>
- Official IBGE v3 base: `https://servicodados.ibge.gov.br/api/v3/nomes/2022`
- POP2026: <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/POP2026_20261029.xlsx>
- DOU comparison: <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/estimativa_dou_2026.xlsx>
- Arpen API: <https://transparencia.registrocivil.org.br/api/record>
- Arpen portal: <https://transparencia.registrocivil.org.br/>
- ViaCEP: <https://viacep.com.br/>

See [sources/bibliography.md](sources/bibliography.md) for release references and
historical context. Older handoffs and the deep-research report are dated
snapshots, not the current inventory.

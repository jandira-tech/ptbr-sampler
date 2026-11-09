# IBGE — Nomes no Brasil, 2022 Census (November 2025)

**Publisher:** Instituto Brasileiro de Geografia e Estatística (IBGE).
**Census reference:** 2022.
**Release:** 4 November 2025.
**Current use:** primary name, surname, historical-stock, and national sex-count
source for ptbr-sampler 0.3.0, acquired through a pinned mirror.

## Current runtime evidence

The build validates and reads the mirror at commit
`db1f66f397d00d4a6653204f8669c9e8c3adb256`. It writes direct national and
27-UF tables under `ptbr_sampler/data/parquet/ibge2022/`:

| Data | Rows / counts |
|---|---:|
| National first names | 128,458 |
| First-name rows aggregated across 27 UFs | 379,611 |
| National surnames | 201,601 |
| Surname rows aggregated across 27 UFs | 459,233 |
| National names with empirical M/F counts | 123,733 |
| National null-sex names | 4,725 |
| Historical-stock labels | 61,469 |

National frequency sums are 190,383,184 for first names and 333,496,261 for
surnames. These are sums of available name records, not alternative population
estimates. Multiple surname occurrences make the surname sum incomparable to a
resident count, and upstream suppression affects available rows.

The national observed anchors checked by the build include Maria 12,284,478,
Silva 34,030,104, and Santos 21,367,475. Official and reported UF anchors are
listed in `ptbr_sampler/data/manifest.json` with URLs. No UF-period or UF-sex
rows are manufactured from these national/UF tables.

## How the sampler uses the data

- First names and surnames use the sampled/fixed UF by default; direct calls
  without a UF can use official-population-weighted national cohort marginals.
- Surnames remain pure Census 2022, independent of the first-name cohort.
- Historical periods are derived from national stocks: 1930 stock, successive
  stock differences through 2020, `after2010 = stock2020 - stock2010`, and
  `until2020 = stock2020`. `after2010` means 2011–2020.
- Sex conditioning multiplies a selected distribution by the national
  empirical prior and renormalizes. It is not a UF-sex observation. Null-sex
  labels remain unconditioned but are omitted from M/F tables.

IBGE's dissemination variable for given names is the **first recorded name**.
It does not validate second-name incidence. Surname counts cover recorded
surname occurrences independent of position; presence percentages should not be
interpreted as "last-position surname" distributions.

## Suppression and limits

The official publication suppresses small cells according to locality and
release rules. The mirror inventory is therefore not asserted to contain every
name occurrence or every theoretically possible name. This project adds no
small-cell suppression, but also does not reconstruct withheld counts. Null sex
is retained in source-derived unconditioned tables and excluded only from M/F
conditionals.

The release's headline examples remain useful external comparisons: Silva is
reported for 16.76% of the national population, Santos 43.38% in Sergipe, and
Silva 35.75% in Alagoas and 34.23% in Pernambuco. Current code addresses the old
single-national-pool gap by shipping UF surname tables; those percentages are
not a claim that all IBGE municipality/period slices are packaged.

## Access and provenance

- Application: <https://www.ibge.gov.br/apps/nomes/>
- Census application: <https://censo2022.ibge.gov.br/nomes/>
- Release (PT): <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/44929-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil>
- Release (EN): <https://agenciadenoticias.ibge.gov.br/en/agencia-news/2184-news-agency/news/44956-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil-2>
- Official v3 base: `https://servicodados.ibge.gov.br/api/v3/nomes/2022`
- Pinned mirror: <https://github.com/alexsantee/nomes_do_brasil_2022>

An official-v3 live refresh was not established during documentation
reconciliation. The pinned mirror is the recorded verified acquisition path.
Its MIT statement covers mirror code, not an override of IBGE dataset terms;
see [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

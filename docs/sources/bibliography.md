# Bibliography — ptbr-sampler data sources

This page distinguishes current 0.3.0 sources from historical provenance. Exact
checksums, counts, formulas, and package paths are in
[docs/data-origins.md](../data-origins.md); attribution and dataset-term limits
are in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).

## Current build inputs

### IBGE — 2022 Census names, released November 2025

The current distributions use national and all-UF first-name and surname counts,
historical national stock rows, and national empirical male/female counts.
Sampling reads a checksum-verified mirror snapshot; optional official IBGE v3
probing is a separate reproducibility path, not a claimed successful refresh.

- Interactive application: <https://www.ibge.gov.br/apps/nomes/>
- Census application: <https://censo2022.ibge.gov.br/nomes/>
- Release (PT): <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/44929-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil>
- Release (EN): <https://agenciadenoticias.ibge.gov.br/en/agencia-news/2184-news-agency/news/44956-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil-2>
- Official v3 API base: `https://servicodados.ibge.gov.br/api/v3/nomes/2022`
- Pinned input mirror: <https://github.com/alexsantee/nomes_do_brasil_2022>
- Mirror commit: `db1f66f397d00d4a6653204f8669c9e8c3adb256`

Published anchors include Maria 12,284,478, Silva 34,030,104, and Santos
21,367,475 nationally. The checked UF evidence is recorded in the generated
manifest. The package itself contains 128,458 national first-name rows and
201,601 national surname rows. Source suppression remains visible in sidecars;
counts are not presented as unsuppressed complete-person records.

See [IBGE Nomes no Brasil 2022](ibge-nomes-no-brasil-2022.md).

### IBGE — Population estimates 2026

The TCU-corrected `POP2026_20261029.xlsx` workbook is the population source.
The official total is 214,211,951 across 5,571 source municipalities. The
runtime CEP base covers 5,570 and 214,205,968 people; see the documented Boa
Esperança do Norte exception in [data origins](../data-origins.md#geography-and-the-cep-coverage-gap).

- POP2026 workbook: <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/POP2026_20261029.xlsx>
- DOU comparison workbook: <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/estimativa_dou_2026.xlsx>
- Estimates landing page: <https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html>

### Arpen-Brasil — 2025 aggregate civil registrations

The Associação Nacional dos Registradores de Pessoas Naturais supplies the 2025
national and UF SIMPLE/COMPOUND/ALL top-50 rankings plus 2,537,697 registered
births. Only atomic SIMPLE rows enter `newborn2025`; the remaining probability
mass is modeled from the national IBGE 2011–2020 tail.

- Transparency portal: <https://transparencia.registrocivil.org.br/>
- Record API: <https://transparencia.registrocivil.org.br/api/record>

These are civil-registration flows and incomplete rankings, not Census stocks,
full name distributions, or evidence for second-name incidence.

### Location metadata and online lookup

- Correios CEP search: <https://buscacepinter.correios.com.br/>
- ViaCEP optional runtime enrichment: <https://viacep.com.br/>
- Anatel area-code reference: <https://www.anatel.gov.br/consumidor/tudo-sobre-telefonia-fixa/codigos-de-area>

CEP/DDD metadata describes the legacy runtime base; it does not upgrade its
5,570-city coverage to the complete 5,571-row POP2026 municipality inventory.

## Legacy source pages

The following dated pages preserve older research. They do not describe active
0.3.0 inputs unless explicitly cross-linked by data origins:

- [IBGE 2024 population estimates](ibge-estimativas-populacao-2024.md) —
  superseded by POP2026 for runtime geography.
- [Arpen 2024 rankings](arpen-2024-rankings.md) — superseded by Arpen 2025 for
  the newborn model; useful only as historical context.
- [Brasil.IO `genero-nomes`](genero-nomes.md) — legacy national sex-prior
  provenance, not the current cohort source.
- [Gemini classifications](gemini-gender-classifications.md) — historical
  model-generated gap-fill, not empirical evidence and not a current fallback.
- [Archived pre-0.3.0 research report](<../../deep-research-report(4).md>) — the
  audit that motivated modernization, not a description of current code.

## Methodology tools

IPEA `censobr` and `geobr` are investigation tools, not inputs to the committed
distributions:

- `censobr`: <https://ipeagit.github.io/censobr/>
- `geobr`: <https://ipeagit.github.io/geobr/>

Do not imply that these packages were used in the build merely because they are
listed as useful external validation tools.

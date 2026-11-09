# Archived IBGE population estimates — 1 July 2024

> **Historical source page; superseded in 0.3.0 by POP2026.** Current UF and
> municipal weights use `POP2026_20261029.xlsx`, with national population
> 214,211,951 and 5,571 source municipalities. The CEP runtime base covers 5,570
> and 214,205,968 people. Values and normalization claims below describe the old
> JSON generation, not current artifacts. See [current geography provenance](../data-origins.md#geography-and-the-cep-coverage-gap).

**Publisher:** Instituto Brasileiro de Geografia e Estatística (IBGE).
**Reference date:** 1 July 2024.
**Relevance for ptbr-sampler:** official population weights underlying
`ptbr_sampler/data/locations_data.json` and the `states` / `cities` partitions of the
Parquet layout.

## Headline

Estimated resident population of Brazil: **212.6 million** inhabitants on
1 July 2024. The estimates are calibrated against the 2022 Census counts and
propagate upward so municipal totals reproduce the federative totals.

## Share by Federation Unit (IBGE release)

| State | Population 2024 | Share |
|---|---:|---:|
| São Paulo | 45,973,194 | 21.6% |
| Minas Gerais | 21,322,691 | 10.0% |
| Rio de Janeiro | 17,219,679 | 8.1% |
| Bahia | 14,090,256 | 6.6% |
| Rio Grande do Sul | 10,850,000 | 5.1% |
| Paraná | 11,444,380 | 5.4% |
| Pernambuco | 9,207,024 | 4.3% |
| Ceará | 8,791,688 | 4.1% |
| Rondônia | 1,746,227 | 0.8% |
| Tocantins | 1,577,342 | 0.7% |
| Acre | 880,631 | 0.4% |
| Amapá | 802,837 | 0.4% |
| Roraima | 716,793 | 0.3% |

The full 27-UF table (including all remaining states) is distributed by IBGE
in the `estimativa_dou_2024.pdf` release and in the SIDRA tables linked
below.

## Access paths

- News release (PT):
  <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/41111-populacao-estimada-do-pais-chega-a-212-6-milhoes-de-habitantes-em-2024>
- DOU PDF (per-municipality totals):
  <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf>
- Landing page:
  <https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html>
- SIDRA browser (machine-readable):
  <https://sidra.ibge.gov.br/pesquisa/EstimaPop>

## Notes on the `locations_data.json` mapping

The committed `locations_data.json` encodes `population_percentage` as a
fraction of total Brazilian population. The values are consistent with the
table above — e.g. São Paulo lands in the 0.21 range, Acre ≈ 0.0019. When
the Parquet ingestion script runs, it re-derives these shares from the
authoritative totals to guard against drift in the normalisation.

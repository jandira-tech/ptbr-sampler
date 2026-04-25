# IBGE — Nomes no Brasil, 2022 Census release (November 2025)

**Publisher:** Instituto Brasileiro de Geografia e Estatística (IBGE).
**Release date:** 4 November 2025.
**Data reference date:** 1 August 2022 (2022 Census household register).
**Relevance for ptbr-sampler:** primary external benchmark for the
`first_names` and `surnames` tables and the source motivating the
`state × period × sex` conditioning now supported by the sampler.

## Scope of the release

The 2025 edition is the first to publish **surnames** alongside given names,
and the first to expose both with a joint `sex × period-of-birth × locality`
slicing. Rankings can be generated at the Brazil, Federation Unit, or
municipality level. Below the ranking cut (counts under 20 at Brazil level),
individual entries are suppressed for statistical confidentiality.

## Key statistics (national)

| Metric | Value |
|---|---:|
| Distinct surnames surveyed | > 200,000 |
| `Silva` — national presence | 16.76% |
| `Santos` — national presence | ≈ 11% (second most frequent) |
| Most frequent given name (full population) | `Maria` |
| Most frequent male given name | `José` |

## Regional surname concentration

IBGE's release highlights that the 2022 benchmark is **not well approximated
by a single national distribution**:

| Scope | Surname | Share |
|---|---|---:|
| Brazil | Silva | 16.76% |
| Sergipe | Santos | 43.38% |
| Alagoas | Silva | 35.75% |
| Pernambuco | Silva | 34.23% |

Any sampler that draws surnames from one pooled law will materially
understate these regional concentrations. This is the single largest
realism gap flagged by `deep-research-report(4).md` and the motivation for
the `surnames/uf=<UF>/period=<period>` partition layout under
`ptbr_sampler/data/parquet/`.

## Period-of-birth dimension

Both given names and surnames are sliced by birth period. The exact
break-points mirror IBGE's 2010 release ("up to 1929" plus decades from 1930
onward), now extended with a `pos_2010` bucket for the post-2010 cohort
captured by the 2022 Census. In the Parquet layout, `period` is a string
partition key matching one of:

```
ate1930, ate1940, ate1950, ate1960, ate1970,
ate1980, ate1990, ate2000, ate2010, pos2010
```

## Sex dimension

IBGE 2022 exposes `M` / `F` explicitly. The current repository first-name
table does not have a sex column; the deep-research audit flags this as a
realism gap. When the sampler ingests 2022 Census data, the Parquet layout
`first_names/uf=<UF>/decade=<decade>/sex=<M|F>/` makes the conditioning
explicit and the ingestion script enforces it.

## Access paths

- Announcement (PT): <https://www.ibge.gov.br/novo-portal-destaques/44658-no-dia-4-11-2025-o-ibge-lanca-o-censo-demografico-2022-nomes-no-brasil-2.html>
- Announcement (EN): <https://www.ibge.gov.br/en/highlights/44662-on-november-4-2025-ibge-will-release-2022-population-census-names-in-brazil.html>
- News release (PT): <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/44929-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil>
- News release (EN): <https://agenciadenoticias.ibge.gov.br/en/agencia-news/2184-news-agency/news/44956-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil-2>
- Interactive app: <https://www.ibge.gov.br/apps/nomes/>
- Legacy machine-readable API (2010 Census): <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2>
- Bulk microdata via the Ipeabase `censobr` package: <https://ipeagit.github.io/censobr/>

## Methodological notes

1. The dissemination variable for given names is **only the first recorded
   name** (`apenas o primeiro nome informado`). That means this release does
   not directly validate the repository's `middle_names.json` file, which
   mixes second given names with surnames and administrative noise.
2. The surname field is a count over **all surnames recorded** for each
   resident, independent of order, so a national `Silva` percentage of
   16.76% is a population-presence figure, not a last-position figure.
3. Cells below the confidentiality threshold (20 at Brazil level, higher at
   UF and municipality level) are suppressed.

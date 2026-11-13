# Sampling Brazil at census scale: what IBGE Census 2022 publishes — and what it censors

*Part 1 of the `ptbr-sampler` `0.3.0` series (English).*

On 4 November 2025, IBGE released the second edition of *Nomes no Brasil*, derived from the
1 August 2022 Demographic Census household register: $N_{\text{pop}} = 203{,}080{,}756$
residents, `128,458` distinct given names and `201,601` distinct surnames, each with male and
female counts, nationally, by sex, by birth cohort, and across all 27 Federation Units (UFs).
`ptbr-sampler` `0.3.0` makes this census the **default** vintage
(`sample(q=..., census_year=2022)` is the default; `TimePeriod.ALL`).

```python
import random
from ptbr_sampler import sample

# Full coherent profile (name, UF, city, CEP, phone, CPF, RG, PIS, CNPJ, CEI)
profile = sample(q=1, all_data=True, uf_conditioning=True, rng=random.Random(2026))
```

But a census release is not a raw microdata dump. It is a **censor-aware aggregate**: small
cells are suppressed to protect respondents. Treating the published tables as if they were
complete would silently bias any sampler. This post explains the censoring model and how
`ptbr-sampler` honors it.

## The `Liv102228` suppression thresholds

IBGE Technical Note [`Liv102228`](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf)
defines **decreasing** confidentiality thresholds as the geographic grain gets finer:

| Scope | Suppress cells with count below |
| --- | ---: |
| National, and national by decade | `< 20` |
| Per Federation Unit (UF) | `< 15` |
| Per municipality | `< 10` |

A name whose national count is, say, 18 has its sex cells set to `NULL` *nationally* — even
though 18 is above the municipality threshold. The suppression is per-scope, and the scopes
nest: a cell suppressed at the national level is also suppressed in every finer breakdown that
contains it.

## The four sex-cell regimes, exactly

For each given name $i$ with national frequency $N_i$, the 2022 release reports male count
$N_{i,M}$ and female count $N_{i,F}$, each possibly `NULL`. `ptbr-sampler` classifies every
name into exactly one of four disjoint regimes:

1. **`both_observed`** — $N_{i,M} \ge 20$ and $N_{i,F} \ge 20$: $p_{i,M} = N_{i,M}/N_i$ is a
   directly observed empirical probability.
2. **`one_null_exact_zero`** (`55,210` names) — one sex cell is `NULL` but
   $N_{i,\text{obs}} = N_i$, so the missing cell is *deduced* to be exactly zero
   ($p = 0$), not merely small.
3. **`one_null_suppressed_positive`** (`57,941` names, `232,758` residual occurrences =
   `0.1223%` of national mass) — $N_{i,\text{obs}} < N_i$ and the residual
   $R_i = N_i - N_{i,\text{obs}} \in \{1, \dots, 19\}$ is strictly positive but censored.
   Arithmetic reveals $R_i$ exists, but IBGE withheld its sex split; `ptbr-sampler` records
   $p_{i,\text{obs}} = N_{i,\text{obs}}/N_i$ accurately and stores `NaN` for the suppressed
   cell — it **never imputes** the withheld split.
4. **`both_null_suppressed`** (`4,725` names, `108,522` occurrences = `0.057%`,
   $20 \le N_i \le 38$) — both sex cells suppressed.

Conservation check: **99.8207%** of published national given-name mass
($190{,}041{,}904 / 190{,}383{,}184$ occurrences) has directly observed empirical sex
counts, and **0.0%** is LLM-imputed in the 2022 pipeline. The suppressed residue is
**0.1793%** (`341,280` occurrences). Five distinct coverage metrics are reported instead of a
single ambiguous "coverage %": `96.32%` vocabulary lookup coverage
(`123,733 / 128,458` name types have at least one observed sex count), `99.8207%` observed
mass, `55,210` deduced exact zeros, `0.0%` LLM mass, `0.1793%` suppressed mass.

## `strict` vs `estimated` conditioning

Census 2022 publishes 1D and 2D marginals, not full multi-way cubes. So:

- **`conditioning_mode='strict'` (default):** sex-conditioned draws use only
  `first_names/sex=M` and `first_names/sex=F` partitions built from observed counts;
  suppressed names are excluded from sex-conditioned marginals but remain in unconditioned
  sampling. UF-conditioned draws use `first_names/uf=<UF>/`.
- **`conditioning_mode='estimated'` (explicit opt-in):** for unobserved joints such as
  `UF × sex` or `cohort × sex`, a lazy in-memory Bayes reweighting composes the observed
  marginals, $P(\text{name} \mid u, s) \propto P(\text{name} \mid u)\, P(s \mid \text{name})$,
  with the retained-coverage mass $\eta$ tracked per cell. `UF × cohort` remains rejected
  outright — cohort age structure varies across UFs and no defensible invariance law exists.

```python
from ptbr_sampler import sample

# strict (default): raises if you ask for a joint table that is not directly observed
sample(q=5, uf='RJ', sex_conditioning='F')                       # ValueError in 'strict'
sample(q=5, uf='RJ', sex_conditioning='F', conditioning_mode='estimated')  # OK
sample(q=5, sex_conditioning='population')                       # 2022 observed sex prior
```

## Why this matters for synthetic data

If you rescale a truncated table (say, the top 50 names renormalized to sum to 1) or treat
censored `NULL`s as zeros, you leak probability mass into the wrong places and your
"synthetic population" no longer matches the census it claims to mirror. `ptbr-sampler`
instead normalizes integer `frequency` columns in `float64` via `math.fsum` — never the
upstream 4-decimal-rounded `percentage` column (whose rounded sum is `161.9529%` for surnames
vs the exact unrounded `164.2185%`) — and audits the four regimes exhaustively at ingestion
time (`scripts/audit_datasets.py`, `tests/test_dataset_audit.py`).

*Next: [Surnames are token streams, not labels](02-surname-slots-alias-gof.md) — slot-share
math, Kahan-compensated alias tables, and four-layer goodness-of-fit validation.*

# Surnames are token streams, not labels: slot mechanics, alias tables, and honest GoF tests

*Part 2 of the `ptbr-sampler` `0.3.0` series (English).*

IBGE's press headline says **`Silva` is carried by `16.76%` of Brazilians**
($34{,}030{,}104 / 203{,}080{,}756$ residents). If you sample a "surname" categorical with
$p_{\text{Silva}} = 0.1676$, you overweight `Silva` — because a Brazilian name is not one
surname label but a **stream of surname tokens**.

## Person-level presence vs token-slot share

The 2022 census records $\bar{L} \approx 1.6422$ surname tokens per resident
($\sum_s \text{frequency}(s) = 333{,}496{,}261$ across the `201,601` distinct surnames), so
the exact unrounded ratio is $100 \times 333{,}496{,}261 / 203{,}080{,}756 = 164.2185\%$
(while summing the upstream 4-decimal-rounded `percentage` column gives `161.9529%` — tail
truncation; always normalize integer counts, never rounded percentages).

The normalized **slot probability** is

$$q_i = \frac{C_i}{C_{\text{total}}} \implies q_{\text{Silva}} = \frac{34{,}030{,}104}{333{,}496{,}261} = 10.2040\%, \qquad q_{\text{Santos}} = 6.4071\%.$$

`16.76%` is the **person-level union event** $P(\text{Silva} \in \text{person's surname set})$.
For a two-slot draw without stem replacement ($S_2 \neq S_1$),
$P(\text{Silva} \in \{S_1, S_2\}) = 1 - (1-q_{\text{Silva}})^2 \approx 19.65\%$ — consistent with
`16.76%` being an average over $\bar{L} \approx 1.6422$ slots (about one-third of residents
carry a single surname). `ptbr-sampler` samples two slots from the token distribution and
rejects stem collisions (`_surname_stem_key(S_1) \neq _surname_stem_key(S_2)`), then attaches
civil-registry prepositions (`da`, `de`, `do`, `dos`, `das`, `e`).

Regional concentration is first-class: with `uf='SE'`, surnames dispatch to
`census_year=2022/surnames/uf=SE/part.parquet` (`Santos` reaches `43.38%` person presence in
Sergipe; `Silva` `35.75%` in Alagoas, `34.23%` in Pernambuco).

## $O(1)$ draws: Kahan-compensated Walker–Vose alias tables

With $M_S = 201{,}601$ categories, a cumulative-sum draw is $O(M_S)$ per sample. The
Walker–Vose alias method gives $O(1)$ after an $O(M_S)$ build — but Vose's loop performs
sequential floating-point subtraction that **catastrophically cancels on Zipfian hubs**:
`Silva`'s scaled weight is $s_{\text{Silva}} = M_S \cdot q_{\text{Silva}} \approx 20{,}571.45$,
and subtracting it from a unit pool in `float64` loses low bits.

`ptbr-sampler` builds alias tables in `float64` with **Shewchuk-style exact bulk absorption**
(`math.fsum`) for the hub mass plus **Kahan (1965) compensated subtraction** in the loop,
achieving worst-case reconstruction error

$$\|p^{\text{alias}} - w\|_\infty = 1.39 \times 10^{-17}.$$

Every draw is then a single uniform $u \in [0,1)$ mapped through the alias table — vectorized
across batches with NumPy.

```python
import random
from ptbr_sampler import BrazilianNameSampler

sampler = BrazilianNameSampler.from_parquet(census_year=2022)
print(sampler.get_random_name(uf='SE', return_components=True, rng=random.Random(99)))
print(sampler.batch_sample_names(5, rng=random.Random(7)))
```

## Four-layer goodness-of-fit validation (why KS and top-50 χ² are wrong here)

Two legacy anti-patterns must die:

1. **Nominal Kolmogorov–Smirnov** (`ks_2samp` on strings): the empirical CDF needs a total
   order; permuting category labels changes $D_n$, so the test is not permutation-invariant
   on nominal data.
2. **Truncated rescaled top-$K$ Pearson $\chi^2$:** restricting to the top 50 names and
   renormalizing $p_j' = p_j / \sum_{r\le 50} p_r$ only tests relative head proportions — a
   bug leaking 5% of mass from the head into the tail leaves $p_j'$ unchanged and passes.

`ptbr-sampler` `0.3.0` replaces them with four layers (`ptbr_sampler/sampling/validation.py`,
`tests/test_distribution_validation.py`):

- **Layer A — deterministic conservation:** exact `float64` probability vectors
  ($\|\mathbf{w}\|_1 = 1$) and exact $O(M)$ alias reconstruction ($L_\infty < 10^{-14}$).
- **Layer B — exhaustive tail-pooled multinomial GoF with Holm–Bonferroni control:** sort
  $p_{(1)} \ge \dots \ge p_{(M)}$, greedily pool the long tail into disjoint bins with
  Cochran's criterion $E_j = n \sum_{i \in B_j} p_i \ge 5$, **without rescaling**, and compute
  both Pearson $X^2$ and log-likelihood $G^2$. Across $m$ simultaneous partition tests, Holm's
  step-down rejects $H_{(r)}$ iff $p_{(j)} \le \alpha/(m-j+1)$ for all $j \le r$ at
  $\alpha_{\text{FWER}} = 0.001$.
- **Layer C — mandatory negative controls on every run:** a synthetic 2% head-to-tail leak is
  rejected with $p < 10^{-10}$, and drawing from `top_40=True` against the full surname
  marginal is rejected immediately ($X^2 = \infty$, $p = 0$).
- **Layer D — cross-table coherence audits:**
  $\mathrm{TVD}(\sum_u \frac{\text{Pop}_u}{N} P(\cdot \mid u), P_{\text{nat}}) = 0.030919$
  (bounded by per-UF `< 15` suppression) and the decade-sum/national ratio `0.978767`
  (`2.12%` gap from `< 20` per-decade suppression).

*Next: [A 102.8 KiB wheel with census-grade data](03-slim-wheel-hf-faker-rng.md) — pinned
Hugging Face runtime, seedable RNG, Faker.*

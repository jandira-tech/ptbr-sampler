# Blog — `ptbr-sampler` for data scientists

A three-part technical series on how `ptbr-sampler` `0.3.0` turns the IBGE Census 2022
into a production-grade synthetic-data sampler. Available in English and PT-BR.

## English

1. [Sampling Brazil at census scale: what IBGE Census 2022 publishes — and what it censors](en/01-census-2022-liv102228-censoring.md)
   — the `Liv102228` four-regime suppression rules, why `99.8207%` of national given-name
   mass has directly observed sex counts, and `strict` vs `estimated` conditioning.
2. [Surnames are token streams, not labels](en/02-surname-slots-alias-gof.md)
   — `Silva` at `16.76%` person presence vs `10.2040%` slot share vs `19.65%` two-slot
   presence, Kahan-compensated Walker–Vose alias tables ($L_\infty = 1.39 \times 10^{-17}$),
   and four-layer Holm–Bonferroni goodness-of-fit validation.
3. [A 102.8 KiB wheel with census-grade data](en/03-slim-wheel-hf-faker-rng.md)
   — SHA-256-pinned Hugging Face runtime partitions, seedable `random.Random` injection,
   and first-class `Faker` integration.

## PT-BR (Português do Brasil)

1. [Amostra o Brasil em escala censitária: o que o Censo 2022 publica — e o que ele censura](pt-br/01-censo-2022-liv102228-censura.md)
2. [Sobrenomes são cadeias de tokens, não rótulos](pt-br/02-sobrenomes-slots-alias-gof.md)
3. [Um wheel de 102,8 KiB com dados de nível censitário](pt-br/03-wheel-leve-hf-faker-rng.md)

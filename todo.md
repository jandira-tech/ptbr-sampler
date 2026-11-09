# Current data and documentation status

**Baseline:** ptbr-sampler 0.3.0. This checklist supersedes the earlier audit
checklist. See [data origins](docs/data-origins.md) and
[architecture](docs/architecture.md) for implemented behavior. The original
[research report](<deep-research-report(4).md>) is an archived historical audit.

## Implemented

- [x] Provide `ptbr-data status`, `fetch`, `validate`, and `build`, with pinned
  hashes, source timestamps, caching, staged builds, and generated sidecars.
- [x] Sample UF-conditioned first names and surnames from IBGE 2022 by default.
  Direct national marginals use official POP2026 UF populations.
- [x] Add `current`, `census2022`, and `newborn2025`, with a documented per-UF
  population-derived blend and a national modeled `after2010` residual tail.
- [x] Add historical periods through `ate2020` and `after2010`, derived by stock
  subtraction. Reject non-default cohort plus an explicit period.
- [x] Support `M`, `F`, and per-row `mixed` sex conditioning from national IBGE
  empirical counts. Keep `experimental_uf_sex_conditioning` only as a
  compatibility path to `mixed`; UF conditioning no longer depends on it.
- [x] Apply `top_40` to final UF surname probabilities. Keep explicit
  `random=True` uniform over final support without changing second-name rate.
- [x] Filter the legacy second-name vocabulary and retain its ratio with an
  explicit limitation instead of claiming national validation.
- [x] Preserve all 27 official UF totals and explain the 5,570-city CEP runtime
  base versus 5,571 POP2026 source municipalities, including Boa Esperança do
  Norte (`5101837`).
- [x] Add optional namespaced Faker methods, explicit aliases, instance-safe
  reinstallation, and seeded per-instance RNG without global reseeding.
- [x] Publish deterministic future Colab and normal molab badge URLs. Do not
  advertise `/wasm`, Pyodide compatibility, or a live hosted success before
  those targets and compatibility have been tested.
- [x] Separate MIT code licensing from IBGE, Arpen, mirror, legacy, and vendored
  npm terms in `THIRD_PARTY_NOTICES.md`.

## Remaining limitations and follow-ups

- [ ] Resolve or formally assess IBGE and Arpen bulk-data reuse terms with the
  rights holders or qualified counsel. The reviewed official IBGE data page did
  not expose an explicit bulk license this project can confirm; the mirror's
  MIT code license does not settle dataset rights.
- [ ] Add CEP/DDD metadata for Boa Esperança do Norte before claiming all 5,571
  current IBGE municipalities are selectable. Keep official UF blend
  denominators unchanged when repairing runtime CEP coverage.
- [ ] Obtain a representative second-name study before changing 30.99%. Do not
  infer incidence from Arpen compound rankings.
- [ ] Replace authorial surname-prefix heuristics only if a suitable empirical
  source is acquired; prefix choices are currently style conventions.
- [ ] Exercise official IBGE v3 acquisition and compare fresh output with the
  pinned mirror when a network-enabled environment permits it. Network
  timeouts and unavailable probes must remain explicit results.
- [ ] Validate the public notebook repository links after publication and test
  marimo/Pyodide separately before adding a `/wasm` badge.
- [ ] If installed Python users need the same one-call convenience wrapper as
  source checkouts, package and test `sample.py` (or a supported package-level
  equivalent) in a behavior change outside this documentation-only task.

## Not planned as supported claims

- Treating derived stock bins as disjoint observed UF-period-sex Census rows.
- Describing Arpen top-50 rankings as complete distributions.
- Describing `current` as an official future population-name estimate.
- Treating national sex priors or 50/50 `mixed` draws as measured UF sex ratios.
- Claiming that synthetic check digits identify valid registrations or people.

# Third-Party Data & Attribution Notices

## 1. Repository Software License vs. Statistical Data Attribution

The source code of `ptbr-sampler` is licensed under the **MIT License** (`Copyright (c) 2026 Jandira Tech`; see [`LICENSE`](LICENSE)). The repository's MIT License governs the software code only and does not claim to relicense third-party or public-sector datasets. The statistical distributions, demographic frequencies, and geographic lookup tables consumed at build time or fetched at runtime originate from official Brazilian public-sector publications and third-party open compilations listed below; each source retains its own legal status, terms of use, and attribution requirements.

---

## 2. IBGE — Instituto Brasileiro de Geografia e Estatística

- **Datasets used:**
  - *Censo Demográfico 2022 — Nomes no Brasil* (reference date 1 August 2022; released 4 November 2025). Technical methodology and confidentiality rules documented in IBGE Technical Note [Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf) (suppression thresholds: `< 20` nationally and national-by-decade, `< 15` per Federation Unit, `< 10` per municipality).
  - *Censo Demográfico 2010 — Nomes no Brasil* / IBGE Nomes API v2 (`https://servicodados.ibge.gov.br/api/docs/nomes?versao=2`).
  - *Estimativas da População Residente* (reference date 1 July 2024; `https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf`).
- **Legal status & attribution:** Official Brazilian statistical disseminations published by IBGE under Brazilian open government data / public dissemination rules (Lei de Acesso à Informação — Law No. 12,527/2011; Decree No. 8,777/2016). Derived tables attribute IBGE as the primary statistical producer and preserve IBGE's disclosure-control suppression without attempting to reconstruct withheld small-cell counts.

---

## 3. Gabriel Lobo — `olob0/ibge-nomes-no-brasil-2022` (Hugging Face Compilation)

- **Repository:** <https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022>
- **Pinned revision:** `05efb85c92af43da2ed4ed088d1e0c9f17160e65`
- **Artifacts verified by SHA-256:**
  - `name_ranking.parquet` (`635691d3ce52eb59c242ecb886dbaab62b4b42e6bed4b4f1766f8c6725636c64`)
  - `name_detail.parquet` (`91518f2d0d1da8e438ab9f557127da06633e186914aecb717f1bbf7bfb6b2943`)
  - `name_by_decade.parquet` (`9f852814bf42a47358841c054a70939c763c4fc70c7e38564ad44fb94b7fbdef`)
  - `name_by_state.parquet` (`5588f012d43bb38b07691044010eb7e96cb2bfc359dd3b53a6c3b0ea46f1504e`)
  - `state.parquet` (`5d4aa2a4faf4cdef421f2563de63cd8298b58113779774045a29b9e13ddebc55`)
- **Attribution:** Tabular Parquet compilation of IBGE's *Nomes no Brasil* 2022 web-application dissemination endpoints curated by Gabriel Lobo (`@olob0`). Note that IBGE's underlying v3 web-application endpoints (`servicodados.ibge.gov.br/api/v3/nomes/...`) power the interactive portal rather than a formally versioned open-data bulk contract; `ptbr-sampler` pins the immutable commit SHA and per-file SHA-256 digests above for reproducibility.

---

## 4. Runtime Dataset Mirror — `arthrod/ptbr-sampler-data` (Hugging Face Hub)

- **Repository:** <https://huggingface.co/datasets/arthrod/ptbr-sampler-data>
- **Role in `ptbr-sampler` `0.3.0`:** Hosts the pre-ingested partitioned Parquet marginals (`parquet/census_year=2022/...` and legacy `parquet/...`) and geography/name support tables referenced by `ptbr_sampler/data/dataset_manifest.json`, keeping the published Python wheel under `150 KiB`. Every runtime file is fetched over HTTPS from an immutable 40-character Hugging Face commit SHA and verified against its manifest SHA-256 before atomic cache placement.
- **Provenance:** Derived from the IBGE, `olob0/ibge-nomes-no-brasil-2022`, Brasil.IO, Correios/ViaCEP, and Anatel sources documented in [`docs/data-origins.md`](docs/data-origins.md).

---

## 5. Brasil.IO / Álvaro Justen (`@turicas`) — `genero-nomes` (Legacy 2010 Vintage Only)

- **Source:** <https://brasil.io/dataset/genero-nomes/files/> and <https://github.com/turicas/genero-nomes>
- **License & attribution:** Creative Commons Attribution-ShareAlike 4.0 International (`CC-BY-SA-4.0`), curated by Álvaro Justen / Brasil.IO from the IBGE Nomes API (2010 Census).
- **Scope in `ptbr-sampler`:** Used exclusively for the optional historical `census_year=2010` sex-conditioned partitions (`parquet/sex_prior/scope=national/` and `parquet/first_names/period=ate*/sex=*/`). Not used in the default `census_year=2022` pipeline, which derives sex conditioning directly from empirical 2022 `male_count` / `female_count` observations (`99.8207%` national mass coverage).

---

## 6. Legacy 2010 Gemini Gender Gap-Fill (`gemini-3.1-flash-lite-preview`)

- **Artifact:** `ptbr_sampler/data/raw/gemini_gender/classifications.jsonl`
- **Scope in `ptbr-sampler`:** LLM-generated (`M`/`F`/`U`) fallback classifications for the `~8.1%` of rare/variant names in legacy 2010 `names_data.json` absent from `brasil.io/genero-nomes`. Stored with `source = 'gemini-3.1-flash-lite-preview'` and `count_male = count_female = count_total = 0` so model predictions are never conflated with empirical census counts. Never used in `census_year=2022`.

---

## 7. Arpen-Brasil, Correios / ViaCEP, and Anatel Reference Data

- **Arpen-Brasil (*Associação Nacional dos Registradores de Pessoas Naturais*):** Annual civil-registry newborn name rankings (<https://arpenbrasil.org.br/>), cited strictly as a birth-flow reference benchmark (`docs/sources/arpen-2024-rankings.md`), not mixed into IBGE resident-stock tables.
- **Correios / ViaCEP & Anatel:** Municipal postal-code prefix spans (<https://viacep.com.br/>) and DDD area codes (<https://www.anatel.gov.br/>) paired with IBGE 2024 municipal population shares in `cities_with_ceps.json`.

# Third-party notices

The ptbr-sampler source code is distributed under the [MIT License](LICENSE),
Copyright (c) 2026 Jandira Tech. That license covers this project's code. It
does not relicense upstream datasets, web services, or vendored dependencies.

This file records attribution and known distribution constraints; it is not a
legal opinion. You are responsible for reviewing the upstream terms and
assessing whether your intended use and redistribution are permitted.

## IBGE data

The build uses data associated with the Brazilian Institute of Geography and
Statistics (Instituto Brasileiro de Geografia e Estatística, IBGE):

- **Nomes no Brasil / 2022 Census**, released in 2025:
  <https://www.ibge.gov.br/apps/nomes/> and
  <https://censo2022.ibge.gov.br/nomes/>. National and federative-unit first
  names, surnames, historical stocks, and national sex counts are redistributed
  as normalized Parquet derivatives. Counts can reflect upstream suppression.
- **Population estimates 2026**:
  <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/POP2026_20261029.xlsx>.
  `estimativa_dou_2026.xlsx` is also used as a comparison source.
- **Legacy Nomes API / 2010 Census**:
  <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2>. Retained legacy
  files provide historical context and compatibility fixtures.

The official IBGE data pages reviewed for this release do not present an
explicit, identified bulk-data license that this project can confirm. No public
domain, Creative Commons, or other dataset license is asserted here. The
absence of such a statement in this notice does not establish permission.
IBGE attribution, source terms, privacy constraints, and any applicable reuse
rules remain independent of the project's MIT license. This unresolved dataset
licensing question is a release and downstream-use risk that each distributor
must evaluate.

IBGE names and marks identify the upstream publisher; they do not imply that
IBGE sponsors or approves ptbr-sampler or its modeled `current` distribution.

## Arpen-Brasil civil-registry data

The 2025 SIMPLE, COMPOUND, and ALL top-50 rankings and registered-birth totals
come from the Associação Nacional dos Registradores de Pessoas Naturais
(Arpen-Brasil) transparency portal:

- Portal: <https://transparencia.registrocivil.org.br/>
- Record API used by the build: <https://transparencia.registrocivil.org.br/api/record>
- Older 2024 contextual release:
  <https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/>

Arpen data and service terms apply independently. The MIT license does not
relicense those records. Only aggregate rankings and totals are used; the
rankings are truncated and are not complete distributions. The historical 2024
release is not the source of the current 2025 cohort model.

## Pinned IBGE mirror

The validated IBGE build reads `nomes.sqlite.zip` from:

- Repository: <https://github.com/alexsantee/nomes_do_brasil_2022>
- Pinned commit: `db1f66f397d00d4a6653204f8669c9e8c3adb256`
- Expected archive SHA-256:
  `c9d139e3281db5405590b668885bfd7d453a9e4c6e7d86d208e7b82c56c84bca`

The mirror repository identifies its **code** as MIT-licensed. That statement
does not override or replace IBGE's rights or terms for the dataset stored in
the mirror. ptbr-sampler verifies bytes and reads the database but does not
execute mirror code. Official IBGE v3 retrieval remains a separate optional
reproduction path.

## Legacy Brasil.IO and Gemini provenance

Earlier period-by-sex artifacts used these sources. They are retained as
historical provenance and compatibility data, not as fallbacks in the current
IBGE 2022 cohort build:

- **Brasil.IO / `genero-nomes`**, curated by Álvaro Justen (`@turicas`):
  <https://brasil.io/dataset/genero-nomes/files/> and
  <https://github.com/turicas/genero-nomes>. Dataset and scraper terms remain
  with their respective publishers.
- **Google Gemini classifications** from the historical
  `gemini-3.1-flash-lite-preview` run: <https://ai.google.dev/gemini-api/docs>.
  These were model-generated labels, not empirical IBGE observations. Google
  service terms apply to running the old classifier; no Gemini service is
  called by normal sampling.

## Vendored npm runtime

Online CEP resolution uses the vendored `cep-promise` browser bundle and its
runtime dependencies under `ptbr_sampler/utils/node_modules/`. Each package's
license file is included alongside its code. Versions below are pinned by the
vendored runtime; the root `package-lock.json` records the corresponding npm
installation graph.

| Package | Vendored version | License | Project |
|---|---:|---|---|
| `cep-promise` | 4.4.1 | MIT | <https://github.com/filipedeschamps/cep-promise> |
| `node-fetch` | 2.6.7 | MIT | <https://github.com/node-fetch/node-fetch> |
| `tr46` | 0.0.3 | MIT | <https://github.com/jsdom/tr46> |
| `unfetch` | 4.1.0 | MIT | <https://github.com/developit/unfetch> |
| `webidl-conversions` | 3.0.1 | BSD-2-Clause | <https://github.com/jsdom/webidl-conversions> |
| `whatwg-url` | 5.0.0 | MIT | <https://github.com/jsdom/whatwg-url> |

The package Registries and unmodified npm tarballs are at
<https://www.npmjs.com/package/cep-promise>,
<https://www.npmjs.com/package/node-fetch>,
<https://www.npmjs.com/package/tr46>,
<https://www.npmjs.com/package/unfetch>,
<https://www.npmjs.com/package/webidl-conversions>, and
<https://www.npmjs.com/package/whatwg-url>. Their copyright notices and license
texts control those vendored components.

## Other runtime and build libraries

Python dependencies declared in `pyproject.toml` retain their own licenses and
are installed separately by the package manager; they are not relicensed by
this distribution. Offline address fixtures combine project editorial curation
with Faker-style corpora. ViaCEP (<https://viacep.com.br/>) is an optional external
service, and its availability and terms govern online lookups.

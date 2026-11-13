# 🇧🇷 `ptbr-sampler` `0.3.0` — Gerador Estatístico de Dados Brasileiros

Gere nomes, endereços, CPFs, CNPJs, RGs, PIS e CEIs brasileiros **proporcionais à distribuição populacional real** e fundamentados em dados públicos auditáveis. A partir da versão **`0.3.0`**, o padrão primário é o **Censo Demográfico 2022 do IBGE** (`census_year=2022`, `TimePeriod.ALL`), e os datasets de execução são hospedados no Hugging Face Hub ([`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data)) com verificação `SHA-256` sob demanda — mantendo o pacote `.whl` **abaixo de `150 KiB`**.

As referências completas estão em [`docs/sources/bibliography.md`](docs/sources/bibliography.md) e [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); a arquitetura de dados e validação estatística está em [`docs/architecture.md`](docs/architecture.md) e [`docs/data-origins.md`](docs/data-origins.md).

*Read in English: [README.en.md](README.en.md)*

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.3.0-green.svg)](pyproject.toml)

---

## ✨ Destaques da Versão `0.3.0`

- 👤 **Censo 2022 por Padrão (`census_year=2022`, `TimePeriod.ALL`)**: `128.458` prenomes (`99,8207%` de massa com sexo observado diretamente) e `201.601` sobrenomes nacionais e por UF (`Santos` em Sergipe, `Silva` em Alagoas/Pernambuco), compilados a partir de [`olob0/ibge-nomes-no-brasil-2022`](https://huggingface.co/datasets/olob0/ibge-nomes-no-brasil-2022) (`05efb85c92af43da2ed4ed088d1e0c9f17160e65`). O Censo 2010 permanece disponível via `--census-year 2010` / `census_year=2010`.
- 📦 **Wheel Ultraleve (`< 150 KiB`) + Cache Runtime no Hugging Face**: O `.whl` embarca apenas `ptbr_sampler/data/dataset_manifest.json` (`~16 KiB`). As partições Parquet tocadas são baixadas sob demanda de `arthrod/ptbr-sampler-data` (fixadas por commit SHA imutável de 40 caracteres + `SHA-256` por arquivo) para `~/.cache/ptbr-sampler/<hf_revision>/`, com suporte total a pré-aquecimento offline (`ptbr datasets prefetch`).
- 🧭 **Separação Estrita entre Marginais Observadas e Estimativas de Bayes**: `conditioning_mode='strict'` (padrão) serve apenas distribuições observadas diretamente pelo IBGE (`nacional`, `nacional × sexo`, `nacional × coorte`, `UF`); `conditioning_mode='estimated'` habilita `UF × sexo` e `coorte × sexo` em memória via regra de Bayes sem explosão de arquivos em disco.
- 📍 **Geografia Ponderada por População e Documentos Sintéticos Válidos**: UFs e municípios ponderados pelas Estimativas da População IBGE 2024 (`212,6M`), além de CPF, RG estadual, PIS, CNPJ e CEI sintéticos.

---

## 📦 Instalação e Pré-Aquecimento de Datasets (Docker / Offline)

```bash
# Instalação rápida (< 150 KiB wheel)
uv add ptbr-sampler
# ou em um checkout local de desenvolvimento:
uv sync --extra test --extra dev
```

Na primeira chamada fora do repositório git, `ptbr-sampler` baixa apenas as partições necessárias (`~3,1 MiB` no caminho nacional padrão). Para ambientes **Docker, CI ou air-gapped**:

```bash
# Pré-baixa e valida SHA-256 de todos os artefatos do Censo 2022
ptbr datasets prefetch --census-year 2022

# Audita o status do cache e integridade SHA-256
ptbr datasets status --verify

# Execução 100% offline (falha deterministicamente se faltar algum artefato no cache)
PTBR_SAMPLER_OFFLINE=1 ptbr generate --qty 5 --uf-conditioning
```

Variáveis de ambiente suportadas:
- `PTBR_SAMPLER_CACHE_DIR`: diretório raiz do cache de usuário (padrão: `$XDG_CACHE_HOME/ptbr-sampler` ou `~/.cache/ptbr-sampler`).
- `PTBR_SAMPLER_DATA_DIR`: diretório pré-populado com os artefatos de runtime (containers imutáveis).
- `PTBR_SAMPLER_HF_REPO`: repositório espelho no Hugging Face Hub (padrão: `arthrod/ptbr-sampler-data`).
- `PTBR_SAMPLER_OFFLINE`: quando `1`/`true`, bloqueia qualquer chamada de rede em tempo de execução.

---

## 🎯 Início Rápido

### Interface de Linha de Comando (`ptbr`)

```bash
# Padrão 0.3.0: Censo 2022 (estoque completo TimePeriod.ALL) + geografia ponderada
ptbr generate --qty 5

# Condicionamento empírico por UF (prenomes e sobrenomes regionais do Censo 2022)
ptbr generate --qty 5 --uf-conditioning

# Condicionamento por sexo observado ('M', 'F', 'mixed' 50/50 ou 'population' empírico)
ptbr generate --qty 5 --sex-conditioning population

# Condicionamento conjunto UF × sexo via independência condicional de Bayes (opt-in explícito)
ptbr generate --qty 5 --uf-conditioning --sex-conditioning F --conditioning-mode estimated

# Opt-in histórico para o Censo 2010 (padrão TimePeriod.UNTIL_2010)
ptbr generate --qty 5 --census-year 2010

# Modo uniforme ("realismo desativado") e inspeção de fontes
ptbr generate --qty 5 --random
ptbr sources --census-year 2022
```

### API Python

```python
from ptbr_sampler import BrazilianNameSampler, TimePeriod, sample

# Amostragem completa (padrão: census_year=2022, time_period=TimePeriod.ALL, conditioning_mode='strict')
records = sample(q=5, uf_conditioning=True)

# Condicionamento conjunto coorte × sexo (opt-in 'estimated')
cohort_f = sample(
    q=5,
    time_period=TimePeriod.UNTIL_2020,  # nascidos em 2010–2019 no Censo 2022
    sex_conditioning='F',
    conditioning_mode='estimated',
)

# Uso direto do amostrador de nomes em Parquet (baixa sob demanda se instalado via wheel)
name_sampler = BrazilianNameSampler.from_parquet(census_year=2022)
person = name_sampler.get_random_name(uf='SE', return_components=True)

# Compatibilidade histórica com o Censo 2010
legacy_records = sample(q=5, census_year=2010)
```

---

## 📐 Metodologia Estatística, Limiares Liv102228 e Cobertura

Conforme a Nota Técnica [IBGE Liv102228](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf), o Censo 2022 suprime células com frequência **`< 20` no nível Brasil e Brasil × década**, **`< 15` por UF** e **`< 10` por município** (os limiares regionais são *menores*, não maiores, que o nacional).

### Cinco métricas distintas de cobertura de sexo (Censo 2022)
1. **Cobertura de vocabulário (tipos distintos):** `123.733 / 128.458` (`96,32%`) prenomes possuem ao menos uma contagem de sexo observada.
2. **Massa empírica observada diretamente:** **`99,8207%`** (`190.041.904 / 190.383.184` ocorrências; `60.954` linhas masculinas e `73.361` femininas).
3. **Massa deduzida como zero exato (`R = 0`):** **`55.210`** prenomes com um sexo `NULL` satisfazem $N - N_{\text{obs}} = 0$ identicamente (`one_null_exact_zero`).
4. **Massa atribuída por LLM não calibrado:** **`0,0%`** no Censo 2022 (o preenchimento via Gemini restringe-se ao modo histórico `census_year=2010`, com `count_* = 0`).
5. **Massa suprimida / excluída de condicionais de sexo:** **`341.280`** ocorrências (**`0,1793%`**, somando `232.758` residuais em `57.941` nomes `one_null_suppressed_positive` e `108.522` em `4.725` nomes `both_null_suppressed`).

### Coortes decenais, sobrenomes por slot vs. presença e datas de referência
- **Alinhamento de coortes (evitando deslocamento de 10 anos):** No legado 2010 (`names_data.json`), `ate2010` representa nascidos em `2000–2009`; no Censo 2022 (`olob0` `name_by_decade`), `decade=2000` representa `2000–2009` (`TimePeriod.UNTIL_2010`), `decade=2010` representa `2010–2019` (`TimePeriod.UNTIL_2020`), `decade=2020` representa `2020–01/08/2022` (`TimePeriod.PERIOD_2020_2022`), e `decade=1930` agrega `<= 1939` (`TimePeriod.UNTIL_1940`).
- **Probabilidade por slot vs. presença populacional de sobrenomes:** O número divulgado pelo IBGE para `Silva` (`16,76%` = `34.030.104 / 203.080.756`) mede **presença por pessoa** considerando todos os sobrenomes registrados (`~1,6422` tokens/pessoa). A fração normalizada por slot é $q_{\text{Silva}} = 10,2040\%$ ($q_{\text{Santos}} = 6,4071\%$). No modo padrão de dois sobrenomes em `2022`, o segundo slot é reamostrado condicionado a $s_2 \neq s_1$ para evitar sobrenomes duplicados (`"Silva Silva"`).
- **Datas de referência mistas e componentes autorais:** Nomes padrão refletem o estoque residente em **1º de agosto de 2022** (`203,08M`), enquanto a geografia (`locations_data.json` / `cities_with_ceps.json`) usa as Estimativas IBGE de **1º de julho de 2024** (`212,6M`). Já `middle_names.json` (`percentage_with_second = 30,99%`) e conectivos (`da`, `de`, `dos`) provêm de corpus autoral/cartorário, pois o IBGE divulga apenas o primeiro nome e sobrenomes sem preposições.

---

## 🛠️ Fluxo para Mantenedores e Testes

```bash
# Baixar snapshot fixado do Censo 2022, ingerir Parquets float64 e auditar
python -m scripts.download_datasets --fetch-ibge-2022
python -m scripts.ingest_to_parquet
python -m scripts.audit_datasets --raw-dir ptbr_sampler/data/raw/ibge_nomes_2022 --parquet-dir ptbr_sampler/data/parquet/census_year=2022

# Rodar suíte rápida (inclui reconstrução exata O(M) das tabelas de alias) e suíte Monte Carlo completa
uv run pytest -n auto -q
uv run pytest -m slow tests/test_distribution_validation.py -v
```

---

## 📄 Licença e Atribuições de Terceiros

O código-fonte deste repositório é regido pelo arquivo [`LICENSE`](LICENSE). As atribuições das fontes estatísticas públicas e compilações de terceiros (IBGE, `olob0/ibge-nomes-no-brasil-2022`, `brasil.io/genero-nomes`, Arpen-Brasil e `arthrod/ptbr-sampler-data`) estão documentadas em [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

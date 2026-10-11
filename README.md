# 🇧🇷 Gerador de Dados Brasileiros Realistas

Gere nomes, endereços, CPFs, CNPJs e outros documentos brasileiros que são **proporcionais à distribuição populacional real** e baseados **exclusivamente em dados existentes e verificados**. Cada nome gerado existe nos registros históricos brasileiros, e as localizações são amostradas proporcionalmente à população de cada região. Ao mesmo tempo, como a alocação das entidades é distrbuída aleatoreamente e a formação dos nomes, nomes do meio e sobrenomes foi feita independentemente, é **impossível** que haja qualquer possibilidade de identificar uma pessoa específica.

As referências completas estão em [`docs/sources/bibliography.md`](docs/sources/bibliography.md); a arquitetura de amostragem (Parquet particionado, método de alias Walker/Vose, cache LRU por condição) está em [`docs/architecture.md`](docs/architecture.md). A auditoria estatística que motivou esta versão está em [`deep-research-report(4).md`](deep-research-report(4).md).

*Read it in English: [English](README.en.md)*

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ Características Principais

- 📍 **Geração de Localizações**: Endereços brasileiros realistas com amostragem ponderada por população
- 👤 **Geração de Nomes**: Nomes brasileiros historicamente precisos com amostragem específica por período
- 📄 **Geração de Documentos**: Documentos brasileiros válidos (CPF, RG, PIS, CNPJ, CEI)
- 🎯 **Precisão Estatística**: Baseado em dados demográficos reais e estatísticas históricas
- 🔧 **Saída Flexível**: Dados estruturados em vários formatos (CLI, dicionários Python, pronto para API)
- ⚡ **Alto Desempenho**: Amostragem eficiente com pesos pré-calculados
- 🧪 **Completamente Testado**: Conjunto abrangente de testes para confiabilidade

## 🚀 Perfeito Para

- 🏢 **Aplicações Empresariais**: Gere dados de teste realistas para aplicações no mercado brasileiro
- 🧪 **Testes**: Crie conjuntos de dados diversos para testes abrangentes de aplicações
- 📊 **Ciência de Dados**: Gere amostras estatisticamente precisas para análise e modelagem
- 🎓 **Educação**: Aprenda sobre formatos de documentos brasileiros e regras de validação
- 🔄 **Desenvolvimento de APIs**: Dados estruturados prontos para uso em respostas de API

## 📦 Instalação

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/ptbr-sampler.git
cd ptbr-sampler

# Instale as dependências (recomenda-se usar um ambiente virtual)
uv sync

# Consulta de CEPs reais (Node.js): instala o pacote cep-promise
npm install
```

## 🎯 Início Rápido

### Interface de Linha de Comando

```bash
# Gere um perfil completo (nome, localização, documentos)
uv run ptbr sample --qty 1

# Gere apenas documentos específicos
uv run ptbr sample --only-cpf --only-rg --qty 3

# Modo "realismo desativado" (saída intencionalmente menos realista):
# localização uniforme entre estados/cidades, nomes uniformes nas tabelas,
# meio nome com 50/50 em vez do 30,99% empírico.
uv run ptbr sample --qty 5 --random
```

### API Python

```python
from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import BrazilianNameSampler, TimePeriod
from ptbr_sampler.document_sampler import DocumentSampler

# Inicialize os amostradores
location_sampler = BrazilianLocationSampler("data/cities_with_ceps.json")
name_sampler = BrazilianNameSampler("data/names_data.json", 
                                   middle_names_path="data/middle_names.json")
doc_sampler = DocumentSampler()

# Gere os dados
state_name, state_abbr, city_name = location_sampler.get_state_and_city()
name_components = name_sampler.get_random_name(
    time_period=TimePeriod.UNTIL_2010,
    return_components=True
)

# Obtenha a saída formatada
result = {
    "name": name_components.first_name,
    "middle_name": name_components.middle_name,
    "surnames": name_components.surname,
    "city": city_name,
    "state": state_name,
    "state_abbr": state_abbr,
    "cep": location_sampler.format_full_location(
        city_name, state_name, state_abbr
    ).split(',')[-1].strip(),
    "cpf": doc_sampler.generate_cpf(),
    "rg": doc_sampler.generate_rg(state_abbr)
}
```

## 🎛️ Funcionalidades em Detalhes

### Geração de Localização
- Seleção de estados e cidades ponderada por população
- Geração realista de CEPs
- Formatação flexível da saída
- Suporte para filtragem por região específica

### Geração de Nomes
- Amostragem baseada em períodos históricos
- Suporte para nomes completos, nomes do meio e sobrenomes
- Opções de formatação (título, maiúsculas)
- Opção de lista dos 40 sobrenomes mais comuns

### Geração de Documentos
- CPF (Cadastro de Pessoas Físicas)
- RG (Registro Geral) com formatos específicos por estado
- PIS (Programa de Integração Social)
- CNPJ (Cadastro Nacional da Pessoa Jurídica)
- CEI (Cadastro Específico do INSS)

### Saída de Dados
- Formato de dicionário estruturado
- CLI com formatação rica
- Suporte para geração em lote
- Campos de saída personalizáveis

## 🏗️ Estrutura do Projeto

```plaintext
src
├── br_location_class.py         # Amostragem de localização
├── br_name_class.py             # Amostragem de nomes
├── br_rg_class.py              # Geração de RG
├── cli.py                      # Interface de linha de comando
├── document_sampler.py         # Geração de documentos
├── __init__.py                 # Inicialização do pacote
└── utils/                      # Funções utilitárias
    ├── cpf.py                  # Manipulação de CPF
    ├── pis.py                  # Manipulação de PIS
    ├── cnpj.py                 # Manipulação de CNPJ
    ├── cei.py                  # Manipulação de CEI
    ├── util.py                 # Funções auxiliares
    └── __init__.py
```

## 🧪 Testes

Conjunto abrangente de testes cobrindo todos os componentes:

```bash
uv run pytest
```

## 📚 Requisitos

- Python 3.9+
- Dependências:
  - Typer (framework CLI)
  - Rich (formatação de terminal)
  - pytest (testes)
- Node.js e `npm install` (só para a consulta de CEPs reais via `cep-promise`)

## 📖 Documentação

Documentação detalhada para todas as funcionalidades e componentes:

- [Visão Geral](#visão-geral)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Funcionalidades Principais](#funcionalidades-principais)
- [Interface de Linha de Comando](#interface-de-linha-de-comando-cli)
- [Retorno de Dados](#retorno-de-dados-em-dicionários)
- [Testes e Validação](#testes-e-validação)
- [Instalação e Dependências](#instalação-e-dependências)
- [Exemplos de Uso](#exemplos-de-uso)

## 📊 Fontes e Citações

Todas as distribuições estatísticas do repositório foram construídas a partir de fontes primárias oficiais brasileiras. As principais são:

| Fonte | Escopo | URL |
|---|---|---|
| IBGE — *Nomes no Brasil*, Censo 2022 (relançamento 2025) | Nomes e sobrenomes por sexo, período de nascimento, UF e município | <https://www.ibge.gov.br/apps/nomes/> |
| IBGE — Agência de Notícias (PT) | Release do Censo 2022 *Nomes no Brasil* | <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/44929-um-pais-de-marias-joses-silvas-e-santos-ibge-lanca-nova-edicao-do-nomes-no-brasil> |
| IBGE — Destaques (EN) | Release do Censo 2022 *Nomes no Brasil* | <https://www.ibge.gov.br/en/highlights/44662-on-november-4-2025-ibge-will-release-2022-population-census-names-in-brazil.html> |
| IBGE — API Nomes v2 | Frequências por década e localidade (Censo 2010) | <https://servicodados.ibge.gov.br/api/docs/nomes?versao=2> |
| IBGE — Estimativas da População 2024 | Totais por UF e município em 1º de julho de 2024 | <https://agenciadenoticias.ibge.gov.br/agencia-noticias/2012-agencia-de-noticias/noticias/41111-populacao-estimada-do-pais-chega-a-212-6-milhoes-de-habitantes-em-2024> |
| IBGE — FTP DOU 2024 | Tabela canônica por município (PDF) | <https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf> |
| Arpen-Brasil | Ranking nacional de nascimentos 2024 | <https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/> |
| IPEA — `censobr` | Microdados do Censo 2022 em Parquet | <https://ipeagit.github.io/censobr/> |
| IPEA — `geobr` | Geometrias oficiais dos municípios | <https://ipeagit.github.io/geobr/> |

As fichas detalhadas de cada fonte (percentuais por UF, metodologia, datas de referência) estão em:

- [`docs/sources/bibliography.md`](docs/sources/bibliography.md) — índice geral.
- [`docs/sources/ibge-nomes-no-brasil-2022.md`](docs/sources/ibge-nomes-no-brasil-2022.md) — sobrenomes por UF (`Silva` 16,76% Brasil; `Santos` 43,38% Sergipe; `Silva` 35,75% Alagoas; `Silva` 34,23% Pernambuco; >200 mil sobrenomes).
- [`docs/sources/ibge-estimativas-populacao-2024.md`](docs/sources/ibge-estimativas-populacao-2024.md) — 212,6 milhões de habitantes em 01/07/2024.
- [`docs/sources/arpen-2024-rankings.md`](docs/sources/arpen-2024-rankings.md) — top 10 nacional de 2024: Helena, Miguel, Gael, Ravi, Theo, Heitor, Cecília, Arthur, Noah, Maitê.

## 🏛️ Arquitetura de Dados e Amostragem

A versão atual substitui `dict` Python aninhado por três decisões que escalam até IBGE 2022 condicionado por `(UF × década × sexo)`:

1. **Armazenamento** — Parquet particionado em `ptbr_sampler/data/parquet/` (`first_names/period=<x>/`, `surnames/scope=national/`, `middle_names/`, `states/`). Leituras via `pyarrow.dataset` com *filter pushdown* — apenas as partições efetivamente usadas são materializadas. A camada de ingestão está em [`scripts/ingest_to_parquet.py`](scripts/ingest_to_parquet.py).
2. **Primitiva de amostragem** — método de *alias* de Walker/Vose em [`ptbr_sampler/sampling/alias.py`](ptbr_sampler/sampling/alias.py): O(m) para construir, **O(1) por amostra**, totalmente vetorizado em NumPy. `k=1` e `k=100.000` têm a mesma estrutura de custo por amostra.
3. **Carregamento preguiçoso com LRU** — [`ptbr_sampler/sampling/store.py`](ptbr_sampler/sampling/store.py) encapsula partições atrás de um cache LRU limitado; condições quentes (SP/MG/RJ) permanecem residentes, condições frias paginam do disco.

O arquivo `middle_names.json` é filtrado contra uma *whitelist* de nomes próprios mantida em [`ptbr_sampler/sampling/vocabulary.py`](ptbr_sampler/sampling/vocabulary.py), descartando vazamento de sobrenomes (`Araújo`, `Borges`, `Bezerra`, …), o marcador `Cancelado` e tokens não-nominais (`-`). A validação estatística por `scipy.stats.chisquare` e `ks_2samp` vive em [`tests/test_distribution_validation.py`](tests/test_distribution_validation.py).

Para gerar a camada Parquet a partir dos JSONs legados:

```bash
python -m scripts.ingest_to_parquet
```

## 🧭 Realismo por padrão (e modo aleatório explícito)

O caminho padrão é **realismo por padrão**:

1. a geografia é amostrada primeiro, com pesos proporcionais à população
   (estado e cidade);
2. os nomes são amostrados a partir das tabelas de alias derivadas das
   distribuições empíricas (IBGE, registros civis), conforme as
   dimensões realmente disponíveis nos dados.

Quem quiser saída intencionalmente menos realista pode optar por
`random=True` (Python) ou `--random` (CLI):

```python
from sample import sample
sample(q=5)                # realismo por padrão (recomendado)
sample(q=5, random=True)   # modo aleatório explícito
```

No modo aleatório o amostrador **ignora** os pesos populacionais para a
localização, **ignora** os pesos de frequência para nomes/sobrenomes, e
substitui a taxa empírica de meio-nome (30,99%) por um sorteio
uniforme 50/50. Isto é por desenho — o objetivo do projeto continua
sendo realismo, e o flag deixa essa escolha explícita.

Importante: o modo realista **só** condiciona em dimensões que
realmente existem nos dados disponíveis. Hoje isso significa: período
para nomes, escopo nacional para sobrenomes, e participação populacional
para geografia. Não há condicionamento por UF nem por sexo no payload
distribuído — ver "Lacunas de realismo conhecidas" abaixo.

## 📥 Baixar dados e reconstruir os Parquets

Se quiser reconstruir os artefatos do zero (`todo.md` itens 1 e 11):

```bash
# 1. Inventário: o que está presente localmente, e o que cada dataset alimenta?
python -m scripts.download_datasets

# 2a. (Opcional, EXPERIMENTAL) Baixar os rankings UF × sexo × década do
#     IBGE Nomes v2 (~540 chamadas, top-20 por condição). Isso destrava o
#     condicionamento por UF/sexo para nomes; ver caveat abaixo.
python -m scripts.download_datasets --fetch-ibge-nomes

# 2b. Para qualquer linha [MISS] do passo 1, baixe a fonte e coloque em
#    ptbr_sampler/data/raw/<nome>/. Datasets distribuídos só como webapp
#    (IBGE Nomes 2022, Arpen 2024) ficam manuais por design.

# 3. Reconstrua o layout Parquet a partir dos JSONs e dos rankings raw:
python -m scripts.ingest_to_parquet

# 4. Re-rode os testes:
uv run --extra test pytest -q
```

Cada dataset, a URL canônica, o caminho local e o que ele alimenta
estão tabelados em [`docs/data-origins.md`](docs/data-origins.md) na
seção "Download-and-rebuild walkthrough".

**Requisitos de rede:** o fetch chama `servicodados.ibge.gov.br` via
HTTPS; sandboxes que restringem egress (este repositório é desenvolvido
em um deles) falham com "Host not in allowlist" / 403. Rode em uma
máquina com saída de internet liberada.

> **Handoff entre máquinas.** Se você está rodando o fetch em outra
> máquina e voltando para o Claude Code depois, siga o roteiro em
> [`docs/handoff-fetch-and-ingest.md`](docs/handoff-fetch-and-ingest.md)
> e o template de retorno em
> [`docs/handoff-resume-with-claude.md`](docs/handoff-resume-with-claude.md).

### Condicionamento UF × sexo (experimental)

Quando os rankings do passo 2a são ingeridos, o amostrador pode
condicionar nomes em `(UF, período, sexo)` — mas isso é **opt-in**:

```python
from sample import sample
sample(q=5, experimental_uf_sex_conditioning=True)
```

```bash
uv run ptbr sample --qty 5 --experimental-uf-sex
```

**Caveat (importante):** o endpoint de ranking do IBGE Nomes v2 retorna
apenas os **top 20** nomes por condição. A pool condicionada é portanto
muito mais estreita do que a tabela period-only (~milhares de nomes por
período), então ligar o flag troca diversidade distribucional por
realismo regional/sexo. Por isso o default segue period-only.

Quando uma partição `(UF, período, sexo)` específica está ausente, o
amostrador cai silenciosamente para a tabela period-only para aquela
linha — então o flag é seguro mesmo após um fetch parcial.

## ⚠️ Lacunas de realismo conhecidas

Resumo operacional dos pontos onde os dados disponíveis hoje **limitam**
o realismo da amostragem. Os detalhes completos estão em
`docs/data-origins.md`, `docs/architecture.md` e `deep-research-report(4).md`.

- **Condicionamento por UF/sexo para *nomes* — experimental, top-20.**
  O endpoint IBGE Nomes v2 expõe top-20 nomes por
  `(UF, sexo, década)`. A ingesta gravar partições
  `parquet/first_names/uf=<UF>/period=<P>/sex=<S>/` quando rodada e o
  amostrador as usa via `experimental_uf_sex_conditioning=True`. Default
  fica em period-only porque ~20 nomes/condição é muito menos do que
  ~milhares/período no caminho não-condicionado.
- **Sem condicionamento por UF para *sobrenomes*.** A release IBGE Nomes
  no Brasil 2022 publica sobrenomes por UF apenas no webapp (sem API /
  endpoint de download). Hoje sobrenomes seguem distribuição pooled
  nacional — `Santos` 43,38% em Sergipe e `Silva` 35,75% em Alagoas
  ficam subestimados. Bloqueado por dado, não por código.
- **Sem condicionamento por sexo no caminho default.** Pelo mesmo
  motivo do item anterior: o `names_data.json` agrupa M/F. O sampler
  só usa sexo quando o flag experimental está ligado E os partições
  ingeridas existem.
- **Horizonte de tempo limitado a `UNTIL_2010`.** O último bucket
  cobre nascimentos até 2010 (estoque IBGE). Coortes recentes (2011–2024)
  ficam fora; o ranking Arpen 2024 serve como benchmark de fluxo de
  recém-nascidos, mas não substitui o estoque populacional.
- **`top_40` é modo histórico.** Ele existe porque, no extrato legado,
  só os 40 maiores sobrenomes estavam consolidadamente disponíveis. A
  tabela completa (~86 mil entradas) é mais realista. `top_40` permanece
  como conveniência; não o use esperando que seja o caminho preservador
  de realismo.
- **Convenção de dois sobrenomes.** A convenção brasileira
  predominante é ter pelo menos dois sobrenomes (um por linhagem
  parental). O default mantém isso. `with_only_one_surname=True` é
  modo de compatibilidade/conveniência, **não** o realista.
- **Provenance de `middle_names.json`.** Extrato de cartórios civis
  filtrado por whitelist de nomes próprios e blocklist de sobrenomes
  (ver `ptbr_sampler/sampling/vocabulary.py`); pipeline reproduzível por
  `python -m scripts.ingest_to_parquet`. IBGE *Nomes no Brasil* só
  dissemina primeiro nome, então essa fonte é autoral por necessidade.
  Documentação detalhada em `docs/data-origins.md`.
- **`percentage_with_second = 30,99%`.** Calculado diretamente do
  extrato (`1.640.514 / 5.293.204`). Transparente para esse corpus,
  mas o corpus é autoral. Leia como estimativa explícita, não como
  fato IBGE.
- **`random=True` afrouxa todas as dimensões.** Ele é o complemento
  honesto do realismo: quem quiser saída uniforme tem como pedir.

## 📄 Licença

Este projeto está licenciado sob a Licença MIT - consulte o arquivo [LICENSE](LICENSE) para obter detalhes.


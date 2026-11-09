# ptbr-sampler

Gere perfis sintéticos brasileiros com nomes, localização, endereço, telefone e
documentos. A versão 0.3.0 usa distribuições do Censo 2022 do IBGE, registros
de nascimentos de 2025 da Arpen-Brasil e estimativas populacionais de 2026.
Os dados de entrada e as transformações são auditáveis; os resultados não
representam pessoas reais nem constituem estimativas oficiais de nomes.

*Read in English: [English](README.en.md).*

[![Python 3.12 ou superior](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Licença MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-yellow.svg)](LICENSE)
[![Abrir demonstração no Colab](https://img.shields.io/badge/Colab-Abrir%20demonstra%C3%A7%C3%A3o-F9AB00?logo=googlecolab)](https://colab.research.google.com/github/jandira-tech/ptbr-sampler-notebooks/blob/main/notebooks/ptbr_sampler_demo.ipynb)
[![Abrir demonstração no molab](https://img.shields.io/badge/molab-Abrir%20demonstra%C3%A7%C3%A3o-green)](https://molab.marimo.io/github/jandira-tech/ptbr-sampler-notebooks/blob/main/notebooks/ptbr_sampler_demo.py)

Os endereços dos notebooks são determinísticos para a publicação futura de
`jandira-tech/ptbr-sampler-notebooks`. A compatibilidade com marimo/WASM e
Pyodide ainda não foi verificada; por isso, não há link `/wasm`.

## Instalação

Instale o pacote público do PyPI com Python 3.12 ou superior:

```bash
python -m pip install ptbr-sampler==0.3.0
```

Para a integração opcional com Faker:

```bash
python -m pip install 'ptbr-sampler[faker]==0.3.0'
```

O código-fonte em `jandira-tech/ptbr-sampler` é privado; o pacote PyPI e o
repositório público de notebooks são distribuições separadas. Não é necessário
clonar o repositório-fonte para usar o CLI, os dados empacotados ou o provider.

## CLI

`ptbr sample` e `ptbr generate` são equivalentes:

```bash
ptbr sample --qty 1
ptbr generate --qty 5 --uf SP --cohort census2022 --sex-conditioning F
ptbr sample --qty 3 --time-period after2010 --return-only-name
ptbr sample --qty 5 --random --save-to-jsonl amostras.jsonl
ptbr sample --only-cpf --only-rg --qty 3
ptbr sources
```

Use `ptbr sample --help` para todos os seletores. A geração é offline por
padrão. `--make-api-call` consulta CEPs via ViaCEP; o modo `--easy` também ativa
essas chamadas, inclui todos os campos e grava em `output/output.jsonl`.

## API `sample()`

O wrapper de conveniência `sample(q=...)` está no módulo `sample.py` da raiz do
repositório-fonte. Em um checkout autorizado, os exemplos abaixo são válidos:

```python
from sample import Cohort, TimePeriod, sample
```

A distribuição wheel 0.3.0 também expõe as classes em `ptbr_sampler` e a função
de baixo nível `ptbr_sampler.sampler.sample`, mas não instala o módulo `sample`
de nível superior. Para uma API Python instalada e concisa, use o provider Faker
documentado abaixo ou o CLI.

```python
from random import Random
from sample import Cohort, TimePeriod, sample

# Coorte atual, UF sorteada pela população e sem condicionamento por sexo.
perfil = sample(q=1, rng=Random(42))

# UF fixa vale para localização, primeiros nomes e sobrenomes.
perfis = sample(q=10, cohort=Cohort.NEWBORN2025, uf='SP', sex_conditioning='F')

# Um período histórico explícito substitui a mistura de coortes.
historico = sample(q=3, time_period=TimePeriod.AFTER_2010)

# Uniforme no suporte final selecionado, sem alterar a taxa de segundo nome.
uniforme = sample(q=5, random=True)
```

`q=1` retorna um dicionário; quantidades maiores retornam uma lista. O padrão
é `cohort='current'`, `time_period=None`, `random=False` e
`sex_conditioning=None`. O wrapper inclui CPF, RG e telefone por padrão.
`census2022` ou `newborn2025` combinados com `time_period` geram `ValueError`;
apenas `current + time_period` é compatível.

### Coortes, períodos e sexo

| Seletor | Significado |
|---|---|
| `current` | Mistura sintética de Censo 2022 e nascimentos de 2025; padrão |
| `census2022` | Frequências observadas do Censo 2022, sem ajuste de recência |
| `newborn2025` | Top 50 Arpen por UF mais cauda nacional 2011–2020 modelada |
| `ate1930` … `ate2020` | Estoques e diferenças de estoques históricos nacionais do IBGE |
| `after2010` | Diferença `estoque2020 - estoque2010`, cobrindo 2011–2020 |
| `M`, `F` | Prior nacional empírico de sexo do IBGE 2022, aplicado e renormalizado |
| `mixed` | Sorteio M/F 50/50 por linha; não gera um campo `sex` na saída |

O condicionamento por sexo usa evidência **nacional**, não observações UF ×
sexo. Nomes sem contagem de sexo permanecem nas distribuições sem condição e
são omitidos apenas nas tabelas M/F. `experimental_uf_sex_conditioning=True`
permanece por compatibilidade e apenas escolhe `mixed` quando nenhum sexo foi
informado. UF já é sempre considerada; para migração, use
`sex_conditioning='mixed'` e remova o flag experimental.

A fórmula atual, por UF, é:

```text
alpha_uf = registros_Arpen2025_uf / população_oficial_IBGE_POP2026_uf
current_uf = (1 - alpha_uf) * census2022_uf + alpha_uf * newborn2025_uf
```

O residual do top 50 SIMPLE é distribuído sobre a cauda nacional `after2010`,
excluindo os rótulos observados naquela UF. Não há inferência de incidência de
nomes compostos ou segundos nomes. `current` não é uma estimativa oficial de
nomes da população futura.

Sobrenomes usam somente distribuições nacionais/por UF do IBGE 2022,
independentemente da coorte. `top_40=True` seleciona os 40 maiores sobrenomes
pelas probabilidades finais da UF e renormaliza; não é um top 40 nacional fixo.
`with_only_one_surname=True` é uma opção de saída, não uma afirmação sobre a
frequência real de um ou dois sobrenomes.

`random=True` sorteia uniformemente a localização e o suporte final de nomes e
sobrenomes. A incidência legada de 30,99% de segundo nome permanece inalterada.
Esse valor vem de `1.640.514 / 5.293.204` em um extrato antigo, não foi validado
como estatística populacional e não deve ser inferido dos rankings Arpen.

## Provider Faker

Instale o extra `faker`, registre o provider em cada instância desejada e depois
defina a semente:

```python
from faker import Faker
from ptbr_sampler.faker import install_ptbr

fake = Faker('pt_BR')
install_ptbr(fake, uf='SP', cohort='current')
fake.seed_instance(42)

perfil = fake.ptbr_profile()       # dict[str, str] coerente e completo
nome = fake.ptbr_name()            # str
cpf_sem_pontuacao = fake.ptbr_cpf(formatted=False)
cep = fake.ptbr_cep()
```

`Faker.seed(42)` e `fake.seed_instance(42)` são reproduzíveis entre instâncias
novas quando a configuração e a sequência de chamadas são iguais. O provider
usa `self.generator.random` em todos os campos e não altera o RNG global do
Python ou do NumPy. Campos escalares são chamadas independentes; apenas
`ptbr_profile()` garante que nome, UF, CEP, DDD/telefone e RG venham da mesma
linha.

Métodos namespaced disponíveis:

- Perfil e nomes: `ptbr_profile`, `ptbr_name`, `ptbr_first_name`,
  `ptbr_middle_name`, `ptbr_surname`.
- Localização: `ptbr_city`, `ptbr_state`, `ptbr_state_abbr`, `ptbr_cep`,
  `ptbr_postcode`, `ptbr_address`, `ptbr_street`, `ptbr_neighborhood`,
  `ptbr_building_number`.
- Documentos e telefone: `ptbr_cpf`, `ptbr_rg`, `ptbr_pis`, `ptbr_cnpj`,
  `ptbr_cei`, `ptbr_phone`, `ptbr_phone_number`.

`formatted=False` na instalação remove a pontuação dos documentos por padrão;
configure `cep_without_dash=True` separadamente para o CEP. Os métodos de
documento aceitam `formatted=True/False` por chamada; `ptbr_cep` e
`ptbr_postcode` aceitam `cep_without_dash=True/False`.

As opções de instalação são repassadas ao sampler: `cohort`, `time_period`,
`uf`, `sex_conditioning`, `random`, `top_40`, `name_raw`, `always_middle`,
`with_only_one_surname`, `cep_without_dash`, `include_issuer` e
`make_api_call`. `uniform` e `top40` são aliases de compatibilidade de
`random` e `top_40`; os nomes canônicos têm precedência.

Por padrão, `aliases=False` não altera métodos ou locales existentes do Faker.
Com `aliases=True`, a instância também sobrescreve `name`, `first_name`,
`last_name`, `city`, `state`, `state_abbr`, `postcode`, `address`, `cpf`,
`cnpj`, `pis` e `phone_number`. Reinstalar substitui apenas providers PTBR da
instância, remove aliases anteriores quando solicitado e preserva overrides
posteriores de terceiros. Proxies multilocale são suportados; cada gerador
mantém seu próprio RNG.

O provider funciona offline dentro de um loop assíncrono ativo. Com
`make_api_call=True`, a API síncrona `sample()` não pode resolver CEPs dentro
de um loop já ativo e levanta `RuntimeError`; execute essa chamada fora do loop
ou em uma thread separada.

## Dados, limites e reprodução

- Geografia oficial: 5.571 municípios e população nacional 214.211.951 em
  POP2026. A base CEP em runtime cobre 5.570 municípios e 214.205.968 pessoas.
  Boa Esperança do Norte (IBGE `5101837`, MT, 5.983 habitantes) não possui
  metadados CEP legados e não pode ser sorteada como cidade. Os denominadores
  de UF e `alpha_uf` continuam usando a população oficial completa.
- Nomes: 128.458 linhas nacionais IBGE 2022; sobrenomes: 201.601 linhas
  nacionais e 459.233 linhas agregadas nas 27 UFs. Supressões e ausências da
  fonte não são preenchidas como se fossem observações.
- Sexo: 123.733 nomes nacionais com contagens M/F; 4.725 nomes com sexo nulo
  são retirados somente dos condicionais M/F.
- Arpen 2025: 2.537.697 nascimentos registrados e rankings top 50
  SIMPLE/COMPOUND/ALL para Brasil e 27 UFs. Só SIMPLE entra na coorte.
- Segundo nome: 885 tokens após limpeza do extrato legado de 1.187; a taxa de
  30,99% continua sendo uma lacuna de dados, não um dado oficial nacional.

Consulte [origens, contagens e fórmulas](docs/data-origins.md),
[arquitetura](docs/architecture.md), [fontes](docs/sources/bibliography.md) e
[atribuições e termos de terceiros](THIRD_PARTY_NOTICES.md).

### Reconstruir os dados

O pacote já contém os artefatos compactos necessários. Para mantenedores:

```bash
ptbr-data status
ptbr-data fetch
ptbr-data validate
ptbr-data build
ptbr-data validate
```

`ptbr-data fetch --official` também tenta sondar a API oficial IBGE v3; falhas
de rede são explícitas. O build validado usa um espelho IBGE fixado por commit e
SHA-256, POP2026 e Arpen. O cache fica fora do pacote; o SQLite de
97.566.720 bytes serve à construção e não é distribuído. Veja o
[passo a passo e os limites de rede](docs/data-origins.md#reconstruir-os-artefatos).

## Desenvolvimento e licença

Contribuidores com acesso ao repositório privado podem usar:

```bash
git clone https://github.com/jandira-tech/ptbr-sampler.git
cd ptbr-sampler
uv sync --extra test --extra faker --extra dev
uv run ruff check --no-fix .
uv run ruff format --check .
uv run pytest -q
```

Node.js e `npm install` só são necessários para consulta online de CEP pela
integração `cep-promise`; seus pacotes runtime também são vendored no wheel.

O **código** usa a [licença MIT](LICENSE), Copyright (c) 2026 Jandira Tech.
Dados IBGE e Arpen, o espelho de terceiros e pacotes npm têm atribuições e
termos próprios descritos em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
A licença do código não altera licenças ou condições dos dados.

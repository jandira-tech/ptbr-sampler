# Uso

Todos os exemplos abaixo foram executados contra o wheel publicado `ptbr-sampler==0.3.0` no PyPI.
Instale com:

```bash
pip install "ptbr-sampler[faker]==0.3.0"     # pacote + provider Faker
# ou
uv add "ptbr-sampler[faker]==0.3.0"
```

O wheel tem **102,8 KiB** (`< 150 KiB`); os 195 datasets de execução são baixados
preguiçosamente do repositório Hugging Face fixado por SHA-256
[`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data) no
primeiro uso e ficam em cache em `~/.cache/ptbr-sampler/<hf_revision>/`.

## API Python: `sample()`

```python
import random
from ptbr_sampler import sample

# Perfil completo e coerente (nome, UF, cidade, CEP, rua, telefone, CPF, RG, PIS, CNPJ, CEI).
# rng= produz um fluxo determinístico e thread-safe sem tocar no estado global de random.
perfil = sample(q=1, all_data=True, uf_conditioning=True, rng=random.Random(2026))
```

```python
from ptbr_sampler import TimePeriod, sample

# UF fixa + condicionamento conjunto UF x sexo (2022 não tem tabela direta UF x sexo,
# então opte pela composição Bayes explicitamente):
lote = sample(
    q=5, uf='RJ', sex_conditioning='F',
    conditioning_mode='estimated', formatted=False,   # dígitos crus nos documentos
    rng=random.Random(42),
)

# Coorte de nascimento 2020-2022 (Censo 2022):
coorte = sample(q=5, time_period=TimePeriod.PERIOD_2020_2022, rng=random.Random(7))

# Vintage legada do Censo 2010 (opt-in explícito):
legado = sample(q=3, census_year=2010, rng=random.Random(1))

# Verificação de determinismo: mesma semente -> mesma saída, RNG global intacto.
a = sample(q=2, all_data=True, rng=random.Random(42))
b = sample(q=2, all_data=True, rng=random.Random(42))
assert a == b
```

`sex_conditioning` aceita `'M'`, `'F'`, `'mixed'` (50/50) e `'population'`
(participação nacional de sexo observada em 2022; exige `census_year=2022`). No
`conditioning_mode='strict'` padrão, pedir uma junta não observada (ex.: `uf` +
`sex_conditioning`) levanta um `ValueError` indicando passar `conditioning_mode='estimated'`.

## Amostragem de nomes diretamente

```python
import random
from ptbr_sampler import BrazilianNameSampler

amostrador = BrazilianNameSampler.from_parquet(census_year=2022)   # vintage padrão

componentes = amostrador.get_random_name(uf='SE', return_components=True, rng=random.Random(99))
# NameComponents(first_name='Gustavo', middle_name=None, surname='da Silva Araujo')

lote = amostrador.batch_sample_names(3, rng=random.Random(7))      # sorteios vetorizados O(1)
```

## Localidades

```python
import random
from ptbr_sampler import BrazilianLocationSampler
from ptbr_sampler.datasets import ensure_data_file

loc = BrazilianLocationSampler(ensure_data_file('cities_with_ceps.json'))
loc.get_random_location(uf='SP', rng=random.Random(5))
# 'São Bernardo do Campo, São Paulo (SP), 09853-450'
loc.get_state_and_city(uf='RJ', rng=random.Random(5))
# ('Rio de Janeiro', 'RJ', 'Rio de Janeiro')
```

## Documentos (dígito verificador válido)

```python
import random
from ptbr_sampler.utils.cpf import random_cpf
from ptbr_sampler.utils.cnpj import random_cnpj

random_cpf(rng=random.Random(3))    # '355.512.575-33'  (módulo 11 válido)
random_cnpj(rng=random.Random(3))   # '41.939.071/0005-65'
```

PIS/PASEP, CEI, RG estadual e telefones estão em `ptbr_sampler.utils.*`
(`random_pis`, `random_cei`, `random_rg`, `generate_random_phone`, ...), todos aceitando `rng=`.

## Integração Faker

```python
from faker import Faker
from ptbr_sampler.faker import install_ptbr

fake = install_ptbr(
    Faker('pt_BR'),
    uf_conditioning=True,
    sex_conditioning='population',
    conditioning_mode='estimated',
)
fake.seed_instance(12345)

perfil = fake.ptbr_profile()        # dict coerente: UF <-> cidade <-> CEP <-> DDD <-> RG
nome = fake.ptbr_name()             # nome completo ponderado pelo Censo 2022
sobrenome = fake.ptbr_surname()     # sobrenome de dois slots sem duplicar radical
cpf = fake.ptbr_cpf(formatted=True) # CPF sintético válido em módulo 11
rg_sp = fake.ptbr_rg(uf='SP')       # formato de RG da SSP-SP

# Opt-in: também vincular os aliases padrão (fake.name(), fake.cpf(), fake.city(), ...)
fake_aliased = install_ptbr(Faker('pt_BR'), aliases=True, uf='MG')
```

Por padrão (`aliases=False`) os métodos padrão do `Faker('pt_BR')` ficam intactos; os
formatadores ficam no namespace `ptbr_*`. `fake.seed_instance(S)` reproduz sequências
isoladas; para proxies multi-locale (`Faker(['pt_BR', 'en_US'])`), use `Faker.seed(S)`.

## CLI

```bash
# Tabela Rich (padrão), JSON ou JSONL
ptbr generate -n 5                     # 5 perfis completos em tabela
ptbr generate -n 2 --uf SP --format json --quiet
ptbr generate -n 100 -a -sj out.jsonl  # todos os campos, gravados em JSONL

# Condicionamento
ptbr generate -n 5 --uf RJ --sex-conditioning F --conditioning-mode estimated
ptbr generate -n 5 --sex-conditioning population        # censo 2022 padrão
ptbr generate -n 3 --census-year 2010 --time-period ate1990

# Proveniência dos dados e cache de runtime
ptbr sources                            # origem de cada dataset
ptbr sources -k surname --census-year 2022
ptbr datasets status --census-year 2022 [--verify]      # cache vs remoto, verificação SHA-256
ptbr datasets prefetch --census-year 2022               # aquece o cache (builds Docker)
ptbr datasets prefetch --all-vintages
ptbr datasets clear-cache
```

## Variáveis de ambiente de runtime

| Variável | Efeito |
| --- | --- |
| `PTBR_SAMPLER_DATA_DIR` | Diretório de override somente leitura com os arquivos de runtime (montagem de container, ex.: `/opt/ptbr-data`) |
| `PTBR_SAMPLER_IGNORE_LOCAL_DATA=1` | Ignora um `ptbr_sampler/data/` de checkout e usa só override/cache |
| `PTBR_SAMPLER_CACHE_DIR` | Raiz do cache (padrão `~/.cache/ptbr-sampler` ou `$XDG_CACHE_HOME/ptbr-sampler`) |
| `PTBR_SAMPLER_OFFLINE=1` | Bloqueia todo HTTP de runtime; usa só override/cache local |
| `PTBR_SAMPLER_HF_REPO` / `PTBR_SAMPLER_HF_REVISION` | Sobrescreve o repositório de datasets / o commit SHA de 40 caracteres fixado |

Container air-gapped típico:

```bash
ptbr datasets prefetch --all-vintages          # no build da imagem
PTBR_SAMPLER_OFFLINE=1 ptbr generate -n 10     # em execução, zero rede
```

## Superfície completa do pacote (todas as classes e funções públicas)

Tudo abaixo é documentado automaticamente a partir dos docstrings na
[Referência de API](api.md) (mkdocstrings):

| Objeto | Módulo | O que faz |
| --- | --- | --- |
| `sample()` | `ptbr_sampler` | Gerador de perfis de alto nível (nome + localidade + documentos) |
| `BrazilianNameSampler` | `ptbr_sampler.br_name_class` | Amostragem de nomes Censo 2010/2022: `from_parquet()`, `get_random_name()`, `batch_sample_names()` |
| `NameComponents` | `ptbr_sampler.br_name_class` | Dataclass: `first_name`, `middle_name`, `surname` |
| `TimePeriod` | `ptbr_sampler.br_name_class` | Enum de coortes de nascimento (`ALL`, `ate1930` … `2020_2022`) |
| `resolve_time_period()` | `ptbr_sampler.br_name_class` | Resolução de coorte |
| `BrazilianLocationSampler` | `ptbr_sampler.br_location_class` | UF/estado/cidade/CEP: `get_random_location()`, `get_state()`, `get_state_and_city()` |
| `BrazilianRG` | `ptbr_sampler.br_rg_class` | Gerador de RG por estado (formatos SSP-XX) |
| `DocumentSampler` | `ptbr_sampler.document_sampler` | Amostrador de documentos sintéticos empacotado |
| `PTBRProvider` | `ptbr_sampler.faker` | Provider Faker com os formatadores `ptbr_*` |
| `install_ptbr()` | `ptbr_sampler.faker` | Instala o provider numa instância `Faker` |
| `DatasetManifest`, `ArtifactEntry` | `ptbr_sampler.datasets` | Manifesto de runtime HF fixado (SHA-256 por artefato) |
| `ensure_data_file()`, `ensure_parquet_root()`, `resolve_partition_path()`, `resolve_bundled_or_custom_path()` | `ptbr_sampler.datasets` | Resolução em runtime: `PTBR_SAMPLER_DATA_DIR` → checkout → cache HF verificado |
| `prefetch_datasets()`, `dataset_cache_status()`, `clear_dataset_cache()`, `has_runtime_data_available()`, `get_cache_root()`, `get_revision_cache_dir()` | `ptbr_sampler.datasets` | API de gerenciamento do cache de runtime |
| `DataOrigin`, `by_kind()` | `ptbr_sampler.data_origins` | Registros de proveniência (alimenta `ptbr sources`) |
| `AliasTable`, `build_alias()`, `draw()` | `ptbr_sampler.sampling.alias` | Tabelas alias Walker–Vose $O(1)$ compensadas por Kahan |
| `PartitionSpec`, `PartitionStore`, `alias_from_mapping()` | `ptbr_sampler.sampling.store` | LRU de partições Parquet, preguiçoso e protegido por `RLock` |
| `MultinomialGoFResult`, `exhaustive_multinomial_gof()`, `holm_bonferroni_reject()`, `reconstruct_alias_probabilities()`, `linf_distance()`, `total_variation_distance()` | `ptbr_sampler.sampling.validation` | Validação de aderência em quatro camadas |
| `GivenNameVocabulary` | `ptbr_sampler.sampling.vocabulary` | Higiene do vocabulário de registro |
| `random_cpf()`, `validate_cpf()`, `cpf_check_digits()`, `format_cpf()`, `pad_cpf()` | `ptbr_sampler.utils.cpf` | CPF módulo 11 |
| `CNPJ`, `random_cnpj()`, `validate_cnpj()`, `cnpj_check_digits()`, `format_cnpj()`, `pad_cnpj()`, `parse_cnpj()`, `cnpj_from_firm_id()` | `ptbr_sampler.utils.cnpj` | CNPJ |
| `random_pis()`, `validate_pis()`, `pis_check_digit(s)`, `format_pis()`, `pad_pis()` | `ptbr_sampler.utils.pis` | PIS/PASEP |
| `random_cei()`, `validate_cei()`, `cei_check_digit()`, `format_cei()`, `pad_cei()` | `ptbr_sampler.utils.cei` | CEI |
| `PhoneNumber`, `generate_phone_number()` | `ptbr_sampler.utils.phone` | DDD + telefone |
| `AddressProvider_for_offline` | `ptbr_sampler.utils.address_for_offline` | Provider offline de rua/bairro/cidade |
| `get_cep_data()`, `node_command()`, … | `ptbr_sampler.utils.cep_wrapper` | Ponte opcional ViaCEP/Node |
| `clean_id()`, `pad_id()` | `ptbr_sampler.utils.util` | Auxiliares de ID |
| `app`, `main` | `ptbr_sampler.cli` | A CLI Typer `ptbr` |

## Nota de privacidade

Toda saída é sintética, amostrada de marginais censitárias agregadas (células `>= 20`
nacionalmente, `>= 15` por UF) mais dígitos verificadores algorítmicos. Não existe microdado
de pessoa real em nenhuma etapa do pipeline; não trate valores gerados como identidades reais.

# Um wheel de 102,8 KiB com dados de nível censitário: runtime Hugging Face fixado por SHA-256, RNG reproduzível e Faker

*Parte 3 da série `ptbr-sampler` `0.3.0` (PT-BR). Veja também a [versão em inglês](../en/03-slim-wheel-hf-faker-rng.md).*

```bash
pip install "ptbr-sampler[faker]==0.3.0"   # wheel: 102,8 KiB (< 150 KiB)
```

O wheel embarca **apenas** `ptbr_sampler/data/dataset_manifest.json` (~16 KiB). Os `195`
artefatos de execução (partições Parquet + tabelas JSON de suporte) vivem no dataset Hugging
Face [`arthrod/ptbr-sampler-data`](https://huggingface.co/datasets/arthrod/ptbr-sampler-data)
em um **commit SHA imutável de 40 caracteres** (`c30ef6ac3dbf2d1508e41dce7b6a6e47d8e6dbde`) e
são baixados preguiçosamente no primeiro uso.

## Resolução criptográfica em runtime

Cada entrada do manifesto carrega `sha256` e `size_bytes`. Em runtime,
`ptbr_sampler/datasets.py::ensure_data_file` resolve em ordem estrita:

1. **`PTBR_SAMPLER_DATA_DIR`** — montage de volume/container somente leitura
   (ex.: `/opt/ptbr-data`); com contenção verificada e, com `verify_sha256=True`, digest
   conferido.
2. **Checkout local do código-fonte** (`ptbr_sampler/data/...`), salvo se
   `PTBR_SAMPLER_IGNORE_LOCAL_DATA=1`.
3. **Cache HF verificado** `~/.cache/ptbr-sampler/<hf_revision>/` (override:
   `PTBR_SAMPLER_CACHE_DIR`).

Os downloads são gravados em `<dest>.<pid>.part` sob um `fcntl.flock` entre processos em
`<dest>.lock`, verificados quanto a contagem exata de bytes **e** SHA-256 contra o manifesto,
e então confirmados atomicamente com `os.replace` — seguro para workers concorrentes de
`pytest -n auto` e processos Gunicorn/Uvicorn. `PTBR_SAMPLER_OFFLINE=1` bloqueia
deterministicamente toda saída HTTP (operação air-gapped/Docker), e
`ptbr datasets prefetch --census-year 2022` aquece o cache no build da imagem
(`ptbr datasets status | clear-cache` inspeciona/limpa).

```bash
ptbr datasets prefetch --census-year 2022        # aquece o cache de runtime
PTBR_SAMPLER_DATA_DIR=/opt/ptbr-data ptbr generate -n 5   # override em container
```

## Randomness reproduzível e sem mutação global

RNGs globais compartilhados quebram a reprodutibilidade em apps multi-tenant. Toda API pública
aceita `rng: random.Random | None`:

```python
import random
from ptbr_sampler import sample

a = sample(q=3, all_data=True, rng=random.Random(42))
b = sample(q=3, all_data=True, rng=random.Random(42))
assert a == b                       # bit a bit idênticos; estado global random/numpy intacto
```

Internamente, um `random.Random` injetado gera um
`np.random.default_rng(rng.getrandbits(128))` efêmero para os sorteios alias vetorizados — sem
ler, semear ou restaurar os globais de `random` ou `numpy.random`. As mutações do LRU do
`PartitionStore` e os caches do amostrador são protegidos por `threading.RLock`, e os grupos
de lote são ordenados lexicograficamente antes do sorteio, de modo que a saída depende apenas da
semente, nunca da ordenação de hash.

## Integração Faker de primeira classe

```python
from faker import Faker
from ptbr_sampler.faker import PTBRProvider, install_ptbr

fake = Faker('pt_BR')
install_ptbr(fake)                    # namespaced: fake.ptbr_name(), fake.ptbr_cpf(), ...
fake.seed_instance(7)
print(fake.ptbr_profile())            # persona coerente: nome + CPF + cidade + endereço
print(fake.ptbr_name())
```

O `PTBRProvider` adiciona `ptbr_profile` mais formatadores $O(1)$ (`ptbr_name`,
`ptbr_first_name`, `ptbr_first_name_female`, `ptbr_first_name_male`, `ptbr_middle_name`,
`ptbr_surname`, `ptbr_state`, `ptbr_city`, `ptbr_cep`, `ptbr_address`, `ptbr_cpf`, `ptbr_pis`,
`ptbr_cnpj`, `ptbr_cei`, `ptbr_rg`, `ptbr_phone`, ...) e preserva os métodos padrão do
`Faker('pt_BR')` a menos que você opte explicitamente por `aliases=True`. A semente é totalmente
determinística: `fake.seed_instance(S)` reproduz sequências isoladas; para proxies
multi-locale (`Faker(['pt_BR', 'en_US'])`), use `Faker.seed(S)`.

## Engenharia de release

O `0.3.0` entrou no `main` como `5362c94` via
[PR #46](https://github.com/jandira-tech/ptbr-sampler/pull/46) com o Quality Gate do
SonarCloud **PASS** (0 issues novos, 0 hotspots de segurança, 0,6% de duplicação), Socket
Security **PASS**, os 25 achados do CodeRabbit resolvidos e respondidos, e **554 testes
passando (cobertura de 90%)** com `uv run pytest -n auto -q`. O wheel publicado tem
`102,8 KiB` com apenas `dataset_manifest.json` dentro de `ptbr_sampler/data/`; a documentação é
compilada com MkDocs Material (`mkdocs build --strict` limpo) e hospedada em
<https://ptbr-sampler.readthedocs.io/>.

*Leia as derivações completas no [Relatório Técnico](../../technical-report.md).*

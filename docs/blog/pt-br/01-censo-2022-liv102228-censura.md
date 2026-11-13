# Amostra o Brasil em escala censitária: o que o Censo 2022 do IBGE publica — e o que ele censura

*Parte 1 da série `ptbr-sampler` `0.3.0` (PT-BR). Veja também a [versão em inglês](../en/01-census-2022-liv102228-censoring.md).*

Em 4 de novembro de 2025, o IBGE divulgou a segunda edição de *Nomes no Brasil*, derivada do
cadastro domiciliar do Censo Demográfico de 1º de agosto de 2022:
$N_{\text{pop}} = 203.080.756$ residentes, `128.458` prenomes distintos e `201.601`
sobrenomes distintos, cada um com contagens de homens e mulheres, nacionalmente, por sexo, por
coorte de nascimento e nos 27 Units da Federação (UFs). O `ptbr-sampler` `0.3.0` adota esse
censo como **padrão** (`sample(q=..., census_year=2022)` é o default; `TimePeriod.ALL`).

```python
import random
from ptbr_sampler import sample

# Perfil completo e coerente (nome, UF, cidade, CEP, rua, telefone, CPF, RG, PIS, CNPJ, CEI)
perfil = sample(q=1, all_data=True, uf_conditioning=True, rng=random.Random(2026))
```

Mas um censo não é um despejo de microdados. É um **agregado com censura**: células pequenas
são suprimidas para proteger os respondentes. Tratar as tabelas publicadas como se estivessem
completas enviesa silenciosamente qualquer amostrador. Este post explica o modelo de censura e
como o `ptbr-sampler` o respeita.

## Os limiares de supressão da Nota Técnica `Liv102228`

A Nota Técnica do IBGE
[`Liv102228`](https://biblioteca.ibge.gov.br/visualizacao/livros/liv102228.pdf) define
limiares de confidencialidade **decrescentes** conforme a granularidade geográfica aumenta:

| Escopo | Suprime células com contagem abaixo de |
| --- | ---: |
| Nacional e nacional por década | `< 20` |
| Por Unidade da Federação (UF) | `< 15` |
| Por município | `< 10` |

Um nome com contagem nacional 18, por exemplo, tem as células de sexo `NULL` *nacionalmente* —
mesmo estando acima do limiar municipal. A supressão é por escopo, e os escopos se aninham.

## Os quatro regimes de célula de sexo, exatamente

Para cada prenome $i$ com frequência nacional $N_i$, a divulgação de 2022 traz a contagem
masculina $N_{i,M}$ e a feminina $N_{i,F}$, cada uma possivelmente `NULL`. O `ptbr-sampler`
classifica cada nome em exatamente um de quatro regimes disjuntos:

1. **`both_observed`** — $N_{i,M} \ge 20$ e $N_{i,F} \ge 20$: $p_{i,M} = N_{i,M}/N_i$ é uma
   probabilidade empírica diretamente observada.
2. **`one_null_exact_zero`** (`55.210` nomes) — uma célula de sexo é `NULL`, mas
   $N_{i,\text{obs}} = N_i$, logo a célula ausente é *deduzida* como exatamente zero
   ($p = 0$), não meramente pequena.
3. **`one_null_suppressed_positive`** (`57.941` nomes, `232.758` ocorrências residuais =
   `0,1223%` da massa nacional) — $N_{i,\text{obs}} < N_i$ e o resíduo
   $R_i = N_i - N_{i,\text{obs}} \in \{1, \dots, 19\}$ é estritamente positivo, porém censurado.
   A aritmética revela que $R_i$ existe, mas o IBGE reteve a divisão por sexo; o
   `ptbr-sampler` registra $p_{i,\text{obs}} = N_{i,\text{obs}}/N_i$ com precisão e guarda
   `NaN` na célula suprimida — **nunca imputa** a divisão retida.
4. **`both_null_suppressed`** (`4.725` nomes, `108.522` ocorrências = `0,057%`,
   $20 \le N_i \le 38$) — ambas as células de sexo suprimidas.

Verificação de conservação: **99,8207%** da massa nacional de prenomes publicada
(`190.041.904 / 190.383.184` ocorrências) tem contagens de sexo empiricamente observadas, e
**0,0%** é imputado por LLM no pipeline de 2022. O resíduo suprimido é **0,1793%**
(`341.280` ocorrências). Cinco métricas de cobertura distintas são reportadas em vez de um
"percentual de cobertura" ambíguo: `96,32%` de cobertura vocabular (`123.733 / 128.458`
tipos com ao menos uma contagem de sexo observada), `99,8207%` de massa observada,
`55.210` zeros exatos deduzidos, `0,0%` de massa LLM e `0,1793%` de massa suprimida.

## `strict` vs `estimated`

O Censo 2022 publica marginais 1D e 2D, não cubos multidimensionais completos. Assim:

- **`conditioning_mode='strict'` (padrão):** sorteios condicionados por sexo usam apenas as
  partições `first_names/sex=M` e `first_names/sex=F` construídas a partir de contagens
  observadas; nomes suprimidos ficam de fora das marginais por sexo, mas permanecem no
  sorteio não condicionado. Sorteios por UF usam `first_names/uf=<UF>/`.
- **`conditioning_mode='estimated'` (opt-in explícito):** para juntas não observadas como
  `UF × sexo` ou `coorte × sexo`, um reponderamento Bayes preguiçoso em memória compõe as
  marginais observadas, $P(\text{nome} \mid u, s) \propto P(\text{nome} \mid u)\, P(s \mid \text{nome})$,
  com a massa de cobertura retida $\eta$ rastreada por célula. `UF × coorte` continua
  rejeitada — a estrutura etária varia entre UFs e não há lei de invariância defensável.

```python
from ptbr_sampler import sample

# strict (padrão): erro se você pedir uma tabela conjunta não observada diretamente
sample(q=5, uf='RJ', sex_conditioning='F')                       # ValueError no modo 'strict'
sample(q=5, uf='RJ', sex_conditioning='F', conditioning_mode='estimated')  # OK
sample(q=5, sex_conditioning='population')                       # prior de sexo observado de 2022
```

## Por que isso importa para dados sintéticos

Se você reescala uma tabela truncada (por exemplo, top 50 nomes renormalizados para somar 1)
ou trata `NULL`s censurados como zeros, você desloca massa probabilística para os lugares
errados e sua "população sintética" deixa de espelhar o censo que diz representar. O
`ptbr-sampler` normaliza as colunas inteiras de `frequency` em `float64` via `math.fsum` —
nunca a coluna `percentage` arredondada em 4 casas do upstream (cuja soma arredondada dá
`161,9529%` para sobrenomes, contra `164,2185%` exato) — e audita os quatro regimes de forma
exaustiva na ingestão (`scripts/audit_datasets.py`, `tests/test_dataset_audit.py`).

*Próximo: [Sobrenomes são cadeias de tokens, não rótulos](02-sobrenomes-slots-alias-gof.md) —
matemática de participação por slot, tabelas alias compensadas por Kahan e validação de
aderência em quatro camadas.*

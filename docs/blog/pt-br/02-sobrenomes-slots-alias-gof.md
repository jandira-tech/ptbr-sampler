# Sobrenomes são cadeias de tokens, não rótulos: mecânica de slots, tabelas alias e testes de aderência honestos

*Parte 2 da série `ptbr-sampler` `0.3.0` (PT-BR). Veja também a [versão em inglês](../en/02-surname-slots-alias-gof.md).*

O título de imprensa do IBGE diz que **`Silva` está presente em `16,76%` dos brasileiros**
(`34.030.104 / 203.080.756` residentes). Se você amostrar uma categórica "sobrenome" com
$p_{\text{Silva}} = 0{,}1676$, você superestima `Silva` — porque um nome brasileiro não é um
único rótulo de sobrenome, mas uma **cadeia de tokens de sobrenome**.

## Presença por pessoa vs participação por slot

O censo de 2022 registra $\bar{L} \approx 1{,}6422$ tokens de sobrenome por residente
($\sum_s \text{frequency}(s) = 333.496.261$ entre os `201.601` sobrenomes distintos), logo a
razão exata não arredondada é $100 \times 333.496.261 / 203.080.756 = 164{,}2185\%$ (enquanto
somar a coluna `percentage` arredondada do upstream dá `161,9529%` — truncamento da cauda;
sempre normalize contagens inteiras, nunca porcentagens arredondadas).

A **probabilidade de slot** normalizada é

$$q_i = \frac{C_i}{C_{\text{total}}} \implies q_{\text{Silva}} = \frac{34.030.104}{333.496.261} = 10{,}2040\%, \qquad q_{\text{Santos}} = 6{,}4071\%.$$

`16,76%` é o **evento de união por pessoa** $P(\text{Silva} \in \text{conjunto de sobrenomes da pessoa})$.
Para um sorteio de dois slots sem reposição de radical ($S_2 \neq S_1$),
$P(\text{Silva} \in \{S_1, S_2\}) = 1 - (1-q_{\text{Silva}})^2 \approx 19{,}65\%$ — consistente
com `16,76%` ser uma média sobre $\bar{L} \approx 1{,}6422$ slots (cerca de um terço dos
residentes tem um único sobrenome). O `ptbr-sampler` sorteia dois slots da distribuição de
tokens e rejeita colisões de radical (`_surname_stem_key(S_1) \neq _surname_stem_key(S_2)`),
depois anexa as preposições de registro civil (`da`, `de`, `do`, `dos`, `das`, `e`).

A concentração regional é de primeira classe: com `uf='SE'`, os sobrenomes despacham para
`census_year=2022/surnames/uf=SE/part.parquet` (`Santos` chega a `43,38%` de presença em
Sergipe; `Silva` a `35,75%` em Alagoas e `34,23%` em Pernambuco).

## Sorteios $O(1)$: tabelas alias Walker–Vose compensadas por Kahan

Com $M_S = 201.601$ categorias, um sorteio por soma cumulativa custa $O(M_S)$ por amostra. O
método alias de Walker–Vose dá $O(1)$ após uma construção $O(M_S)$ — mas o laço de Vose faz
subtrações sequenciais em vírgula flutuante que **cancelam catastroficamente em hubs Zipfianos**:
o peso escalado de `Silva` é $s_{\text{Silva}} = M_S \cdot q_{\text{Silva}} \approx 20.571{,}45$,
e subtraí-lo de um pool unitário em `float64` perde bits baixos.

O `ptbr-sampler` constrói as tabelas alias em `float64` com **absorção exata de hubs ao estilo
Shewchuk** (`math.fsum`) para a massa do hub mais **subtração compensada de Kahan (1965)** no
laço, alcançando erro de reconstrução no pior caso

$$\|p^{\text{alias}} - w\|_\infty = 1{,}39 \times 10^{-17}.$$

Cada sorteio é então um único uniforme $u \in [0,1)$ mapeado pela tabela alias — vetorizado em
lotes com NumPy.

```python
import random
from ptbr_sampler import BrazilianNameSampler

amostrador = BrazilianNameSampler.from_parquet(census_year=2022)
print(amostrador.get_random_name(uf='SE', return_components=True, rng=random.Random(99)))
print(amostrador.batch_sample_names(5, rng=random.Random(7)))
```

## Validação de aderência em quatro camadas (por que KS e top-50 χ² estão errados aqui)

Dois antipadrões legados precisam morrer:

1. **Kolmogorov–Smirnov nominal** (`ks_2samp` sobre strings): a CDF empírica exige uma ordem
   total; permutar os rótulos muda $D_n$, logo o teste não é invariante a permutações em dados
   nominais.
2. **Pearson $\chi^2$ truncado e reescalado no top-$K$:** restringir aos top 50 nomes e
   renormalizar $p_j' = p_j / \sum_{r\le 50} p_r$ testa apenas proporções relativas do topo —
   um bug que vaze 5% de massa do topo para a cauda deixa $p_j'$ inalterado e passa no teste.

O `ptbr-sampler` `0.3.0` os substitui por quatro camadas (`ptbr_sampler/sampling/validation.py`,
`tests/test_distribution_validation.py`):

- **Camada A — conservação determinística:** vetores de probabilidade `float64` exatos
  ($\|\mathbf{w}\|_1 = 1$) e reconstrução exata $O(M)$ da tabela alias ($L_\infty < 10^{-14}$).
- **Camada B — GoF multinomial exhaustive com cauda agrupada e controle de Holm–Bonferroni:**
  ordena $p_{(1)} \ge \dots \ge p_{(M)}$, agrupa a cauda longa em bins disjuntos com o critério
  de Cochran $E_j = n \sum_{i \in B_j} p_i \ge 5$, **sem reescalar**, e calcula $X^2$ de Pearson
  e $G^2$ de verossimilhança. Em $m$ testes simultâneos, o procedimento step-down de Holm
  rejeita $H_{(r)}$ se $p_{(j)} \le \alpha/(m-j+1)$ para todo $j \le r$, com
  $\alpha_{\text{FWER}} = 0{,}001$.
- **Camada C — controles negativos obrigatórios em toda execução:** um vazamento sintético de
  2% do topo para a cauda é rejeitado com $p < 10^{-10}$, e sortear de `top_40=True` contra a
  marginal completa de sobrenomes é rejeitado na hora ($X^2 = \infty$, $p = 0$).
- **Camada D — auditorias de coerência entre tabelas:**
  $\mathrm{TVD}(\sum_u \frac{\text{Pop}_u}{N} P(\cdot \mid u), P_{\text{nat}}) = 0{,}030919$
  (limitada pela supressão `< 15` por UF) e a razão soma-por-década/nacional `0,978767`
  (lacuna de `2,12%` pela supressão `< 20` por década).

*Próximo: [Um wheel de 102,8 KiB com dados de nível censitário](03-wheel-leve-hf-faker-rng.md) —
runtime Hugging Face fixado por SHA-256, RNG reproduzível e Faker.*

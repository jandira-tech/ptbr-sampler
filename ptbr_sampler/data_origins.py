"""Machine-readable catalogue of runtime & bundled data origins.

Mirrors ``docs/data-origins.md`` — each entry describes one data type,
its manifest-backed runtime artifacts (resolved from local checkout,
``~/.cache/ptbr-sampler/<hf_revision>/``, or Hugging Face Hub
``arthrod/ptbr-sampler-data``), and the public URL where the primary
source is documented. Used by the ``ptbr sources`` CLI command.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ptbr_sampler.datasets import (
    MANIFEST_PATH,
    PACKAGE_DATA_DIR,
    get_revision_cache_dir,
    load_dataset_manifest,
)

_PACKAGE_DATA = PACKAGE_DATA_DIR


def _artifact_state(relpath: str) -> str:
    env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
    if env_data_dir and (Path(env_data_dir).expanduser() / relpath).is_file():
        return 'local-override'
    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and (_PACKAGE_DATA / relpath).is_file():
        return 'local-checkout'
    if not MANIFEST_PATH.is_file():
        return 'missing'
    manifest = load_dataset_manifest()
    if relpath not in manifest.artifacts:
        return 'missing'
    entry = manifest.artifacts[relpath]
    cache_file = get_revision_cache_dir(manifest) / relpath
    if cache_file.is_file() and cache_file.stat().st_size == entry.size_bytes:
        return 'cached'
    return 'remote-hf'


@dataclass(slots=True, frozen=True)
class DataOrigin:
    """A single data type, its runtime delivery artifacts, and its upstream authority."""

    kind: str
    summary: str
    files: tuple[Path, ...] = field(default_factory=tuple)
    remote_artifacts: tuple[str, ...] = field(default_factory=tuple)
    raw_inputs: tuple[Path, ...] = field(default_factory=tuple)
    census_years: tuple[int, ...] = (2010, 2022)
    dimensions: tuple[str, ...] = field(default_factory=tuple)
    primary_url: str = ''
    notes: str = ''

    def artifact_states(self) -> list[tuple[str, str]]:
        return [(rel, _artifact_state(rel)) for rel in self.remote_artifacts]

    def file_status(self) -> list[tuple[Path, bool]]:
        if self.remote_artifacts:
            return [(_PACKAGE_DATA / rel, state != 'missing') for rel, state in self.artifact_states()]
        return [(p, p.exists()) for p in self.files]


DATA_ORIGINS: tuple[DataOrigin, ...] = (
    DataOrigin(
        kind='First names (Census 2022)',
        summary=(
            'IBGE Censo Demográfico 2022 — Nomes no Brasil (primary 0.3.0 default, '
            '128,458 given names; disclosure thresholds < 20 national/sex/decade, < 15 UF per IBGE Liv102228). '
            'Compiled into checksum-pinned Parquet via olob0/ibge-nomes-no-brasil-2022 @ 05efb85c92af.'
        ),
        files=(_PACKAGE_DATA / 'parquet' / 'census_year=2022' / 'first_names' / 'scope=national' / 'part.parquet',),
        remote_artifacts=(
            'parquet/census_year=2022/first_names/scope=national/part.parquet',
            'parquet/census_year=2022/first_names/sex=F/part.parquet',
            'parquet/census_year=2022/first_names/sex=M/part.parquet',
        ),
        raw_inputs=(_PACKAGE_DATA / 'raw' / 'ibge_nomes_2022' / 'source_manifest.json',),
        census_years=(2022,),
        dimensions=('scope=national', 'sex=F|M', 'period=ate1940..2020_2022', 'uf=<UF>'),
        primary_url='https://censo2022.ibge.gov.br/nomes/',
        notes='See docs/sources/ibge-nomes-no-brasil-2022.md and THIRD_PARTY_NOTICES.md.',
    ),
    DataOrigin(
        kind='Sex prior (Census 2022, nullable censored)',
        summary=(
            'Exact IBGE 2022 male/female split table preserving the 4 censoring regimes '
            '(10,582 both_observed, 55,210 one_null_exact_zero, 57,941 one_null_suppressed_positive, '
            '4,725 both_null_suppressed). Suppressed cells stay nullable (None / NaN) with zero fabricated counts.'
        ),
        files=(_PACKAGE_DATA / 'parquet' / 'census_year=2022' / 'sex_prior' / 'scope=national' / 'part.parquet',),
        remote_artifacts=('parquet/census_year=2022/sex_prior/scope=national/part.parquet',),
        raw_inputs=(_PACKAGE_DATA / 'raw' / 'ibge_nomes_2022' / 'source_manifest.json',),
        census_years=(2022,),
        dimensions=(
            'name',
            'count_total',
            'count_male',
            'count_female',
            'residual_unassigned',
            'censoring_regime',
            'p_male',
            'p_female',
        ),
        primary_url='https://biblioteca.ibge.gov.br/index.php/biblioteca-catalogo?view=detalhes&id=2102228',
        notes='Used by estimated 1D multiplicative Bayes fallback when conditioning across UF+sex or cohort+sex.',
    ),
    DataOrigin(
        kind='Surnames (Census 2022)',
        summary=(
            'IBGE Censo Demográfico 2022 — Nomes no Brasil surname frequencies '
            '(201,601 national surnames + all 27 UF surname tables; Silva 34,030,104 = 16.76%, Santos 21,367,475 = 10.52%).'
        ),
        files=(_PACKAGE_DATA / 'parquet' / 'census_year=2022' / 'surnames' / 'scope=national' / 'part.parquet',),
        remote_artifacts=('parquet/census_year=2022/surnames/scope=national/part.parquet',),
        raw_inputs=(_PACKAGE_DATA / 'raw' / 'ibge_nomes_2022' / 'source_manifest.json',),
        census_years=(2022,),
        dimensions=('scope=national', 'uf=<UF>'),
        primary_url='https://censo2022.ibge.gov.br/nomes/',
        notes='Supports UF-conditioned surname draws and duplicate-stem resampling in two-surname names.',
    ),
    DataOrigin(
        kind='First names',
        summary=(
            'Legacy IBGE Nomes no Brasil (2010 Census release, 2016; explicit opt-in via census_year=2010). '
            'Frequencies by birth period: up to 1929 (ate1930), then by decade through 2010.'
        ),
        files=(
            _PACKAGE_DATA / 'names_data.json',
            _PACKAGE_DATA / 'parquet' / 'first_names' / 'period=ate2010' / 'part.parquet',
        ),
        remote_artifacts=(
            'names_data.json',
            'parquet/first_names/period=ate2010/part.parquet',
        ),
        census_years=(2010,),
        dimensions=('period', 'period x sex'),
        primary_url='https://servicodados.ibge.gov.br/api/docs/nomes?versao=2',
        notes='Historical compatibility vintage (--census-year 2010).',
    ),
    DataOrigin(
        kind='Sex prior (national, long tail)',
        summary=(
            'Legacy 2010 per-name male/female prior merging empirical brasil.io/genero-nomes '
            '(100,787 names, CC BY-SA 4.0) with LLM gap-fill classifications (7,146 names; counts stored as 0).'
        ),
        files=(_PACKAGE_DATA / 'parquet' / 'sex_prior' / 'scope=national' / 'part.parquet',),
        remote_artifacts=('parquet/sex_prior/scope=national/part.parquet',),
        raw_inputs=(
            _PACKAGE_DATA / 'raw' / 'genero_nomes' / 'nomes.csv',
            _PACKAGE_DATA / 'raw' / 'gemini_gender' / 'classifications.jsonl',
        ),
        census_years=(2010,),
        dimensions=('name', 'count_male', 'count_female', 'p_male', 'p_female', 'classification', 'source'),
        primary_url='https://data.brasil.io/dataset/genero-nomes/nomes.csv.gz',
        notes='See docs/sources/genero-nomes.md and docs/sources/gemini-gender-classifications.md.',
    ),
    DataOrigin(
        kind='Surnames',
        summary=('Legacy national surname table (~86,133 entries plus top_40 subset) used when census_year=2010.'),
        files=(
            _PACKAGE_DATA / 'surnames_data.json',
            _PACKAGE_DATA / 'parquet' / 'surnames' / 'scope=national' / 'part.parquet',
        ),
        remote_artifacts=(
            'surnames_data.json',
            'parquet/surnames/scope=national/part.parquet',
        ),
        census_years=(2010,),
        dimensions=('scope=national',),
        primary_url='https://www.ibge.gov.br/apps/nomes/',
        notes='Historical compatibility vintage (--census-year 2010).',
    ),
    DataOrigin(
        kind='Middle names',
        summary=(
            'Second given names extracted from civil registry data (~885 cleaned tokens after dropping 302 '
            'surname/artefact tokens; percentage_with_second = 30.99%). Authorial auxiliary benchmark.'
        ),
        files=(
            _PACKAGE_DATA / 'middle_names.json',
            _PACKAGE_DATA / 'parquet' / 'middle_names' / 'part.parquet',
        ),
        remote_artifacts=(
            'middle_names.json',
            'parquet/middle_names/part.parquet',
        ),
        census_years=(2010, 2022),
        dimensions=('percentage_with_second', 'second_names'),
        primary_url=(
            'https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/'
        ),
        notes='See docs/sources/arpen-2024-rankings.md and docs/data-origins.md.',
    ),
    DataOrigin(
        kind='States (UFs)',
        summary=(
            'IBGE UF population shares (Census 2022 resident total 203,080,756 in parquet/census_year=2022/states '
            'plus IBGE 2024 municipal/state location payload).'
        ),
        files=(
            _PACKAGE_DATA / 'locations_data.json',
            _PACKAGE_DATA / 'parquet' / 'states' / 'part.parquet',
            _PACKAGE_DATA / 'parquet' / 'census_year=2022' / 'states' / 'part.parquet',
        ),
        remote_artifacts=(
            'locations_data.json',
            'parquet/states/part.parquet',
            'parquet/census_year=2022/states/part.parquet',
        ),
        census_years=(2010, 2022),
        dimensions=('state_name', 'state_abbr', 'state_population', 'population_percentage'),
        primary_url='https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html',
        notes='Canonical PDF: https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf',
    ),
    DataOrigin(
        kind='Cities',
        summary=(
            'Municipal population shares (IBGE 2024 estimates), CEP prefix '
            'ranges (Correios), and DDD codes (Anatel). Optional runtime '
            'enrichment via the ViaCEP API.'
        ),
        files=(_PACKAGE_DATA / 'cities_with_ceps.json',),
        remote_artifacts=('cities_with_ceps.json',),
        census_years=(2010, 2022),
        dimensions=('city_name', 'city_uf', 'population_percentage_state', 'cep_range_begins', 'cep_range_ends', 'ddd'),
        primary_url='https://buscacepinter.correios.com.br/',
        notes='ViaCEP runtime enrichment: https://viacep.com.br/',
    ),
    DataOrigin(
        kind='Surname prefixes',
        summary=(
            'Hard-coded linguistic connectives (da, de, dos, do, das, e, '
            "d'). Authorial style prior rather than an empirical "
            'measurement — read as tunable.'
        ),
        files=(),
        census_years=(2010, 2022),
        dimensions=('SURNAME_PREFIXES (ptbr_sampler/br_name_class.py)',),
        primary_url='',
    ),
    DataOrigin(
        kind='Documents (CPF, RG, PIS, CNPJ, CEI)',
        summary=(
            'Algorithmic check-digit implementations per the public '
            'validation specs (Receita Federal / Dataprev / INSS / state '
            'SSPs). Output digits are synthetic.'
        ),
        files=(),
        census_years=(2010, 2022),
        dimensions=('ptbr_sampler/document_sampler.py', 'ptbr_sampler/utils/*'),
        primary_url='https://www.gov.br/receitafederal/pt-br',
    ),
    DataOrigin(
        kind='Addresses (offline)',
        summary=(
            'Provider corpora for street prefixes, neighbourhoods, and '
            'building numbers. Used as fallback when --make-api-call is off '
            'or when ViaCEP cannot resolve a field.'
        ),
        files=(),
        census_years=(2010, 2022),
        dimensions=('ptbr_sampler/utils/address_for_offline.py',),
        primary_url='https://viacep.com.br/',
    ),
    DataOrigin(
        kind='Phone numbers',
        summary=('Anatel DDD allocation drives the area code; subscriber digits are synthetic (mobile prefix 9 + 8 digits).'),
        files=(),
        census_years=(2010, 2022),
        dimensions=('ptbr_sampler/utils/phone.py',),
        primary_url='https://www.anatel.gov.br/consumidor/tudo-sobre-telefonia-fixa/codigos-de-area',
    ),
)


def by_kind(kind_filter: str | None = None, *, census_year: int | None = None) -> dict[str, DataOrigin]:
    """Return a name-indexed view of the catalogue, optionally filtered by substring and/or census vintage."""
    needle = kind_filter.casefold() if kind_filter else None
    out: dict[str, DataOrigin] = {}
    for origin in DATA_ORIGINS:
        if needle and needle not in origin.kind.casefold():
            continue
        if census_year is not None and census_year not in origin.census_years:
            continue
        out[origin.kind] = origin
    return out

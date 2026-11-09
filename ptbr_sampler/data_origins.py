"""Machine-readable catalogue of bundled data origins.

Mirrors ``docs/data-origins.md`` — each entry describes one data type,
the file(s) that carry it inside the installed package, and the public
URL where the primary source is documented. Used by the ``ptbr sources``
CLI command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_PACKAGE_DATA = Path(__file__).resolve().parent / 'data'


@dataclass(slots=True, frozen=True)
class DataOrigin:
    """A single bundled data type and where it came from."""

    kind: str
    summary: str
    files: tuple[Path, ...] = field(default_factory=tuple)
    dimensions: tuple[str, ...] = field(default_factory=tuple)
    primary_url: str = ''
    notes: str = ''

    def file_status(self) -> list[tuple[Path, bool]]:
        return [(p, p.exists()) for p in self.files]


DATA_ORIGINS: tuple[DataOrigin, ...] = (
    DataOrigin(
        kind='First names',
        summary=(
            'IBGE Census 2022 national and all-UF first-name frequencies, '
            'national historical stock differences through 2020, and after2010. '
            'The pinned mirror is checksum-verified; official v3 remains a '
            'separate lazy reproducibility path. Legacy 2010 data is retained.'
        ),
        files=(
            _PACKAGE_DATA / 'names_data.json',
            _PACKAGE_DATA / 'parquet' / 'ibge2022' / 'first_names',
            _PACKAGE_DATA / 'parquet' / 'ibge2022' / 'historical',
        ),
        dimensions=('census2022', 'uf', 'period'),
        primary_url='https://servicodados.ibge.gov.br/api/v3/nomes/2022/localidade/0/ranking/nome?page=1',
        notes=(
            'Pinned mirror and cryptographic hashes are recorded in data/manifest.json. '
            'IBGE data terms apply independently of mirror code licensing.'
        ),
    ),
    DataOrigin(
        kind='Sex prior (national, long tail)',
        summary=(
            'IBGE 2022 supplies 123,733 national names with empirical '
            'male/female counts in parquet/ibge2022/sex_prior; 4,725 null-sex '
            'names are excluded only from sex conditionals. Legacy Brasil.IO '
            'and Gemini files remain solely as historical provenance for the '
            'older parquet/sex_prior partitions.'
        ),
        files=(
            _PACKAGE_DATA / 'raw' / 'genero_nomes' / 'nomes.csv',
            _PACKAGE_DATA / 'raw' / 'gemini_gender' / 'classifications.jsonl',
            _PACKAGE_DATA / 'parquet' / 'sex_prior',
            _PACKAGE_DATA / 'parquet' / 'ibge2022' / 'sex_prior',
        ),
        dimensions=('name', 'count_male', 'count_female', 'p_male', 'p_female'),
        primary_url='https://www.ibge.gov.br/apps/nomes/',
        notes=(
            'See docs/sources/genero-nomes.md and '
            'docs/sources/gemini-gender-classifications.md. '
            'Fetch with "python -m scripts.download_datasets --fetch-genero-nomes" + '
            '"GEMINI_API_KEY=... python -m scripts.classify_unmatched_names_gemini". '
            'Each ingested partition ships a data_origin.json sidecar with '
            'a source breakdown (rows_from_genero_nomes vs rows_from_gemini).'
        ),
    ),
    DataOrigin(
        kind='Surnames',
        summary=(
            'IBGE Census 2022 national (201,601 rows) and all-27-UF observed '
            'surname frequencies (459,233 UF rows). Silva=34,030,104 and '
            'Santos=21,367,475 are checked against official national figures. '
            'Legacy JSON remains available for the existing sampler API.'
        ),
        files=(
            _PACKAGE_DATA / 'surnames_data.json',
            _PACKAGE_DATA / 'parquet' / 'surnames',
            _PACKAGE_DATA / 'parquet' / 'ibge2022' / 'surnames',
        ),
        dimensions=('census2022', 'scope=national', 'uf'),
        primary_url='https://www.ibge.gov.br/apps/nomes/',
        notes=(
            'Two-surname realism note: Brazilian civil naming overwhelmingly '
            'uses at least two surnames; with_only_one_surname=True is a '
            'compatibility override, not the realistic default.'
        ),
    ),
    DataOrigin(
        kind='Middle names',
        summary=(
            'Second given names, extracted from civil registry data. IBGE '
            'disseminates only first names, so this benchmark is indirect. '
            'Ingestion filters surname leakage (Araújo, Borges, …), the '
            '"Cancelado" token, and bare hyphens against a given-name '
            'whitelist (~302 of 1,187 tokens dropped). '
            'percentage_with_second = 30.99% is computed directly from '
            'total_with_second_names / total_people in the raw extract '
            '(1,640,514 / 5,293,204) — transparent for this corpus, but '
            'the corpus itself is authorial, not IBGE-published.'
        ),
        files=(
            _PACKAGE_DATA / 'middle_names.json',
            _PACKAGE_DATA / 'parquet' / 'middle_names',
        ),
        dimensions=('percentage_with_second', 'second_names'),
        primary_url=(
            'https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/'
        ),
        notes='See docs/sources/arpen-2024-rankings.md and docs/data-origins.md (cleaning pipeline).',
    ),
    DataOrigin(
        kind='Arpen 2025 newborn names',
        summary=(
            'National and all-27-UF simple, compound, and all-name top-50 '
            'rankings plus 2,537,697 registered births. Rankings are samples '
            'of the top 50 only, never complete name distributions.'
        ),
        files=(
            _PACKAGE_DATA / 'parquet' / 'arpen2025',
            _PACKAGE_DATA / 'sanitized' / 'arpen2025' / 'arpen2025_responses.jsonl.gz',
        ),
        dimensions=('kind', 'uf', 'name', 'count', 'births'),
        primary_url='https://transparencia.registrocivil.org.br/api/record/all-name?start_date=2025-01-01&end_date=2025-12-31&translate=1',
        notes=(
            'UF state=<ABBR> filter follows the official portal frontend; cached raw responses '
            'include request URL, UTC acquisition time, payload, and hashes in cache metadata.'
        ),
    ),
    DataOrigin(
        kind='States (UFs)',
        summary=(
            'IBGE POP2026 TCU-corrected estimates, 1 July 2026 (Brazil = 214,211,951). '
            'Runtime percentages use the population reconciled to the 5,570-city CEP base; '
            'source-only new municipality totals are recorded in manifest.json.'
        ),
        files=(
            _PACKAGE_DATA / 'locations_data.json',
            _PACKAGE_DATA / 'parquet' / 'states',
        ),
        dimensions=('state_name', 'state_abbr', 'state_population', 'population_percentage'),
        primary_url='https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html',
        notes=(
            'Canonical XLSX: https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/'
            'POP2026_20261029.xlsx; estimativa_dou_2026.xlsx retained as comparison/provenance in cache.'
        ),
    ),
    DataOrigin(
        kind='Cities',
        summary=(
            'Municipal population shares (IBGE POP2026 estimates), CEP prefix '
            'ranges (Correios), and DDD codes (Anatel). Optional runtime '
            'enrichment via the ViaCEP API.'
        ),
        files=(_PACKAGE_DATA / 'cities_with_ceps.json',),
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
        dimensions=('ptbr_sampler/utils/address_for_offline.py',),
        primary_url='https://viacep.com.br/',
    ),
    DataOrigin(
        kind='Phone numbers',
        summary=('Anatel DDD allocation drives the area code; subscriber digits are synthetic (mobile prefix 9 + 8 digits).'),
        files=(),
        dimensions=('ptbr_sampler/utils/phone.py',),
        primary_url='https://www.anatel.gov.br/consumidor/tudo-sobre-telefonia-fixa/codigos-de-area',
    ),
)


def by_kind() -> dict[str, DataOrigin]:
    """Return a name-indexed view of the catalogue."""
    return {o.kind: o for o in DATA_ORIGINS}

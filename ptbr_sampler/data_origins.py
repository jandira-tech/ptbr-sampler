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
            'IBGE Nomes no Brasil (2010 Census release, 2016). Frequencies '
            'by birth period: up to 1929, then by decade through 2010. The '
            '2022 Census release adds UF and sex dimensions — the Parquet '
            'layout already carries those partition keys.'
        ),
        files=(
            _PACKAGE_DATA / 'names_data.json',
            _PACKAGE_DATA / 'parquet' / 'first_names',
        ),
        dimensions=('period',),
        primary_url='https://servicodados.ibge.gov.br/api/docs/nomes?versao=2',
        notes='See docs/sources/ibge-nomes-no-brasil-2022.md',
    ),
    DataOrigin(
        kind='Surnames',
        summary=(
            'National surname distribution consistent with IBGE 2022 Census '
            'figures (Silva 16.76%, Santos ~11%). UF x period conditioning '
            'is the largest realism gap flagged by the audit; the Parquet '
            'layout is ready to receive it. The bundled JSON also exposes '
            'a "top_40" convenience subset (historical-data mode); the '
            'full ~86k-entry table is the realism-preserving default.'
        ),
        files=(
            _PACKAGE_DATA / 'surnames_data.json',
            _PACKAGE_DATA / 'parquet' / 'surnames',
        ),
        dimensions=('scope=national',),
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
        kind='States (UFs)',
        summary=(
            'IBGE Estimativas da População, 1 July 2024 (Brazil = 212.6M). Shares are population-proportional against the national total.'
        ),
        files=(
            _PACKAGE_DATA / 'locations_data.json',
            _PACKAGE_DATA / 'parquet' / 'states',
        ),
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

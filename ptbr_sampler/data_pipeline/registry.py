"""Explicit source registry; raw inputs are never confused with build outputs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

IBGE2022_URL = 'https://raw.githubusercontent.com/alexsantee/nomes_do_brasil_2022/db1f66f397d00d4a6653204f8669c9e8c3adb256/nomes.sqlite.zip'
ARPEN_BASE_URL = 'https://transparencia.registrocivil.org.br/api/record'
POP2026_URL = 'https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/POP2026_20261029.xlsx'
OFFICIAL_V3_BASE = 'https://servicodados.ibge.gov.br/api/v3/nomes/2022'


@dataclass(frozen=True, slots=True)
class Source:
    key: str
    kind: Literal['raw', 'sanitized', 'derived']
    url: str
    filename: str
    sha256: str = ''
    expected_bytes: int | None = None
    upstream_revision: str = ''


SOURCE_REGISTRY: tuple[Source, ...] = (
    Source(
        'ibge2022',
        'raw',
        IBGE2022_URL,
        'ibge2022/nomes.sqlite.zip',
        'c9d139e3281db5405590b668885bfd7d453a9e4c6e7d86d208e7b82c56c84bca',
        33_835_666,
        'db1f66f397d00d4a6653204f8669c9e8c3adb256',
    ),
    Source(
        'ibge2022_sqlite',
        'sanitized',
        IBGE2022_URL,
        'ibge2022/nomes.sqlite',
        '5c00b169e39affcdac15508ee32ea201501221152471b62947a88275bf439c48',
        97_566_720,
        'db1f66f397d00d4a6653204f8669c9e8c3adb256',
    ),
    Source(
        'pop2026',
        'raw',
        POP2026_URL,
        'geography/POP2026_20261029.xlsx',
        '6a5b50c76a5747102a6b40c0aa62498baf7ecc1f128e051e1400dfb57b88117a',
        291_627,
        '2026-10-29 TCU corrected',
    ),
    Source(
        'estimativa_dou_2026',
        'raw',
        'https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2026/estimativa_dou_2026.xlsx',
        'geography/estimativa_dou_2026.xlsx',
        '6d512a1e48506fbbfa252ba407aabc2160b07329fa652411ef7d39bd63f49284',
        247_136,
        '2026 DOU comparison',
    ),
    Source('arpen2025', 'raw', ARPEN_BASE_URL, 'arpen2025/responses.jsonl.gz', upstream_revision='2025-01-01..2025-12-31'),
    Source('ibge2022_runtime', 'derived', IBGE2022_URL, 'parquet/ibge2022', upstream_revision='Census 2022'),
    Source('arpen2025_runtime', 'derived', ARPEN_BASE_URL, 'parquet/arpen2025', upstream_revision='2025 births; top-50 samples only'),
    Source('geography_runtime', 'derived', POP2026_URL, 'cities_with_ceps.json', upstream_revision='POP2026 TCU + 5,570-city CEP base'),
)

SOURCES = {source.key: source for source in SOURCE_REGISTRY}
UF_CODES = {
    'RO': '11',
    'AC': '12',
    'AM': '13',
    'RR': '14',
    'PA': '15',
    'AP': '16',
    'TO': '17',
    'MA': '21',
    'PI': '22',
    'CE': '23',
    'RN': '24',
    'PB': '25',
    'PE': '26',
    'AL': '27',
    'SE': '28',
    'BA': '29',
    'MG': '31',
    'ES': '32',
    'RJ': '33',
    'SP': '35',
    'PR': '41',
    'SC': '42',
    'RS': '43',
    'MS': '50',
    'MT': '51',
    'GO': '52',
    'DF': '53',
}
STATE_NAMES = {
    'RO': 'Rondônia',
    'AC': 'Acre',
    'AM': 'Amazonas',
    'RR': 'Roraima',
    'PA': 'Pará',
    'AP': 'Amapá',
    'TO': 'Tocantins',
    'MA': 'Maranhão',
    'PI': 'Piauí',
    'CE': 'Ceará',
    'RN': 'Rio Grande do Norte',
    'PB': 'Paraíba',
    'PE': 'Pernambuco',
    'AL': 'Alagoas',
    'SE': 'Sergipe',
    'BA': 'Bahia',
    'MG': 'Minas Gerais',
    'ES': 'Espírito Santo',
    'RJ': 'Rio de Janeiro',
    'SP': 'São Paulo',
    'PR': 'Paraná',
    'SC': 'Santa Catarina',
    'RS': 'Rio Grande do Sul',
    'MS': 'Mato Grosso do Sul',
    'MT': 'Mato Grosso',
    'GO': 'Goiás',
    'DF': 'Distrito Federal',
}


def default_cache_dir() -> Path:
    root = os.environ.get('XDG_CACHE_HOME')
    return (Path(root) if root else Path.home() / '.cache') / 'ptbr-sampler'

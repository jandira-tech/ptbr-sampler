"""IBGE 2022 pinned mirror validation and lazy official API v3 reproducibility."""

from __future__ import annotations

import hashlib
import itertools
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ptbr_sampler.data_pipeline.http import HttpClient
from ptbr_sampler.data_pipeline.io import write_json
from ptbr_sampler.data_pipeline.registry import OFFICIAL_V3_BASE, SOURCES, UF_CODES

IBGE_MIRRORS = {'ibge2022': SOURCES['ibge2022'], 'ibge2022_sqlite': SOURCES['ibge2022_sqlite']}
REQUIRED_TABLES = {
    'frequencias': {'id_local', 'nome', 'tipo_nome', 'ano', 'frequencia'},
    'generos': {'id_local', 'nome', 'tipo_nome', 'homens', 'mulheres'},
    'municipios': {'id', 'nome', 'id_uf', 'nome_uf'},
    'populacoes': {'id_local', 'ano', 'populacao'},
}
NATIONAL_COUNTS = {'nome': (128_458, 190_383_184), 'sobrenome': (201_601, 333_496_261)}
UF_COUNTS = {'nome': (379_611,), 'sobrenome': (459_233,)}
ANCHORS = {('nome', 'maria'): 12_284_478, ('sobrenome', 'silva'): 34_030_104, ('sobrenome', 'santos'): 21_367_475}
STOCK_YEARS = tuple(range(1930, 2021, 10))


def read_ibge_mirror(path: Path) -> sqlite3.Connection:
    """Open a verified SQLite read-only, and fail before queries if its schema differs."""
    connection = sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)
    try:
        for table, columns in REQUIRED_TABLES.items():
            found = {row[1] for row in connection.execute(f'pragma table_info({table})')}
            if not columns <= found:
                raise ValueError(f'IBGE mirror schema mismatch for {table}: {sorted(found)}')
        return connection
    except Exception:
        connection.close()
        raise


def validate_mirror(connection: sqlite3.Connection) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for kind, (expected_rows, expected_sum) in NATIONAL_COUNTS.items():
        rows, total = connection.execute(
            'select count(*),sum(frequencia) from frequencias where id_local=0 and ano=2022 and tipo_nome=?', (kind,)
        ).fetchone()
        if (rows, total) != (expected_rows, expected_sum):
            raise ValueError(f'IBGE national {kind} mismatch: {(rows, total)}')
        coverage[f'national_{kind}_rows'] = rows
        coverage[f'national_{kind}_sum'] = total
    placeholders = ','.join('?' for _ in UF_CODES)
    codes = tuple(int(code) for code in UF_CODES.values())
    for kind, (expected_rows,) in UF_COUNTS.items():
        rows = connection.execute(
            'select count(*) from frequencias where ano=2022 and tipo_nome=? and id_local in (' + placeholders + ')',  # noqa: S608
            (kind, *codes),
        ).fetchone()[0]
        if rows != expected_rows:
            raise ValueError(f'IBGE UF {kind} mismatch: {rows} != {expected_rows}')
        coverage[f'uf_{kind}_rows'] = rows
    years = [
        row[0]
        for row in connection.execute(
            "select distinct ano from frequencias where id_local=0 and tipo_nome='nome' and ano<2022 order by ano"
        )
    ]
    if years != list(STOCK_YEARS):
        raise ValueError(f'IBGE historical stock years mismatch: {years}')
    sex_names, null_sex = connection.execute(
        'select sum(case when homens is not null or mulheres is not null then 1 else 0 end),'
        "sum(case when homens is null and mulheres is null then 1 else 0 end) from generos where id_local=0 and tipo_nome='nome'"
    ).fetchone()
    if (sex_names, null_sex) != (123_733, 4_725):
        raise ValueError(f'IBGE sex coverage mismatch: {(sex_names, null_sex)}')
    coverage.update({'sex_names': sex_names, 'sex_null': null_sex, 'historical_stock_years': years})
    for (kind, name), expected in ANCHORS.items():
        actual = connection.execute(
            'select frequencia from frequencias where id_local=0 and ano=2022 and tipo_nome=? and nome=?', (kind, name)
        ).fetchone()
        if actual is None or actual[0] != expected:
            raise ValueError(f'IBGE official anchor mismatch for {name}: {actual} != {expected}')
    return coverage


def derive_historical_bins(stocks: dict[str, dict[int, int]]) -> dict[str, dict[int | str, int]]:
    """Convert authoritative cumulative stocks to disjoint decade bins.

    ``after2010`` is the 2011-2020 bin and ``until2020`` remains a cumulative
    stock. No UF or sex observation is inferred from these national values.
    """
    result: dict[str, dict[int | str, int]] = {}
    for name, values in stocks.items():
        if not values:
            raise ValueError(f'{name}: no historical stocks')
        # Sparse series begin when a name first reaches the published stock.
        # Absence in a later published table is not a negative population:
        # carry the last observed cumulative stock forward (zero new births).
        complete: dict[int, int] = {}
        previous = 0
        for year in STOCK_YEARS:
            previous = int(values.get(year, previous))
            complete[year] = previous
        bins: dict[int | str, int] = {1930: complete[1930]}
        for previous, year in itertools.pairwise(STOCK_YEARS):
            difference = complete[year] - complete[previous]
            if difference < 0:
                raise ValueError(f'{name}: decreasing authoritative stock at {year}')
            bins[year] = difference
        bins['after2010'] = bins[2020]
        bins['until2020'] = complete[2020]
        result[name] = bins
    return result


class OfficialIBGEClient:
    """Lazy v3 downloader. Empty successful pages never imply an official rebuild."""

    def __init__(self, *, transport: Callable[[str, float], Any] | None = None, cache_dir: Path | None = None, retries: int = 3):
        self.http = HttpClient(retries=retries)
        self.transport = transport
        self.cache_dir = cache_dir

    def _get(self, url: str, timeout: float) -> Any:
        if self.transport:
            payload = self.transport(url, timeout)
            acquired = 'fixture'
        else:
            response = self.http.get(url, timeout=timeout)
            payload = response.json()
            acquired = response.acquired_at_utc
        if self.cache_dir:
            key = hashlib.sha256(url.encode()).hexdigest()
            response_bytes = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
            write_json(
                self.cache_dir / f'{key}.json',
                {
                    'url': url,
                    'acquired_at_utc': acquired,
                    'response_sha256': hashlib.sha256(response_bytes).hexdigest(),
                    'response_bytes': len(response_bytes),
                    'payload': payload,
                },
            )
        return payload

    def ranking(self, localidade: int | str, kind: str, *, page_size: int = 1000, timeout: float = 30) -> list[tuple[str, int]]:
        if kind not in {'nome', 'sobrenome'}:
            raise ValueError('kind must be nome or sobrenome')
        rows: list[tuple[str, int]] = []
        page = 1
        while True:
            url = f'{OFFICIAL_V3_BASE}/localidade/{localidade}/ranking/{kind}?page={page}'
            payload = self._get(url, timeout)
            batch = payload.get('data') if isinstance(payload, dict) else payload
            if not isinstance(batch, list):
                raise ValueError(f'malformed official v3 page {page}')  # noqa: TRY004
            if page == 1 and not batch:
                raise ValueError('empty official v3 first page')
            for item in batch:
                if not isinstance(item, dict) or not isinstance(item.get('nome'), str) or not isinstance(item.get('frequencia'), int):
                    raise ValueError(f'malformed official v3 row on page {page}')  # noqa: TRY004
                rows.append((item['nome'], item['frequencia']))
            if not batch or len(batch) < page_size:
                return rows
            page += 1

    def name_history(self, name: str, kind: str, localidade: int | str = 0, *, timeout: float = 30) -> list[dict[str, Any]]:
        if kind not in {'nome', 'sobrenome'}:
            raise ValueError('kind must be nome or sobrenome')
        url = f'{OFFICIAL_V3_BASE}/nome/{name}?tipo={kind}&localidade={localidade}'
        payload = self._get(url, timeout)
        if not isinstance(payload, list) or not payload:
            raise ValueError('empty or malformed official v3 name history')
        return payload

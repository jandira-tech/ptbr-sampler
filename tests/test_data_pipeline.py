"""Offline contract tests for the reproducible data acquisition pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from ptbr_sampler.data_pipeline.archive import extract_verified_sqlite
from ptbr_sampler.data_pipeline.arpen import normalise_arpen, validate_births
from ptbr_sampler.data_pipeline.cli import app
from ptbr_sampler.data_pipeline.geography import rebuild_geography
from ptbr_sampler.data_pipeline.http import HttpClient, HttpError
from ptbr_sampler.data_pipeline.ibge import (
    IBGE_MIRRORS,
    OfficialIBGEClient,
    derive_historical_bins,
    read_ibge_mirror,
)
from ptbr_sampler.data_pipeline.registry import SOURCE_REGISTRY, default_cache_dir

ROOT = Path(__file__).parents[1]
DATA = ROOT / 'ptbr_sampler' / 'data'


def make_zip(member: str = 'nomes.sqlite', payload: bytes = b'sqlite') -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr(member, payload)
    return stream.getvalue()


def test_default_cache_is_user_writable_not_site_packages():
    assert default_cache_dir().name == 'ptbr-sampler'
    assert 'site-packages' not in str(default_cache_dir())
    assert {source.kind for source in SOURCE_REGISTRY} == {'raw', 'sanitized', 'derived'}


def test_verified_archive_checks_checksum_size_and_writes_atomically(tmp_path: Path):
    body = make_zip()
    archive = tmp_path / 'source.zip'
    archive.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    output = tmp_path / 'nested' / 'nomes.sqlite'
    result = extract_verified_sqlite(archive, output, sha256=digest, zip_bytes=len(body), sqlite_bytes=6)
    assert result == output
    assert output.read_bytes() == b'sqlite'
    assert not list(tmp_path.glob('*.tmp'))


def test_verified_archive_rejects_checksum_and_zip_traversal(tmp_path: Path):
    archive = tmp_path / 'source.zip'
    archive.write_bytes(make_zip('../escape'))
    with pytest.raises(ValueError, match='checksum'):
        extract_verified_sqlite(archive, tmp_path / 'out', sha256='0' * 64, zip_bytes=archive.stat().st_size, sqlite_bytes=6)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='unsafe|member'):
        extract_verified_sqlite(archive, tmp_path / 'out', sha256=digest, zip_bytes=archive.stat().st_size, sqlite_bytes=6)


def test_http_client_retries_then_returns_metadata():
    attempts = []

    def transport(request, timeout):
        attempts.append((request.full_url, timeout))
        if len(attempts) < 3:
            raise TimeoutError('slow')
        return {'status': 200, 'body': b'{"data": [1]}', 'headers': {'ETag': 'abc'}}

    client = HttpClient(transport=transport, retries=2, backoff=0, sleeper=lambda _: None)
    response = client.get('https://example.org/data', timeout=4)
    assert response.json() == {'data': [1]}
    assert response.acquired_at_utc.endswith('+00:00')
    assert response.url == 'https://example.org/data'
    assert response.headers['ETag'] == 'abc'
    assert len(attempts) == 3
    assert all(timeout == 4 for _, timeout in attempts)


def test_http_client_does_not_hide_terminal_failure():
    client = HttpClient(transport=lambda *_: (_ for _ in ()).throw(TimeoutError('down')), retries=1, backoff=0, sleeper=lambda _: None)
    with pytest.raises(HttpError, match='after 2 attempts'):
        client.get('https://example.org/data')


def test_official_v3_paginates_and_normalises(tmp_path: Path):
    pages = {
        1: [{'nome': 'MARIA', 'frequencia': 10}, {'nome': 'JOSE', 'frequencia': 5}],
        2: [],
    }
    client = OfficialIBGEClient(transport=lambda url, timeout: {'data': pages[int(url.rsplit('=', 1)[1])]}, cache_dir=tmp_path)
    assert client.ranking(33, 'nome', page_size=2) == [('MARIA', 10), ('JOSE', 5)]
    saved = [json.loads(path.read_text()) for path in tmp_path.glob('*.json')]
    assert len(saved) == 2
    assert all({'url', 'acquired_at_utc', 'response_sha256', 'response_bytes', 'payload'} <= item.keys() for item in saved)


def test_official_v3_rejects_malformed_and_never_accepts_empty_first_page():
    with pytest.raises(ValueError, match='malformed'):
        OfficialIBGEClient(transport=lambda *_: [{'nome': 'MARIA'}]).ranking(33, 'nome')
    with pytest.raises(ValueError, match='empty'):
        OfficialIBGEClient(transport=lambda *_: []).ranking(33, 'nome')


def test_time_period_enum_exposes_2022_extensions():
    from ptbr_sampler.br_name_class import TimePeriod, TimePeriod2022

    assert TimePeriod2022.UNTIL_2020.value == 'until2020'
    assert TimePeriod2022.AFTER_2010.value == 'after2010'
    assert TimePeriod.UNTIL_2020.value == 'ate2020'
    assert TimePeriod.AFTER_2010.value == 'after2010'
    assert len(TimePeriod) == 11


def test_historical_stock_differences_and_extended_periods():
    stocks = {'ANA': {1930: 10, 1940: 15, 1950: 20, 1960: 20, 1970: 30, 1980: 35, 1990: 40, 2000: 50, 2010: 55, 2020: 70}}
    bins = derive_historical_bins(stocks)
    assert bins['ANA'][1930] == 10
    assert bins['ANA'][1940] == 5
    assert bins['ANA'][2020] == 15
    assert bins['ANA']['after2010'] == 15
    assert bins['ANA']['until2020'] == 70
    assert all(value >= 0 for value in bins['ANA'].values())


def test_historical_sparse_name_has_zero_stock_before_first_observation():
    stocks = {'AALIYAH': {2000: 10, 2010: 20, 2020: 35}}
    bins = derive_historical_bins(stocks)
    assert bins['AALIYAH'][1990] == 0
    assert bins['AALIYAH'][2000] == 10
    assert bins['AALIYAH']['after2010'] == 15


def test_historical_absent_later_stock_carries_forward_without_negative_bins():
    stocks = {'ABADIA': {1930: 4, 1940: 10, 2000: 12}}
    bins = derive_historical_bins(stocks)
    assert bins['ABADIA'][1950] == 0
    assert bins['ABADIA'][2010] == 0
    assert bins['ABADIA']['until2020'] == 12


def test_arpen_normalisation_and_birth_reconciliation():
    rows, total = normalise_arpen({'status': 1, 'data': [{'name': 'HELENA', 'total': '30'}, {'name': 'RAVI', 'total': 20}]})
    assert rows == [('HELENA', 30), ('RAVI', 20)]
    assert total == 50
    births = {'data': [{'name': 'AC', 'total': 2}, {'name': 'BR', 'total': 2}]}
    assert validate_births(births, expected_ufs={'AC'}) == {'AC': 2, 'BR': 2}
    with pytest.raises(ValueError, match='missing UFs'):
        validate_births(births, expected_ufs={'AC', 'SP'})
    with pytest.raises(ValueError, match='top-level'):
        validate_births({'data': [{'name': 'AC', 'total': 2}], 'total': 3}, expected_ufs={'AC'})


def test_geography_joins_full_ibge_code_and_preserves_every_city(tmp_path: Path):
    cities = {
        'cities': {
            'Acrelândia_AC': {
                'city_name': 'Acrelândia',
                'city_uf': 'AC',
                'uf_code': '12',
                'city_code': '00013',
                'ddd': '68',
                'ceps': ['69945000'],
                'latitude': -9.8,
                'longitude': -67.8,
            },
            'Rio Branco_AC': {
                'city_name': 'Rio Branco',
                'city_uf': 'AC',
                'uf_code': '12',
                'city_code': '00139',
                'ddd': '68',
                'ceps': ['69900000'],
            },
        }
    }
    population = {1200013: 100, 1200139: 300}
    result = rebuild_geography(cities, population, national_population=400, state_names={'AC': 'Acre'})
    assert len(result['cities']['cities']) == 2
    assert result['cities']['cities']['Acrelândia_AC']['ibge_code'] == '1200013'
    assert result['cities']['cities']['Acrelândia_AC']['population_percentage_state'] == 25.0
    assert result['cities']['cities']['Rio Branco_AC']['population_percentage_total'] == 75.0
    assert result['locations']['states']['Acre']['population_percentage'] == 100.0
    assert result['table_totals'] == {'cities': 2, 'states': 1, 'national_population': 400}
    with pytest.raises(ValueError, match='population join'):
        rebuild_geography(cities, {1200013: 100}, national_population=400, state_names={'AC': 'Acre'})


@pytest.mark.real_data
def test_committed_ibge_artifacts_have_verified_counts_anchors_and_sidecars():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    assert manifest['sources']['ibge2022']['sha256'] == IBGE_MIRRORS['ibge2022'].sha256
    first = pq.read_table(DATA / 'parquet' / 'ibge2022' / 'first_names' / 'scope=national' / 'part.parquet').to_pylist()
    surnames = pq.read_table(DATA / 'parquet' / 'ibge2022' / 'surnames' / 'scope=national' / 'part.parquet').to_pylist()
    assert len(first) == 128_458
    assert len(surnames) == 201_601
    assert sum(row['count'] for row in first) == 190_383_184
    assert sum(row['count'] for row in surnames) == 333_496_261
    assert next(row['count'] for row in first if row['name'] == 'maria') == 12_284_478
    assert next(row['count'] for row in surnames if row['name'] == 'silva') == 34_030_104
    assert next(row['count'] for row in surnames if row['name'] == 'santos') == 21_367_475
    assert all(row['weight'] >= 0 for row in first + surnames)
    assert abs(sum(row['weight'] for row in first) - 1) < 1e-5


@pytest.mark.real_data
def test_committed_runtime_inventory_geography_and_arpen():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    assert manifest['coverage']['ibge_ufs'] == 27
    assert manifest['coverage']['ibge_uf_first_rows'] == 379_611
    assert manifest['coverage']['ibge_uf_surname_rows'] == 459_233
    assert manifest['coverage']['ibge_sex_names'] == 123_733
    assert manifest['coverage']['ibge_sex_null'] == 4_725
    assert manifest['coverage']['cities'] == 5_570
    assert manifest['coverage']['states'] == 27
    assert manifest['coverage']['arpen_births'] == 2_537_697
    assert len(manifest['sources']['arpen2025']['sha256']) == 64
    assert manifest['sources']['arpen2025']['bytes'] > 0
    cities = json.loads((DATA / 'cities_with_ceps.json').read_text())
    locations = json.loads((DATA / 'locations_data.json').read_text())
    assert len(cities['cities']) == len(locations['cities']) == 5_570
    assert len(locations['states']) == 27
    assert abs(sum(s['population_percentage'] for s in locations['states'].values()) - 100) < 1e-6
    for city in cities['cities'].values():
        assert len(city['ibge_code']) == 7
        assert 0 <= city['population_percentage_total'] <= 100
        assert 0 <= city['population_percentage_state'] <= 100
    arpen_sidecar = json.loads((DATA / 'parquet' / 'arpen2025' / 'all' / 'scope=national' / 'data_origin.json').read_text())
    assert '/all-name?' in arpen_sidecar['source_url']
    assert '2025-12-31' in arpen_sidecar['source_url']
    for root in ('ibge2022', 'arpen2025'):
        for parquet in DATA.joinpath('parquet', root).rglob('*.parquet'):
            sidecar_path = parquet.with_name('data_origin.json')
            assert sidecar_path.is_file(), parquet
            sidecar = json.loads(sidecar_path.read_text())
            assert {
                'source',
                'source_url',
                'rows',
                'coverage',
                'transformation',
                'provenance',
                'suppression',
                'limitations',
            } <= sidecar.keys()
    joined_national = locations['states'] and sum(state['joined_city_population'] for state in locations['states'].values())
    official_national = sum(state['state_population'] for state in locations['states'].values())
    assert (
        abs(sum(city['population_percentage_total'] for city in cities['cities'].values()) - 100 * joined_national / official_national)
        < 1e-6
    )
    for state in locations['states'].values():
        uf = state['state_abbr']
        expected_percentage = 100 * state['joined_city_population'] / state['state_population']
        assert (
            abs(
                sum(city['population_percentage_state'] for city in cities['cities'].values() if city['city_uf'] == uf)
                - expected_percentage
            )
            < 1e-6
        )
        assert (
            sum(city['city_population'] for city in cities['cities'].values() if city['city_uf'] == uf) == state['joined_city_population']
        )
        assert state['joined_city_population'] + state['unmatched_source_population'] == state['state_population']


def test_fetch_arpen_source_uses_verified_national_and_uf_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ptbr_sampler.data_pipeline import cli
    from ptbr_sampler.data_pipeline.registry import STATE_NAMES

    def transport(request, timeout):
        url = request.full_url
        if '/birth?' in url:
            payload = {'data': [{'name': uf, 'total': 100} for uf in STATE_NAMES], 'total': 2700}
        else:
            uf = url.rsplit('state=', 1)[1] if 'state=' in url else 'BR'
            payload = {'data': [{'name': f'NOME {uf}', 'total': len(uf)}]}
        return {'status': 200, 'body': json.dumps(payload).encode(), 'headers': {}}

    monkeypatch.setattr(cli, 'HttpClient', lambda: HttpClient(transport=transport, retries=0))
    result = CliRunner().invoke(cli.app, ['fetch', '--source', 'arpen2025', '--cache-dir', str(tmp_path)])
    assert result.exit_code == 0, result.output
    metadata = json.loads((tmp_path / 'arpen2025' / 'responses.jsonl.gz.meta.json').read_text())
    assert metadata['rows'] == 85
    assert len(metadata['sha256']) == 64


def test_cli_status_and_invalid_command_exit_codes(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(app, ['status', '--cache-dir', str(tmp_path), '--data-dir', str(tmp_path / 'data')])
    assert result.exit_code == 0
    assert 'ibge2022' in result.stdout
    result = runner.invoke(app, ['validate', '--data-dir', str(tmp_path / 'missing')])
    assert result.exit_code == 1
    assert 'manifest' in result.output


def test_read_mirror_requires_expected_schema(tmp_path: Path):
    db = tmp_path / 'bad.sqlite'
    connection = sqlite3.connect(db)
    connection.execute('create table nope(value text)')
    connection.close()
    with pytest.raises(ValueError, match='schema'):
        read_ibge_mirror(db)

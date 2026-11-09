"""Security, source-integrity, and generation-transaction regression tests."""

from __future__ import annotations

import gzip
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ptbr_sampler.data_pipeline import build as build_module
from ptbr_sampler.data_pipeline.arpen import fetch_arpen2025, normalise_arpen, validate_births
from ptbr_sampler.data_pipeline.geography import read_pop2026, read_population_workbook, rebuild_geography
from ptbr_sampler.data_pipeline.http import HttpClient
from ptbr_sampler.data_pipeline.registry import SOURCE_REGISTRY, Source

ROOT = Path(__file__).parents[1]
DATA = ROOT / 'ptbr_sampler' / 'data'
CACHE = ROOT / '.cache' / 'ptbr-data'


def insecure_response(*args, **kwargs) -> dict[str, Any]:
    return {
        'status': 200,
        'body': b'{}',
        'stream': io.BytesIO(b'x'),
        'headers': {},
        'final_url': 'http://example.org/final',
    }


def source() -> Source:
    return Source('redirect', 'raw', 'https://example.org/data.bin', 'data.bin', expected_bytes=1)


def test_get_rejects_https_to_http_downgrade_from_fake_transport():
    requests = []

    def transport(request, timeout):
        requests.append(request.full_url)
        return insecure_response()

    with pytest.raises(ValueError, match='HTTPS'):
        HttpClient(transport=transport).get('https://example.org/data')
    assert requests == ['https://example.org/data']


def test_download_rejects_https_to_http_downgrade_from_fake_transport(tmp_path: Path):
    requests = []

    def transport(request, timeout):
        requests.append(request.full_url)
        return insecure_response()

    with pytest.raises(ValueError, match='HTTPS'):
        HttpClient(stream_transport=transport).download(source(), tmp_path / 'data.bin')
    assert requests == ['https://example.org/data.bin']
    assert not (tmp_path / 'data.bin').exists()


def test_redirect_chain_cannot_contain_insecure_hop():
    response = insecure_response(final_url='https://example.org/final')
    response['redirect_urls'] = ['https://example.org/start', 'http://example.org/hop']
    with pytest.raises(ValueError, match='HTTPS'):
        HttpClient(transport=lambda *_: response).get('https://example.org/start')


def test_json_body_limit_and_known_size_stream_limit(tmp_path: Path):
    with pytest.raises(ValueError, match='response body exceeds'):
        HttpClient(max_response_bytes=8, transport=lambda *_: {'body': b'123456789'}).get('https://example.org/data')
    with pytest.raises(ValueError, match='exceeds expected bytes'):
        HttpClient(stream_transport=lambda *_: {'stream': io.BytesIO(b'ab')}).download(source(), tmp_path / 'data.bin')


@pytest.mark.parametrize('key', ['pop2026', 'estimativa_dou_2026'])
def test_workbook_hash_is_checked_immediately_before_opening(key: str, tmp_path: Path):
    path = tmp_path / f'{key}.xlsx'
    path.write_bytes(b'corrupt workbook')
    with pytest.raises(ValueError, match='hash|checksum'):
        if key == 'pop2026':
            read_pop2026(path)
        else:
            read_population_workbook(path, source_key=key)


def copy_arpen_cache(tmp_path: Path) -> tuple[Path, Path]:
    path = tmp_path / 'arpen2025' / 'responses.jsonl.gz'
    path.parent.mkdir(parents=True)
    path.write_bytes((DATA / 'sanitized' / 'arpen2025' / 'arpen2025_responses.jsonl.gz').read_bytes())
    return tmp_path, path


def rewrite_records(path: Path, records: list[dict[str, Any]]) -> None:
    raw = ('\n'.join(json.dumps(record, ensure_ascii=False, separators=(',', ':')) for record in records) + '\n').encode()
    path.write_bytes(gzip.compress(raw, mtime=0))


def read_records(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


@pytest.mark.parametrize('field', ['response_sha256', 'response_bytes'])
def test_cached_arpen_rejects_hash_and_byte_tampering(field: str, tmp_path: Path):
    cache, path = copy_arpen_cache(tmp_path)
    records = read_records(path)
    records[0][field] = '0' * 64 if field == 'response_sha256' else records[0][field] + 1
    rewrite_records(path, records)
    with pytest.raises(ValueError, match='hash|byte'):
        fetch_arpen2025(HttpClient(), cache)


def test_cached_arpen_rejects_duplicate_and_unexpected_endpoint(tmp_path: Path):
    cache, path = copy_arpen_cache(tmp_path)
    records = read_records(path)
    records.append(records[1])
    rewrite_records(path, records)
    with pytest.raises(ValueError, match='duplicate'):
        fetch_arpen2025(HttpClient(), cache)

    cache, path = copy_arpen_cache(tmp_path / 'unexpected')
    records = read_records(path)
    records[1]['endpoint'] = 'unexpected-name'
    rewrite_records(path, records)
    with pytest.raises(ValueError, match='unexpected'):
        fetch_arpen2025(HttpClient(), cache)


def test_shared_count_normalization_rejects_negative_and_empty_names():
    with pytest.raises(ValueError, match='negative'):
        build_module.normalise_counts([('MARIA', -1)])
    with pytest.raises(ValueError, match='empty name'):
        build_module.normalise_counts([('', 1)])


def test_arpen_rejects_empty_names_negative_births_and_duplicate_ufs():
    with pytest.raises(ValueError, match='empty name'):
        normalise_arpen({'data': [{'name': '', 'total': 1}]})
    with pytest.raises(ValueError, match='negative'):
        validate_births({'data': [{'name': 'AC', 'total': -1}]}, expected_ufs={'AC'})
    with pytest.raises(ValueError, match='duplicate UF'):
        validate_births({'data': [{'name': 'AC', 'total': 1}, {'name': 'AC', 'total': 1}]}, expected_ufs={'AC'})


def test_late_generation_failure_preserves_all_original_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / 'data'
    shutil.copytree(DATA, data)
    legacy = data / 'legacy_history.json'
    legacy.write_text('preserve me')
    candidates = [data / 'manifest.json', data / 'cities_with_ceps.json', data / 'locations_data.json', legacy]
    before = {path: path.read_bytes() for path in candidates}

    def fake_ibge(sqlite, output, sanitized, **kwargs):
        output.mkdir(parents=True, exist_ok=True)
        (output / 'partial-marker').write_text('partial')
        return {}

    def fake_arpen(client, cache, output, sanitized, **kwargs):
        output.mkdir(parents=True, exist_ok=True)
        (output / 'partial-marker').write_text('partial')
        return {}

    def fail_late(*args, **kwargs):
        args[2].write_text('partial geography')
        raise ValueError('late DOU failure')

    monkeypatch.setattr(build_module, 'build_ibge', fake_ibge)
    monkeypatch.setattr(build_module, 'build_arpen', fake_arpen)
    monkeypatch.setattr(build_module, 'rebuild_geography_files', fail_late)
    with pytest.raises(ValueError, match='late DOU'):
        build_module.build_all(data, CACHE)
    assert all(path.read_bytes() == content for path, content in before.items())
    assert not (data / 'parquet' / 'ibge2022' / 'partial-marker').exists()
    assert not (data / 'parquet' / 'arpen2025' / 'partial-marker').exists()


def test_derived_metadata_uses_real_acquisition_times():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    expected = json.loads((CACHE / 'ibge2022' / 'nomes.sqlite.zip.meta.json').read_text())['acquired_at_utc']
    assert manifest['sources']['ibge2022']['acquired_at_utc'] == expected
    sidecar = json.loads((DATA / 'parquet' / 'ibge2022' / 'first_names' / 'scope=national' / 'data_origin.json').read_text())
    assert sidecar['acquired_at_utc'] == expected
    assert manifest['sources']['pop2026']['acquired_at_utc'] != manifest['built_at_utc']


def test_sanitized_sqlite_cannot_be_downloaded_as_raw():
    key = next(source.key for source in SOURCE_REGISTRY if source.key == 'ibge2022_sqlite')

    class NoNetwork:
        def download(self, *args, **kwargs):
            raise AssertionError('must not download sanitized source directly')

    from ptbr_sampler.data_pipeline import cli

    # Construction does not perform I/O; download must never be called.
    original = cli.HttpClient
    cli.HttpClient = lambda: NoNetwork()
    try:
        result = CliRunner().invoke(cli.app, ['fetch', '--source', key, '--cache-dir', '/tmp/unused'])
    finally:
        cli.HttpClient = original
    assert result.exit_code == 2


def test_cep_end_fallback_uses_end_not_start():
    base = {
        'cities': {
            'Acrelândia_AC': {
                'city_name': 'Acrelândia',
                'city_uf': 'AC',
                'uf_code': '12',
                'city_code': '00013',
                'cep_range_begins': '69945-000',
                'cep_range_ends': '69949-999',
            }
        }
    }
    result = rebuild_geography(base, {1200013: 100}, national_population=100, state_names={'AC': 'Acre'})
    assert result['cities']['cities']['Acrelândia_AC']['cep_range_ends'] == '69949-999'
    assert result['cities']['cities']['Acrelândia_AC']['cep_ends'] == '69949-999'
    fallback = {'cities': {'Acrelândia_AC': {key: value for key, value in base['cities']['Acrelândia_AC'].items() if not key.startswith('cep_range_')}}}
    fallback['cities']['Acrelândia_AC'].update(cep_ends='69949-999', cep_starts='69945-000')
    result = rebuild_geography(fallback, {1200013: 100}, national_population=100, state_names={'AC': 'Acre'})
    assert result['cities']['cities']['Acrelândia_AC']['cep_range_ends'] == '69949-999'

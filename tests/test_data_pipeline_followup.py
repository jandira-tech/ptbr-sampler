"""Regression tests for the data-pipeline validation review findings."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ptbr_sampler.data_pipeline.geography import compare_population_tables
from ptbr_sampler.data_pipeline.http import HttpClient
from ptbr_sampler.data_pipeline.ibge import OFFICIAL_UF_ANCHOR_EVIDENCE, OFFICIAL_UF_ANCHORS, OfficialIBGEClient
from ptbr_sampler.data_pipeline.registry import Source
from ptbr_sampler.data_pipeline.validate import validate_runtime_data

ROOT = Path(__file__).parents[1]
DATA = ROOT / 'ptbr_sampler' / 'data'


def copy_data(tmp_path: Path) -> Path:
    destination = tmp_path / 'data'
    shutil.copytree(DATA, destination)
    return destination


def test_validate_reads_and_hashes_real_runtime_tree(tmp_path: Path):
    result = validate_runtime_data(copy_data(tmp_path))
    assert result['artifacts_verified'] == len(json.loads((DATA / 'manifest.json').read_text())['artifacts'])
    assert result['first_name_ufs'] == 27
    assert result['surname_ufs'] == 27
    assert result['arpen_births'] == 2_537_697
    assert result['cities'] == 5_570


def test_validate_detects_deleted_and_corrupt_artifacts(tmp_path: Path):
    data = copy_data(tmp_path)
    target = data / 'parquet' / 'ibge2022' / 'first_names' / 'uf=SP' / 'part.parquet'
    target.unlink()
    with pytest.raises(ValueError, match='missing artifact'):
        validate_runtime_data(data)

    data = copy_data(tmp_path / 'corrupt')
    target = data / 'parquet' / 'ibge2022' / 'first_names' / 'uf=SP' / 'part.parquet'
    target.write_bytes(b'not parquet')
    with pytest.raises(ValueError, match='hash mismatch'):
        validate_runtime_data(data)


def test_validate_rejects_unexpected_managed_file_and_bad_geography(tmp_path: Path):
    data = copy_data(tmp_path)
    (data / 'parquet' / 'ibge2022' / 'first_names' / 'uf=XX').mkdir()
    extra = data / 'parquet' / 'ibge2022' / 'first_names' / 'uf=XX' / 'part.parquet'
    shutil.copyfile(data / 'parquet' / 'ibge2022' / 'first_names' / 'uf=SP' / 'part.parquet', extra)
    with pytest.raises(ValueError, match='unexpected artifact'):
        validate_runtime_data(data)

    data = copy_data(tmp_path / 'geography')
    locations_path = data / 'locations_data.json'
    locations = json.loads(locations_path.read_text())
    next(iter(locations['states'].values()))['state_population'] = 1
    locations_path.write_text(json.dumps(locations))
    # Keep the inventory hashes honest so this exercises reconciliation, not only hashing.
    manifest_path = data / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    key = 'ptbr_sampler/data/locations_data.json'
    manifest['artifact_sha256'][key] = hashlib.sha256(locations_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='official UF|geography'):
        validate_runtime_data(data)


def source_for(payload: bytes) -> Source:
    return Source('test', 'raw', 'https://example.org/data.bin', 'data.bin', hashlib.sha256(payload).hexdigest(), len(payload), 'v1')


def test_download_rejects_http_before_network_or_file_creation(tmp_path: Path):
    requests = []
    source = Source('insecure', 'raw', 'http://example.org/data.bin', 'data.bin')

    def transport(request, timeout):
        requests.append(request.full_url)
        raise AssertionError('network must not be reached')

    with pytest.raises(ValueError, match='only HTTPS'):
        HttpClient(stream_transport=transport).download(source, tmp_path / 'data.bin')
    assert requests == []
    assert list(tmp_path.iterdir()) == []


def test_download_resumes_partial_file_with_range(tmp_path: Path):
    payload = b'abcdef'
    part = tmp_path / 'data.bin.part'
    part.write_bytes(payload[:3])
    ranges = []

    def transport(request, timeout):
        ranges.append(request.headers.get('Range'))
        assert request.headers['Range'] == 'bytes=3-'
        return {
            'status': 206,
            'headers': {'Content-Range': 'bytes 3-5/6'},
            'stream': io.BytesIO(payload[3:]),
        }

    metadata = HttpClient(stream_transport=transport, retries=0).download(source_for(payload), tmp_path / 'data.bin')
    assert (tmp_path / 'data.bin').read_bytes() == payload
    assert not part.exists()
    assert ranges == ['bytes=3-']
    assert metadata['resumed_from_bytes'] == 3


def test_download_safely_restarts_when_server_ignores_range(tmp_path: Path):
    payload = b'abcdef'
    part = tmp_path / 'data.bin.part'
    part.write_bytes(b'wrong-prefix')

    def transport(request, timeout):
        assert request.headers['Range'] == 'bytes=12-'
        return {'status': 200, 'headers': {}, 'stream': io.BytesIO(payload)}

    HttpClient(stream_transport=transport, retries=0).download(source_for(payload), tmp_path / 'data.bin')
    assert (tmp_path / 'data.bin').read_bytes() == payload


def valid_history(locality='35'):
    return [
        {
            'nome': 'maria',
            'localidade': locality,
            'res': [{'periodo': '1930[', 'frequencia': 10}, {'periodo': '[2020,2022[', 'frequencia': 20}],
        }
    ]


def test_name_history_accepts_and_validates_complete_schema():
    client = OfficialIBGEClient(transport=lambda *_: valid_history())
    assert client.name_history('maria', 'nome', 35) == valid_history()


@pytest.mark.parametrize(
    'mutate',
    [
        lambda row: row.pop('res'),
        lambda row: row['res'][0].update(periodo=None),
        lambda row: row['res'][0].update(frequencia=-1),
        lambda row: row.update(nome='jose'),
        lambda row: row.update(localidade='33'),
    ],
)
def test_name_history_rejects_malformed_schema_and_mismatched_scope(mutate):
    payload = valid_history()
    mutate(payload[0])
    with pytest.raises(ValueError, match='history|period|frequency|name|locality'):
        OfficialIBGEClient(transport=lambda *_: payload).name_history('maria', 'nome', 35)


def test_population_comparison_detects_codes_statuses_and_deltas():
    comparison = compare_population_tables({1: 100, 2: 200}, {1: 90, 3: 300})
    assert comparison['rows'] == {
        '1': {'status': 'changed', 'pop2026': 100, 'dou2026': 90, 'delta': 10},
        '2': {'status': 'added', 'pop2026': 200, 'dou2026': None, 'delta': 200},
        '3': {'status': 'removed', 'pop2026': None, 'dou2026': 300, 'delta': -300},
    }
    assert comparison['summary'] == {'added': 1, 'removed': 1, 'changed': 1, 'unchanged': 0}


def test_actual_geography_records_dou_comparison_and_official_uf_reconciliation():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    comparison = manifest['geography_comparison']
    assert comparison['source_url'].endswith('estimativa_dou_2026.xlsx')
    assert len(comparison['sha256']) == 64
    # Current corrected POP2026 and DOU files are identical municipality by
    # municipality; the synthetic test above proves additions/removals/deltas
    # are detected when they occur.
    assert comparison['summary'] == {'added': 0, 'removed': 0, 'changed': 0, 'unchanged': 5_571}
    assert comparison['national_population_delta'] == 0
    assert all(row['status'] == 'unchanged' and row['delta'] == 0 for row in comparison['rows'].values())
    reconciliation = manifest['geography_reconciliation']
    assert len(reconciliation) == 27
    assert sum(row['official_population'] for row in reconciliation.values()) == 214_211_951
    assert reconciliation['MT']['unmatched_source_population'] == 5_983
    assert all(row['delta'] == row['joined_population'] - row['official_population'] for row in reconciliation.values())
    locations = json.loads((DATA / 'locations_data.json').read_text())
    assert sum(state['state_population'] for state in locations['states'].values()) == 214_211_951
    assert locations['states']['Mato Grosso']['state_population'] == reconciliation['MT']['official_population']


def test_published_uf_anchors_are_specific_and_independently_sourced():
    assert OFFICIAL_UF_ANCHORS[('SP', 'nome', 'maria')] == 2_131_207
    assert OFFICIAL_UF_ANCHORS[('SP', 'sobrenome', 'silva')] == 5_928_587
    assert OFFICIAL_UF_ANCHORS[('AC', 'nome', 'maria')] == 72_420
    evidence = OFFICIAL_UF_ANCHOR_EVIDENCE[('SP', 'nome', 'maria')]
    assert 'agenciasp.sp.gov.br' in evidence
    for key, expected in OFFICIAL_UF_ANCHORS.items():
        uf, kind, name = key
        directory = 'first_names' if kind == 'nome' else 'surnames'
        rows = pq.read_table(DATA / 'parquet' / 'ibge2022' / directory / f'uf={uf}' / 'part.parquet', columns=['name', 'count']).to_pylist()
        assert next(row['count'] for row in rows if row['name'] == name) == expected


def test_geography_json_files_are_part_of_exact_inventory():
    manifest = json.loads((DATA / 'manifest.json').read_text())
    for name in ('cities_with_ceps.json', 'locations_data.json'):
        key = f'ptbr_sampler/data/{name}'
        assert key in manifest['artifacts']
        assert manifest['artifact_sha256'][key] == hashlib.sha256((DATA / name).read_bytes()).hexdigest()

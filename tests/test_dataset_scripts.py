"""Contributor scripts under ``scripts/`` degrade gracefully on odd inputs."""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import classify_unmatched_names_gemini as classify
from scripts import download_datasets
from tests.test_dataset_audit import _write_minimal_2022_fixture


def test_second_names_report_tolerates_missing_percentage(tmp_path: Path):
    path = tmp_path / 'middle_names.json'
    path.write_text(json.dumps({'second_names': {'MARIA': {}}}), encoding='utf-8')

    assert download_datasets._validate_json_shape(path) == 'second_names: 1 rows; percentage_with_second=n/a'


def test_second_names_report_formats_numeric_percentage(tmp_path: Path):
    path = tmp_path / 'middle_names.json'
    path.write_text(json.dumps({'second_names': {}, 'percentage_with_second': 30.99}), encoding='utf-8')

    assert download_datasets._validate_json_shape(path) == 'second_names: 0 rows; percentage_with_second=30.9900%'


@pytest.fixture
def tiny_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Four names, one covered by genero-nomes, one in the shipped Gemini file."""
    names = tmp_path / 'names_data.json'
    names.write_text(
        json.dumps({'common_names_percentage': {'ate2010': {'names': {'ANA': 1, 'BIA': 1, 'CAU': 1, 'DUDA': 1}}}}),
        encoding='utf-8',
    )
    genero = tmp_path / 'nomes.csv'
    genero.write_text('first_name,classification\nANA,F\n', encoding='utf-8')
    canonical = tmp_path / 'canonical.jsonl'
    canonical.write_text(json.dumps({'name': 'BIA', 'gender': 'F'}) + '\n', encoding='utf-8')
    monkeypatch.setattr(classify, '_NAMES_DATA_JSON', names)
    monkeypatch.setattr(classify, '_GENERO_NOMES_CSV', genero)
    monkeypatch.setattr(classify, '_GEMINI_JSONL', canonical)
    return tmp_path


def test_unmatched_names_skip_the_shipped_classifications_for_a_fresh_output(tiny_corpus: Path):
    assert classify.compute_unmatched_names(tiny_corpus / 'fresh.jsonl') == ['CAU', 'DUDA']


def test_unmatched_names_resume_from_the_given_output(tiny_corpus: Path):
    output = tiny_corpus / 'run.jsonl'
    output.write_text(json.dumps({'name': 'CAU', 'gender': 'M'}) + '\n', encoding='utf-8')

    assert classify.compute_unmatched_names(output) == ['DUDA']
    assert classify.compute_unmatched_names(output, limit=0) == []


def test_existing_classifications_skip_non_object_lines(tmp_path: Path):
    path = tmp_path / 'c.jsonl'
    path.write_text(
        '["MARIA"]\n{"name": 123, "gender": "F"}\n{"name": "BIA", "gender": 1}\n{"name": "ana", "gender": "f"}\n', encoding='utf-8'
    )

    assert classify._load_existing_classifications(path) == {'ANA': 'F'}


def test_dry_run_accepts_an_output_outside_the_repository(tmp_path: Path, capsys):
    output = tmp_path / 'elsewhere.jsonl'

    assert classify.main(['--dry-run', '--limit', '1', '--output', str(output)]) == 0
    assert f'Output: {output.resolve()}' in capsys.readouterr().out


def test_dataset_requests_refuse_anything_but_https():
    with pytest.raises(ValueError, match='non-HTTPS'):
        download_datasets._https_request('file:///etc/passwd', 'ua')
    assert download_datasets._https_request('https://example.org/x', 'ua').full_url == 'https://example.org/x'


def test_second_names_report_rejects_boolean_percentage(tmp_path: Path):
    path = tmp_path / 'middle_names.json'
    path.write_text(json.dumps({'second_names': {}, 'percentage_with_second': True}), encoding='utf-8')

    assert download_datasets._validate_json_shape(path).endswith('percentage_with_second=n/a')


def test_fetch_ibge_2022_verifies_sha256_and_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = b'PAR1mockparquetbytesPAR1'
    digest = hashlib.sha256(payload).hexdigest()
    spec = download_datasets.PinnedParquetSpec(
        filename='state.parquet',
        sha256=digest,
        size_bytes=len(payload),
        expected_rows=1,
        required_columns=('code', 'abbreviation', 'population'),
    )
    seen_urls: list[str] = []

    def _capture_stream(url: str, dest: Path, **kw) -> None:
        seen_urls.append(url)
        dest.write_bytes(payload)

    monkeypatch.setattr(download_datasets, 'IBGE_2022_FILES', (spec,))
    monkeypatch.setattr(download_datasets, '_validate_parquet_schema_and_rows', lambda path, s: 1)
    monkeypatch.setattr(download_datasets, '_stream_https_bytes', _capture_stream)

    manifest_path = download_datasets.fetch_ibge_2022(out_dir=tmp_path)
    assert seen_urls == [
        f'https://huggingface.co/datasets/{download_datasets.IBGE_2022_REPO}/resolve/{download_datasets.IBGE_2022_REVISION}/parquet/state.parquet'
    ]
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['revision'] == download_datasets.IBGE_2022_REVISION
    assert manifest['files']['state.parquet']['sha256'] == digest
    assert 'fetched_at_utc' in manifest['files']['state.parquet']


def test_fetch_ibge_2022_rejects_checksum_mismatch_and_leaves_no_partial_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = download_datasets.PinnedParquetSpec(
        filename='state.parquet',
        sha256='0' * 64,
        size_bytes=4,
        expected_rows=1,
        required_columns=('code',),
    )
    monkeypatch.setattr(download_datasets, 'IBGE_2022_FILES', (spec,))
    monkeypatch.setattr(download_datasets, '_stream_https_bytes', lambda url, dest, **kw: dest.write_bytes(b'bad!'))

    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        download_datasets.fetch_ibge_2022(out_dir=tmp_path)
    assert not (tmp_path / 'state.parquet').exists()
    assert not list(tmp_path.glob('*.part'))


def test_fetch_ibge_2022_reuses_valid_cache_and_replaces_corrupt_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    good = b'valid-parquet-bytes'
    digest = hashlib.sha256(good).hexdigest()
    spec = download_datasets.PinnedParquetSpec('state.parquet', digest, len(good), 1, ('code',))
    monkeypatch.setattr(download_datasets, 'IBGE_2022_FILES', (spec,))
    monkeypatch.setattr(download_datasets, '_validate_parquet_schema_and_rows', lambda path, s: 1)

    calls = 0

    def fake_stream(url: str, dest: Path, **kw: object) -> None:
        nonlocal calls
        calls += 1
        dest.write_bytes(good)

    monkeypatch.setattr(download_datasets, '_stream_https_bytes', fake_stream)

    # Corrupt existing file must be detected and refetched automatically
    (tmp_path / 'state.parquet').write_bytes(b'corrupted')
    download_datasets.fetch_ibge_2022(out_dir=tmp_path, overwrite=False)
    assert calls == 1

    # Second call with valid file on disk skips network completely
    download_datasets.fetch_ibge_2022(out_dir=tmp_path, overwrite=False)
    assert calls == 1


def test_retry_helper_retries_429_and_503_but_fails_fast_on_404():
    attempts = 0

    def transient_then_ok() -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.HTTPError('https://huggingface.co/x', 503, 'Service Unavailable', hdrs=None, fp=None)
        return b'ok'

    assert download_datasets._with_bounded_retries(transient_then_ok, max_attempts=3, base_sleep=0.0) == b'ok'
    assert attempts == 3

    attempts_429 = 0

    def transient_429_then_ok() -> bytes:
        nonlocal attempts_429
        attempts_429 += 1
        if attempts_429 < 2:
            raise urllib.error.HTTPError('https://huggingface.co/x', 429, 'Too Many Requests', hdrs=None, fp=None)
        return b'ok'

    assert download_datasets._with_bounded_retries(transient_429_then_ok, max_attempts=3, base_sleep=0.0) == b'ok'
    assert attempts_429 == 2

    def permanent_404() -> bytes:
        raise urllib.error.HTTPError('https://huggingface.co/x', 404, 'Not Found', hdrs=None, fp=None)

    with pytest.raises(urllib.error.HTTPError):
        download_datasets._with_bounded_retries(permanent_404, max_attempts=3, base_sleep=0.0)


def test_redirect_handler_blocks_disallowed_hosts():
    download_datasets._assert_allowed_https_url('https://huggingface.co/datasets/x/resolve/main/y.parquet')
    download_datasets._assert_allowed_https_url('https://cas-bridge.xethub.hf.co/xet-bridge-us/abc')
    with pytest.raises(RuntimeError, match='Blocked redirect or fetch'):
        download_datasets._assert_allowed_https_url('http://huggingface.co/datasets/x')
    with pytest.raises(RuntimeError, match='Blocked redirect or fetch'):
        download_datasets._assert_allowed_https_url('https://evil.example.com/payload.parquet')

    handler = download_datasets._AllowedRedirectHandler()
    req = urllib.request.Request('https://huggingface.co/datasets/x')
    with pytest.raises(RuntimeError, match='Blocked redirect or fetch'):
        handler.redirect_request(req, None, 302, 'Found', {}, 'https://evil.example.com/steal')


def test_merge_sex_prior_never_fabricates_unit_counts_for_gemini(tmp_path: Path):
    from scripts import ingest_to_parquet

    csv_path = tmp_path / 'nomes.csv'
    csv_path.write_text(
        'first_name,frequency_male,frequency_female,frequency_total,ratio,classification,alternative_names\nANA,10,990,1000,0.99,F,\n',
        encoding='utf-8',
    )
    gemini_path = tmp_path / 'classifications.jsonl'
    gemini_path.write_text(
        '{"name": "ZORBLAX", "gender": "M", "model": "gemini-test"}\n{"name": "ZORBLINA", "gender": "F", "model": "gemini-test"}\n',
        encoding='utf-8',
    )

    merged, counts = ingest_to_parquet._merge_sex_prior(csv_path, gemini_path)
    assert counts['gemini_M'] == 1
    assert counts['gemini_F'] == 1
    assert merged['ZORBLAX']['count_male'] == 0
    assert merged['ZORBLAX']['count_female'] == 0
    assert merged['ZORBLAX']['count_total'] == 0
    assert merged['ZORBLAX']['p_male'] == 1.0
    assert merged['ZORBLINA']['count_male'] == 0
    assert merged['ZORBLINA']['count_female'] == 0
    assert merged['ZORBLINA']['count_total'] == 0
    assert merged['ZORBLINA']['p_female'] == 1.0


def test_ingest_ibge_2022_writes_float64_partitions_and_nullable_sex_prior(tmp_path: Path):
    from scripts import ingest_to_parquet

    raw_dir = tmp_path / 'raw_2022'
    raw_dir.mkdir()
    _write_minimal_2022_fixture(raw_dir)
    # Provide all 10 decade cohorts so CENSUS_2022_DECADE_TO_PERIOD is exercised end-to-end
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria'] * 10,
                'name_type': ['given'] * 10,
                'decade': [1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020],
                'frequency': [100] * 10,
            }
        ),
        raw_dir / 'name_by_decade.parquet',
    )
    out_root = tmp_path / 'parquet'
    audit = ingest_to_parquet.ingest_ibge_2022(raw_dir, out_root)
    assert audit['given_rows'] == 4

    nat_given = pq.read_table(out_root / 'census_year=2022' / 'first_names' / 'scope=national' / 'part.parquet')
    assert nat_given.schema.field('weight').type == pa.float64()
    assert math.isclose(math.fsum(nat_given['weight'].to_pylist()), 1.0, rel_tol=0.0, abs_tol=1e-15)

    sex_prior = pq.read_table(out_root / 'census_year=2022' / 'sex_prior' / 'scope=national' / 'part.parquet')
    rows_by_key = {r['canonical_key']: r for r in sex_prior.to_pylist()}

    # 'maria': total=100, male=20, female=80 -> both_observed
    maria = rows_by_key['maria']
    assert maria['censoring_regime'] == 'both_observed'
    assert math.isclose(maria['p_male'], 0.2) and math.isclose(maria['p_female'], 0.8)

    # 'ana': total=60, male=None, female=60 -> one_null_exact_zero
    ana = rows_by_key['ana']
    assert ana['censoring_regime'] == 'one_null_exact_zero'
    assert math.isclose(ana['p_male'], 0.0) and math.isclose(ana['p_female'], 1.0)

    # 'anna': total=25, male=None, female=20 -> one_null_suppressed_positive: p_female=0.8, p_male=NaN
    anna = rows_by_key['anna']
    assert anna['censoring_regime'] == 'one_null_suppressed_positive'
    assert anna['count_male'] is None
    assert anna['residual_unassigned'] == 5
    assert math.isclose(anna['p_female'], 0.8)
    assert math.isnan(anna['p_male'])

    # 'ariel': total=24, male=None, female=None -> both_null_suppressed: both NaN
    ariel = rows_by_key['ariel']
    assert ariel['censoring_regime'] == 'both_null_suppressed'
    assert math.isnan(ariel['p_male']) and math.isnan(ariel['p_female'])

    assert not (out_root / '.tmp_census_year=2022').exists()
    assert not (out_root / '.bak_census_year=2022').exists()


def test_cli_scripts_reject_path_traversal_and_outside_workspace_paths(tmp_path: Path):
    from scripts import audit_datasets, ingest_to_parquet, publish_hf_dataset

    traversal = str(tmp_path / '..' / 'escape')
    outside = '/etc'

    for bad_path in (traversal, outside, 'bad\x00path'):
        with pytest.raises(ValueError, match='CLI path|Parent-directory|repository or temp'):
            audit_datasets.main(['--raw-dir', bad_path])
        with pytest.raises(ValueError, match='CLI path|Parent-directory|repository or temp'):
            ingest_to_parquet.main(['--data-dir', bad_path, '--out', str(tmp_path / 'out')])
        with pytest.raises(ValueError, match='CLI path|Parent-directory|repository or temp'):
            ingest_to_parquet.ingest_ibge_2022(Path(bad_path), tmp_path / 'out')
        with pytest.raises(ValueError, match='CLI path|Parent-directory|repository or temp'):
            publish_hf_dataset.main(['--data-dir', bad_path, '--manifest-only'])
        with pytest.raises(ValueError, match='CLI path|Parent-directory|repository or temp'):
            publish_hf_dataset.write_dataset_manifest(Path(bad_path))


def test_publish_hf_dataset_rejects_malformed_repo_id_and_revision(tmp_path: Path):
    from scripts import publish_hf_dataset

    for bad_repo in ('../evil/repo', 'evil/../repo', 'no-namespace', 'org/repo/extra', 'org/bad\x00repo'):
        with pytest.raises(ValueError, match='repo_id'):
            publish_hf_dataset.main(['--data-dir', str(tmp_path), '--repo-id', bad_repo, '--manifest-only'])
        with pytest.raises(ValueError, match='repo_id'):
            publish_hf_dataset.publish_to_huggingface(tmp_path, repo_id=bad_repo)

    for bad_rev in ('../evil', 'rev/slash', 'bad\x00rev', ''):
        with pytest.raises(ValueError, match='revision'):
            publish_hf_dataset.main(['--data-dir', str(tmp_path), '--revision', bad_rev, '--manifest-only'])

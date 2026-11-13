"""Tests for runtime Hugging Face dataset resolution, caching, SHA-256 verification, and manifest publishing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import ptbr_sampler
from ptbr_sampler import datasets as ds_mod
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore
from scripts import publish_hf_dataset


def _write_mini_parquet(path: Path, names: list[str], counts: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tot = float(sum(counts))
    pq.write_table(
        pa.table(
            {
                'name': pa.array(names, type=pa.string()),
                'count': pa.array(counts, type=pa.int64()),
                'weight': pa.array([c / tot for c in counts], type=pa.float64()),
            }
        ),
        path,
        compression='zstd',
    )


def test_package_version_is_0_3_0():
    assert ptbr_sampler.__version__ == '0.3.0'


def test_publish_manifest_builder_collects_runtime_artifacts_and_excludes_raw_and_backups(tmp_path: Path):
    data_dir = tmp_path / 'data'
    _write_mini_parquet(
        data_dir / 'parquet' / 'census_year=2022' / 'first_names' / 'scope=national' / 'part.parquet',
        ['Maria', 'Joao'],
        [60, 40],
    )
    (data_dir / 'middle_names.json').write_text('{"common_middle_names": ["Maria"]}\n', encoding='utf-8')
    (data_dir / 'raw' / 'ibge_nomes_2022').mkdir(parents=True)
    (data_dir / 'raw' / 'ibge_nomes_2022' / 'state.parquet').write_bytes(b'ignored')
    (data_dir / 'locations_data.bak.json').write_text('{}', encoding='utf-8')

    manifest_path = publish_hf_dataset.write_dataset_manifest(
        data_dir,
        repo_id='arthrod/ptbr-sampler-data',
        revision='a' * 40,
    )
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['package_version'] == '0.3.0'
    assert manifest['hf_repo_id'] == 'arthrod/ptbr-sampler-data'
    assert manifest['hf_revision'] == 'a' * 40
    assert 'parquet/census_year=2022/first_names/scope=national/part.parquet' in manifest['artifacts']
    assert 'middle_names.json' in manifest['artifacts']
    assert not any(k.startswith('raw/') or '.bak' in k for k in manifest['artifacts'])


def test_ensure_data_file_downloads_lazily_verifies_sha256_and_reuses_cache_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    remote_root = tmp_path / 'remote'
    rel = 'parquet/census_year=2022/first_names/scope=national/part.parquet'
    src_file = remote_root / rel
    _write_mini_parquet(src_file, ['Maria', 'Ana'], [70, 30])
    payload = src_file.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    rev = 'b' * 40

    manifest_file = tmp_path / 'dataset_manifest.json'
    manifest_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'package_version': '0.3.0',
                'hf_repo_id': 'arthrod/ptbr-sampler-data',
                'hf_revision': rev,
                'artifacts': {
                    rel: {'sha256': digest, 'size_bytes': len(payload), 'census_years': [2022]},
                },
            }
        ),
        encoding='utf-8',
    )

    request_count = 0
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal request_count
            expected_path = f'/datasets/arthrod/ptbr-sampler-data/resolve/{rev}/{rel}'
            if self.path != expected_path:
                self.send_response(404)
                self.end_headers()
                return
            with lock:
                request_count += 1
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cache_dir = tmp_path / 'cache'
        monkeypatch.setattr(ds_mod, 'MANIFEST_PATH', manifest_file)
        ds_mod.load_dataset_manifest.cache_clear()
        monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(cache_dir))
        monkeypatch.setenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', '1')
        monkeypatch.setenv('PTBR_SAMPLER_HF_BASE_URL', f'http://127.0.0.1:{server.server_port}')

        # Concurrent cold downloads must serialize on the advisory lock and hit HTTP once:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: ds_mod.ensure_data_file(rel), range(6)))

        assert all(p == results[0] and p.is_file() for p in results)
        assert request_count == 1

        # PartitionStore with resolve_partition_path loads lazily from the cache root:
        store = PartitionStore(path_resolver=ds_mod.resolve_partition_path)
        p_root = ds_mod.ensure_parquet_root(census_year=2022)
        table = store.get(PartitionSpec.of(p_root / 'first_names', scope='national'))
        assert list(table.labels) == ['Maria', 'Ana']
        assert table.counts is not None and list(table.counts) == [70, 30]
        assert request_count == 1
    finally:
        server.shutdown()
        ds_mod.load_dataset_manifest.cache_clear()


def test_ensure_data_file_rejects_sha256_mismatch_and_offline_cache_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rel = 'middle_names.json'
    rev = 'c' * 40
    manifest_file = tmp_path / 'dataset_manifest.json'
    manifest_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'package_version': '0.3.0',
                'hf_repo_id': 'arthrod/ptbr-sampler-data',
                'hf_revision': rev,
                'artifacts': {
                    rel: {'sha256': '0' * 64, 'size_bytes': 12, 'census_years': [2010, 2022]},
                },
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(ds_mod, 'MANIFEST_PATH', manifest_file)
    ds_mod.load_dataset_manifest.cache_clear()
    monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', '1')

    monkeypatch.setenv('PTBR_SAMPLER_OFFLINE', '1')
    with pytest.raises(RuntimeError, match='PTBR_SAMPLER_OFFLINE=1'):
        ds_mod.ensure_data_file(rel)

    monkeypatch.delenv('PTBR_SAMPLER_OFFLINE')
    monkeypatch.setattr(
        ds_mod,
        '_download_url_to_part',
        lambda url, part_path, **kw: (part_path.write_bytes(b'tampered1234'), 'f' * 64, 12)[1:],
    )
    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        ds_mod.ensure_data_file(rel)
    ds_mod.load_dataset_manifest.cache_clear()


def test_redirect_handler_strips_authorization_header_on_cross_origin_cdn_redirect():
    handler = ds_mod._CrossOriginSafeRedirectHandler(allow_loopback_http=False)
    req = urllib.request.Request(
        'https://huggingface.co/datasets/arthrod/ptbr-sampler-data/resolve/main/middle_names.json',
        headers={'Authorization': 'Bearer hf_secret_token', 'User-Agent': 'ptbr-sampler/0.3.0'},
    )
    redirected = handler.redirect_request(
        req,
        fp=None,
        code=302,
        msg='Found',
        headers={},
        newurl='https://cas-bridge.xethub.hf.co/xet-bridge-us/signed-blob',
    )
    assert redirected is not None
    assert not redirected.has_header('Authorization')
    assert 'authorization' not in {k.lower() for k in redirected.unredirected_hdrs}


def test_normalize_relpath_blocks_traversal():
    with pytest.raises(ValueError, match='traversal'):
        ds_mod._normalize_relpath('../secrets.json')
    with pytest.raises(ValueError, match='Invalid'):
        ds_mod._normalize_relpath('/etc/passwd')


def test_bundled_manifest_pins_immutable_40_char_hf_revision():
    import re

    ds_mod.load_dataset_manifest.cache_clear()
    manifest = ds_mod.load_dataset_manifest()
    assert manifest.hf_repo_id == 'arthrod/ptbr-sampler-data'
    assert manifest.package_version == '0.3.0'
    assert re.fullmatch(r'[0-9a-f]{40}', manifest.hf_revision)
    assert len(manifest.artifacts) == 195


def test_resolve_partition_path_and_cli_status_reject_corrupt_cache_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import hashlib

    from typer.testing import CliRunner

    from ptbr_sampler.cli import app

    rel = 'parquet/census_year=2022/first_names/scope=national/part.parquet'
    good_bytes = b'PAR1goodcontentPAR1'
    good_sha = hashlib.sha256(good_bytes).hexdigest()
    rev = 'd' * 40
    manifest_file = tmp_path / 'dataset_manifest.json'
    manifest_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'package_version': '0.3.0',
                'hf_repo_id': 'arthrod/ptbr-sampler-data',
                'hf_revision': rev,
                'artifacts': {
                    rel: {'sha256': good_sha, 'size_bytes': len(good_bytes), 'census_years': [2022]},
                },
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(ds_mod, 'MANIFEST_PATH', manifest_file)
    monkeypatch.setattr(ds_mod, 'PACKAGE_DATA_DIR', tmp_path / 'empty_pkg_data')
    ds_mod.load_dataset_manifest.cache_clear()
    monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.delenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', raising=False)
    monkeypatch.delenv('PTBR_SAMPLER_DATA_DIR', raising=False)

    corrupt_cache_file = ds_mod.get_revision_cache_dir() / rel
    corrupt_cache_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_cache_file.write_bytes(b'truncated')

    # 1. Offline resolve_partition_path must NOT silently return the truncated cache file
    monkeypatch.setenv('PTBR_SAMPLER_OFFLINE', '1')
    with pytest.raises(RuntimeError, match='PTBR_SAMPLER_OFFLINE=1'):
        ds_mod.resolve_partition_path(corrupt_cache_file)

    # 2. Same-size SHA-tampered cache file must report INVALID via `ptbr datasets status --verify` without KeyError
    corrupt_cache_file.write_bytes(b'X' * len(good_bytes))
    res = CliRunner().invoke(app, ['datasets', 'status', '--verify'])
    assert res.exit_code == 1
    assert f'INVALID: {rel}' in (res.stdout + getattr(res, 'stderr', '') or res.output)
    ds_mod.load_dataset_manifest.cache_clear()


def test_data_dir_override_offline_true_sha256_and_census_year_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from typer.testing import CliRunner

    from ptbr_sampler.cli import app

    rel = 'parquet/census_year=2022/first_names/scope=national/part.parquet'
    good_bytes = b'PAR1validoverridePAR1'
    good_sha = hashlib.sha256(good_bytes).hexdigest()
    rev = 'e' * 40
    manifest_file = tmp_path / 'dataset_manifest.json'
    manifest_file.write_text(
        json.dumps(
            {
                'schema_version': 1,
                'package_version': '0.3.0',
                'hf_repo_id': 'arthrod/ptbr-sampler-data',
                'hf_revision': rev,
                'artifacts': {
                    rel: {'sha256': good_sha, 'size_bytes': len(good_bytes), 'census_years': [2022]},
                },
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(ds_mod, 'MANIFEST_PATH', manifest_file)
    monkeypatch.setattr(ds_mod, 'PACKAGE_DATA_DIR', tmp_path / 'empty_pkg_data')
    ds_mod.load_dataset_manifest.cache_clear()
    monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', '1')

    # 1. PTBR_SAMPLER_OFFLINE=true (documented boolean literal) blocks uncached network downloads
    monkeypatch.setenv('PTBR_SAMPLER_OFFLINE', 'true')
    assert ds_mod.has_runtime_data_available(census_year=2022) is False
    with pytest.raises(RuntimeError, match='PTBR_SAMPLER_OFFLINE'):
        ds_mod.ensure_data_file(rel)

    # 2. PTBR_SAMPLER_DATA_DIR satisfies offline availability, reports local-override, and honors verify_sha256
    override_dir = tmp_path / 'override_data'
    override_file = override_dir / rel
    override_file.parent.mkdir(parents=True, exist_ok=True)
    override_file.write_bytes(good_bytes)
    monkeypatch.setenv('PTBR_SAMPLER_DATA_DIR', str(override_dir))

    assert ds_mod.has_runtime_data_available(census_year=2022) is True
    status_ok = ds_mod.dataset_cache_status(census_year=2022, verify_sha256=True)
    assert status_ok['artifacts'][0]['state'] == 'local-override'
    assert status_ok['artifacts'][0]['valid'] is True

    # Tamper override file: verify_sha256=True must detect SHA-256 mismatch
    override_file.write_bytes(b'Z' * len(good_bytes))
    status_bad = ds_mod.dataset_cache_status(census_year=2022, verify_sha256=True)
    assert status_bad['artifacts'][0]['valid'] is False
    with pytest.raises(RuntimeError, match='SHA-256 mismatch'):
        ds_mod.ensure_data_file(rel, verify_sha256=True)

    # 3. Invalid census_year values must fail fast rather than silently matching 0 artifacts
    with pytest.raises(ValueError, match='census_year'):
        ds_mod.prefetch_datasets(census_year=2024)
    with pytest.raises(ValueError, match='census_year'):
        ds_mod.dataset_cache_status(census_year=2024)
    res_src = CliRunner().invoke(app, ['sources', '--census-year', '2024'])
    assert res_src.exit_code == 1

    # 4. Path/query injection in PTBR_SAMPLER_HF_REPO is rejected
    monkeypatch.delenv('PTBR_SAMPLER_DATA_DIR')
    monkeypatch.delenv('PTBR_SAMPLER_OFFLINE')
    monkeypatch.setenv('PTBR_SAMPLER_HF_REPO', 'evil/repo/../../other?x=1')
    ds_mod.load_dataset_manifest.cache_clear()
    with pytest.raises(ValueError, match='hf_repo_id'):
        ds_mod.load_dataset_manifest()
    ds_mod.load_dataset_manifest.cache_clear()

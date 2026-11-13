"""Catalogue of bundled data origins and the ``ptbr sources`` command."""

from __future__ import annotations

import subprocess
import sys

import pytest

from ptbr_sampler.data_origins import DATA_ORIGINS, DataOrigin, by_kind


class TestCatalogue:
    def test_has_primary_entries(self):
        kinds = {o.kind for o in DATA_ORIGINS}
        assert 'First names (Census 2022)' in kinds
        assert 'Surnames (Census 2022)' in kinds
        assert 'First names' in kinds
        assert 'Surnames' in kinds
        assert 'Middle names' in kinds
        assert 'States (UFs)' in kinds
        assert 'Cities' in kinds

    def test_by_kind_matches_tuple_length_and_filters_by_census_year(self):
        assert len(by_kind()) == len(DATA_ORIGINS)
        only_2022 = by_kind(census_year=2022)
        assert 'First names (Census 2022)' in only_2022
        assert 'First names' not in only_2022
        only_2010 = by_kind(census_year=2010)
        assert 'First names' in only_2010
        assert 'First names (Census 2022)' not in only_2010

    def test_bundled_or_manifest_files_exist_even_in_slim_wheel_mode(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        # Every DataOrigin that lists files/remote_artifacts must resolve both in checkout and in cold slim-wheel mode.
        missing: list[str] = []
        for origin in DATA_ORIGINS:
            for path, exists in origin.file_status():
                if not exists:
                    missing.append(f'{origin.kind}: {path}')
        assert not missing, f'Missing bundled files: {missing}'

        monkeypatch.setenv('PTBR_SAMPLER_IGNORE_LOCAL_DATA', '1')
        monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(tmp_path / 'empty_cache'))
        for origin in DATA_ORIGINS:
            for rel, state in origin.artifact_states():
                assert state == 'remote-hf', (origin.kind, rel, state)
            for path, exists in origin.file_status():
                assert exists, (origin.kind, path)

    def test_primary_url_is_https_where_present(self):
        for origin in DATA_ORIGINS:
            if origin.primary_url:
                assert origin.primary_url.startswith(('http://', 'https://')), f'{origin.kind}: {origin.primary_url!r}'

    def test_dataorigin_is_frozen(self):
        origin = DATA_ORIGINS[0]
        with pytest.raises((AttributeError, TypeError)):
            origin.kind = 'mutated'  # type: ignore[misc]


class TestSourcesCommand:
    def test_sources_lists_all_kinds(self):
        run = subprocess.run(
            [sys.executable, '-m', 'ptbr_sampler', 'sources'],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr
        for origin in DATA_ORIGINS:
            assert origin.kind in run.stdout

    def test_sources_filter_by_kind(self):
        run = subprocess.run(
            [sys.executable, '-m', 'ptbr_sampler', 'sources', '--kind', 'middle'],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr
        assert 'Middle names' in run.stdout
        assert 'First names' not in run.stdout

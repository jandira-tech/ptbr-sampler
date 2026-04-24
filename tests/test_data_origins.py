"""Catalogue of bundled data origins and the ``ptbr sources`` command."""

from __future__ import annotations

import subprocess
import sys

import pytest

from ptbr_sampler.data_origins import DATA_ORIGINS, DataOrigin, by_kind


class TestCatalogue:
    def test_has_primary_entries(self):
        kinds = {o.kind for o in DATA_ORIGINS}
        assert 'First names' in kinds
        assert 'Surnames' in kinds
        assert 'Middle names' in kinds
        assert 'States (UFs)' in kinds
        assert 'Cities' in kinds

    def test_by_kind_matches_tuple_length(self):
        assert len(by_kind()) == len(DATA_ORIGINS)

    def test_bundled_files_exist(self):
        # Every DataOrigin that lists files must point at real paths.
        missing: list[str] = []
        for origin in DATA_ORIGINS:
            for path, exists in origin.file_status():
                if not exists:
                    missing.append(f'{origin.kind}: {path}')
        assert not missing, f'Missing bundled files: {missing}'

    def test_primary_url_is_https_where_present(self):
        for origin in DATA_ORIGINS:
            if origin.primary_url:
                assert origin.primary_url.startswith(('http://', 'https://')), (
                    f'{origin.kind}: {origin.primary_url!r}'
                )

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

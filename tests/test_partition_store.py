"""Partitioned Parquet store and ingestion script."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts import ingest_to_parquet
from src.sampling.alias import AliasTable
from src.sampling.store import PartitionSpec, PartitionStore


_TINY_NAMES = {
    'common_names_percentage': {
        'ate2010': {
            'names': {
                'Maria': {'percentage': 0.4, 'count': 40},
                'João': {'percentage': 0.3, 'count': 30},
                'Ana': {'percentage': 0.2, 'count': 20},
                # Included so the middle-name filter whitelist knows about them.
                'Clara': {'percentage': 0.05, 'count': 5},
                'Miguel': {'percentage': 0.05, 'count': 5},
            },
            'total': 100,
        }
    }
}

_TINY_SURNAMES = {
    'surnames': {
        'Silva': {'percentage': 0.6, 'count': 60},
        'Santos': {'percentage': 0.4, 'count': 40},
        'top_40': {'Silva': {'percentage': 0.5, 'count': 1}},
    }
}

_TINY_MIDDLES = {
    'total_people': 100,
    'total_with_second_names': 30,
    'unique_second_names': 2,
    'percentage_with_second': 30.0,
    'second_names': {
        'Clara': {'count': 20, 'percentage': 20.0},
        'Miguel': {'count': 10, 'percentage': 10.0},
        # Contamination that must be stripped by the vocabulary filter.
        'Silva': {'count': 5, 'percentage': 5.0},
        '-': {'count': 1, 'percentage': 0.5},
    },
}

_TINY_LOCATIONS = {
    'states': {
        'São Paulo': {'state_abbr': 'SP', 'state_population': 46_000_000, 'population_percentage': 0.22},
        'Minas Gerais': {'state_abbr': 'MG', 'state_population': 21_000_000, 'population_percentage': 0.10},
    }
}


@pytest.fixture
def tiny_data_dir(tmp_path: Path) -> Path:
    (tmp_path / 'names_data.json').write_text(
        json.dumps(_TINY_NAMES), encoding='utf-8'
    )
    (tmp_path / 'surnames_data.json').write_text(
        json.dumps(_TINY_SURNAMES), encoding='utf-8'
    )
    (tmp_path / 'middle_names.json').write_text(
        json.dumps(_TINY_MIDDLES), encoding='utf-8'
    )
    (tmp_path / 'locations_data.json').write_text(
        json.dumps(_TINY_LOCATIONS), encoding='utf-8'
    )
    return tmp_path


class TestPartitionSpec:
    def test_path_layout(self, tmp_path: Path):
        spec = PartitionSpec.of(tmp_path / 'first_names', period='ate2010')
        assert spec.path() == tmp_path / 'first_names' / 'period=ate2010' / 'part.parquet'

    def test_multi_key(self, tmp_path: Path):
        spec = PartitionSpec.of(tmp_path / 'first_names', uf='SP', decade='1990', sex='F')
        assert spec.path() == (
            tmp_path / 'first_names' / 'uf=SP' / 'decade=1990' / 'sex=F' / 'part.parquet'
        )

    def test_key_stable_for_equal_specs(self, tmp_path: Path):
        a = PartitionSpec.of(tmp_path, uf='SP', decade='1990')
        b = PartitionSpec.of(tmp_path, uf='SP', decade='1990')
        assert a.key() == b.key()


class TestIngestion:
    def test_round_trip(self, tiny_data_dir: Path, tmp_path: Path):
        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])

        # First names
        fn_spec = PartitionSpec.of(out / 'first_names', period='ate2010')
        assert fn_spec.path().exists()

        # Surnames
        sn_spec = PartitionSpec.of(out / 'surnames', scope='national')
        assert sn_spec.path().exists()

        # Middle names at root (no partition keys)
        mn_path = out / 'middle_names' / 'part.parquet'
        assert mn_path.exists()

        # States
        st_path = out / 'states' / 'part.parquet'
        assert st_path.exists()

    def test_middle_names_filter_strips_surname(self, tiny_data_dir: Path, tmp_path: Path):
        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])
        import pyarrow.parquet as pq

        mn = pq.read_table(out / 'middle_names' / 'part.parquet').to_pydict()
        kept = set(mn['name'])
        assert 'Clara' in kept
        assert 'Miguel' in kept
        # Contamination must be rejected by the whitelist.
        assert 'Silva' not in kept
        assert '-' not in kept

    def test_skip_filter_flag_keeps_contamination(
        self, tiny_data_dir: Path, tmp_path: Path
    ):
        out = tmp_path / 'parquet'
        ingest_to_parquet.main(
            [
                '--data-dir',
                str(tiny_data_dir),
                '--out',
                str(out),
                '--skip-middle-names-filter',
            ]
        )
        import pyarrow.parquet as pq

        mn = pq.read_table(out / 'middle_names' / 'part.parquet').to_pydict()
        kept = set(mn['name'])
        assert 'Silva' in kept  # not filtered out


class TestPartitionStore:
    def test_load_round_trip(self, tiny_data_dir: Path, tmp_path: Path):
        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])

        store = PartitionStore(max_entries=2)
        spec = PartitionSpec.of(out / 'first_names', period='ate2010')
        table = store.get(spec)
        assert isinstance(table, AliasTable)
        labels = {str(s) for s in table.labels}
        assert {'Maria', 'João', 'Ana'}.issubset(labels)

    def test_lru_eviction(self, tiny_data_dir: Path, tmp_path: Path):
        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])

        store = PartitionStore(max_entries=1)
        store.get(PartitionSpec.of(out / 'first_names', period='ate2010'))
        store.get(PartitionSpec.of(out / 'surnames', scope='national'))
        assert len(store) == 1

    def test_missing_partition_raises(self, tmp_path: Path):
        store = PartitionStore()
        spec = PartitionSpec.of(tmp_path / 'nonexistent', uf='ZZ')
        with pytest.raises(FileNotFoundError):
            store.get(spec)

    def test_sample_from_loaded_table(self, tiny_data_dir: Path, tmp_path: Path):
        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])

        store = PartitionStore()
        table = store.get(PartitionSpec.of(out / 'surnames', scope='national'))
        rng = np.random.default_rng(7)
        draws = table.sample(10_000, rng)
        frac_silva = (draws == 'Silva').sum() / len(draws)
        # Built-in surname weights should dominate (~60%).
        assert 0.55 < frac_silva < 0.65

    def test_register_and_contains(self):
        store = PartitionStore(max_entries=2)
        spec = PartitionSpec.of('x', uf='SP')
        t = AliasTable.from_counts(['a', 'b'], [1, 2])
        store.register(spec, t)
        assert spec in store
        assert len(store) == 1
        store.clear()
        assert spec not in store

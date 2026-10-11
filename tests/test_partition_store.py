"""Partitioned Parquet store and ingestion script."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ptbr_sampler.br_name_class import TimePeriod
from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore
from scripts import ingest_to_parquet

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
    (tmp_path / 'names_data.json').write_text(json.dumps(_TINY_NAMES), encoding='utf-8')
    (tmp_path / 'surnames_data.json').write_text(json.dumps(_TINY_SURNAMES), encoding='utf-8')
    (tmp_path / 'middle_names.json').write_text(json.dumps(_TINY_MIDDLES), encoding='utf-8')
    (tmp_path / 'locations_data.json').write_text(json.dumps(_TINY_LOCATIONS), encoding='utf-8')
    return tmp_path


class TestPartitionSpec:
    def test_path_layout(self, tmp_path: Path):
        spec = PartitionSpec.of(tmp_path / 'first_names', period='ate2010')
        assert spec.path() == tmp_path / 'first_names' / 'period=ate2010' / 'part.parquet'

    def test_multi_key(self, tmp_path: Path):
        spec = PartitionSpec.of(tmp_path / 'first_names', uf='SP', decade='1990', sex='F')
        assert spec.path() == (tmp_path / 'first_names' / 'uf=SP' / 'decade=1990' / 'sex=F' / 'part.parquet')

    def test_key_stable_for_equal_specs(self, tmp_path: Path):
        a = PartitionSpec.of(tmp_path, uf='SP', decade='1990')
        b = PartitionSpec.of(tmp_path, uf='SP', decade='1990')
        assert a.key() == b.key()


class TestIngestion:
    def test_normalise_accepts_iterators(self):
        assert ingest_to_parquet._normalise(iter([1.0, 2.0, 3.0])) == pytest.approx([1 / 6, 2 / 6, 3 / 6])

    def test_main_defaults_are_module_relative(self, monkeypatch: pytest.MonkeyPatch, tiny_data_dir: Path, tmp_path: Path):
        out = tmp_path / 'parquet'
        original_parse = ingest_to_parquet.argparse.ArgumentParser.parse_args

        def parse_args(self, args=None, namespace=None):
            parsed = original_parse(self, [], namespace)
            assert parsed.data_dir.is_absolute()
            assert parsed.out.is_absolute()
            assert parsed.out == parsed.data_dir / 'parquet'
            return original_parse(self, ['--data-dir', str(tiny_data_dir), '--out', str(out)], namespace)

        monkeypatch.setattr(ingest_to_parquet.argparse.ArgumentParser, 'parse_args', parse_args)
        ingest_to_parquet.main([])

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

    def test_skip_filter_flag_keeps_contamination(self, tiny_data_dir: Path, tmp_path: Path):
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

    def test_partition_with_no_count_or_weight_raises(self, tmp_path: Path):
        """A partition file lacking both count and weight columns must raise."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        spec = PartitionSpec.of(tmp_path / 'orphan', uf='SP')
        spec.path().parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({'name': ['a', 'b', 'c']}), spec.path())

        store = PartitionStore()
        with pytest.raises(ValueError, match='neither positive counts nor weight column'):
            store.get(spec)

    def test_uf_sex_partition_round_trip_and_ingest(self, tmp_path: Path):
        """Synthetic IBGE Nomes v2 raw → ingest → conditioned partition.

        Verifies the full chain: raw JSON written by the downloader is
        consumed by ``ingest_first_names_uf_sex`` and produces a
        ``first_names/uf=<UF>/period=<P>/sex=<S>/part.parquet`` file with
        the right labels.
        """
        raw_root = tmp_path / 'raw' / 'ibge_nomes_v2'
        out = tmp_path / 'parquet'
        target = raw_root / 'uf=SP' / 'period=ate2010' / 'sex=F.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    'uf': 'SP',
                    'localidade': '35',
                    'sexo': 'F',
                    'decada': 2010,
                    'period': 'ate2010',
                    'res': [
                        {'nome': 'MARIA', 'frequencia': 1000, 'ranking': 1},
                        {'nome': 'ANA', 'frequencia': 500, 'ranking': 2},
                    ],
                },
            ),
            encoding='utf-8',
        )

        stats = ingest_to_parquet.ingest_first_names_uf_sex(raw_root, out)
        assert stats == {('SP', 'ate2010', 'F'): 2}

        spec = PartitionSpec.of(
            out / 'first_names',
            uf='SP',
            period='ate2010',
            sex='F',
        )
        assert spec.path().exists()

        store = PartitionStore()
        table = store.get(spec)
        labels = {str(s) for s in table.labels}
        assert labels == {'MARIA', 'ANA'}

    def test_uf_sex_ingest_skips_when_raw_missing(self, tmp_path: Path):
        """No raw → no partitions, no error."""
        out = tmp_path / 'parquet'
        stats = ingest_to_parquet.ingest_first_names_uf_sex(tmp_path / 'absent', out)
        assert stats == {}

    def test_name_sampler_uses_uf_sex_partition_when_present(self, tmp_path: Path):
        """When (uf, period, sex) partition exists, the conditioned draw uses it."""
        # Build a tiny but full payload that satisfies ``_validate_data``.
        tiny_full_names = {
            'common_names_percentage': {
                p.value: {
                    'names': {
                        'PeriodFallback': {'percentage': 1.0, 'count': 1},
                    },
                    'total': 1,
                }
                for p in TimePeriod
            }
        }
        tiny_data_dir = tmp_path / 'data'
        tiny_data_dir.mkdir()
        (tiny_data_dir / 'names_data.json').write_text(json.dumps(tiny_full_names), encoding='utf-8')
        (tiny_data_dir / 'surnames_data.json').write_text(json.dumps(_TINY_SURNAMES), encoding='utf-8')
        (tiny_data_dir / 'middle_names.json').write_text(json.dumps(_TINY_MIDDLES), encoding='utf-8')
        (tiny_data_dir / 'locations_data.json').write_text(json.dumps(_TINY_LOCATIONS), encoding='utf-8')

        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])

        # Drop a synthetic UF / sex partition with a distinctive label that
        # cannot collide with the period-only fallback table.
        raw_root = tiny_data_dir / 'raw' / 'ibge_nomes_v2'
        target = raw_root / 'uf=SP' / 'period=ate2010' / 'sex=F.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    'uf': 'SP', 'localidade': '35', 'sexo': 'F',
                    'decada': 2010, 'period': 'ate2010',
                    'res': [
                        {'nome': 'CONDITIONED_ONLY_NAME', 'frequencia': 999, 'ranking': 1},
                    ],
                },
            ),
            encoding='utf-8',
        )
        ingest_to_parquet.ingest_first_names_uf_sex(raw_root, out)

        from ptbr_sampler.br_name_class import BrazilianNameSampler

        combined = {**tiny_full_names, 'surnames': _TINY_SURNAMES['surnames']}
        sampler = BrazilianNameSampler(
            combined,
            middle_names_path=tiny_data_dir / 'middle_names.json',
            parquet_root=out,
        )
        # Conditioned draw — must hit the synthetic label.
        comps = sampler.batch_sample_names(
            5,
            time_period=TimePeriod.UNTIL_2010,
            ufs=['SP'] * 5,
            sexes=['F'] * 5,
        )
        for c in comps:
            assert c.first_name == 'CONDITIONED_ONLY_NAME'

        # Unconditioned draw — must NOT hit the synthetic label (only the
        # period-only ``PeriodFallback`` is valid).
        comps_default = sampler.batch_sample_names(5, time_period=TimePeriod.UNTIL_2010)
        for c in comps_default:
            assert c.first_name == 'PeriodFallback'

    def test_name_sampler_uf_sex_falls_back_when_partition_absent(self, tmp_path: Path):
        """Asking for a (uf, sex) without a partition silently falls back."""
        tiny_full_names = {
            'common_names_percentage': {
                p.value: {
                    'names': {'PeriodFallback': {'percentage': 1.0, 'count': 1}},
                    'total': 1,
                }
                for p in TimePeriod
            }
        }
        tiny_data_dir = tmp_path / 'data'
        tiny_data_dir.mkdir()
        (tiny_data_dir / 'names_data.json').write_text(json.dumps(tiny_full_names), encoding='utf-8')
        (tiny_data_dir / 'surnames_data.json').write_text(json.dumps(_TINY_SURNAMES), encoding='utf-8')
        (tiny_data_dir / 'middle_names.json').write_text(json.dumps(_TINY_MIDDLES), encoding='utf-8')
        (tiny_data_dir / 'locations_data.json').write_text(json.dumps(_TINY_LOCATIONS), encoding='utf-8')

        out = tmp_path / 'parquet'
        ingest_to_parquet.main(['--data-dir', str(tiny_data_dir), '--out', str(out)])

        from ptbr_sampler.br_name_class import BrazilianNameSampler

        combined = {**tiny_full_names, 'surnames': _TINY_SURNAMES['surnames']}
        sampler = BrazilianNameSampler(
            combined,
            middle_names_path=tiny_data_dir / 'middle_names.json',
            parquet_root=out,
        )
        # Asking for a UF without a partition must fall back to the period table.
        comps = sampler.batch_sample_names(
            5,
            time_period=TimePeriod.UNTIL_2010,
            ufs=['ZZ'] * 5,  # no partition for ZZ — must fall back
            sexes=['F'] * 5,
        )
        for c in comps:
            assert c.first_name == 'PeriodFallback'

    def test_partition_with_only_weight_column_loads(self, tmp_path: Path):
        """A partition file with only weight (no count) is loaded via from_weights."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        spec = PartitionSpec.of(tmp_path / 'weighted', uf='SP')
        spec.path().parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table({'name': ['a', 'b'], 'weight': [0.7, 0.3]}),
            spec.path(),
        )

        store = PartitionStore()
        table = store.get(spec)
        assert set(str(s) for s in table.labels) == {'a', 'b'}


def _write_uf_raw(raw_root: Path, res: list) -> None:
    target = raw_root / 'uf=SP' / 'period=ate2010' / 'sex=F.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'uf': 'SP', 'res': res}), encoding='utf-8')


def test_uf_sex_ingest_writes_origin_sidecar(tmp_path: Path):
    """UF x period x sex partitions carry ``data_origin.json`` like every other partition."""
    raw_root = tmp_path / 'raw'
    out = tmp_path / 'parquet'
    _write_uf_raw(raw_root, [{'nome': 'MARIA', 'frequencia': 1000, 'ranking': 1}])

    ingest_to_parquet.ingest_first_names_uf_sex(raw_root, out)

    sidecar = out / 'first_names' / 'uf=SP' / 'period=ate2010' / 'sex=F' / 'data_origin.json'
    origin = json.loads(sidecar.read_text(encoding='utf-8'))
    assert origin['rows'] == 1
    assert origin['partition'] == 'first_names/uf=SP/period=ate2010/sex=F'
    assert 'IBGE Nomes API v2' in origin['source']


def test_uf_sex_ingest_skips_malformed_rows(tmp_path: Path):
    """A non-object entry in ``res`` is skipped, not an AttributeError."""
    raw_root = tmp_path / 'raw'
    out = tmp_path / 'parquet'
    _write_uf_raw(raw_root, ['MARIA', None, {'nome': 'ANA', 'frequencia': 500, 'ranking': 2}])

    stats = ingest_to_parquet.ingest_first_names_uf_sex(raw_root, out)

    assert stats == {('SP', 'ate2010', 'F'): 1}

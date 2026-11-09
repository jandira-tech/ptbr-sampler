"""Additional tests for code added/changed in this PR.

Covers gaps not addressed by the existing test suite:

* ``alias.py`` — draw(k=0), AliasTable.__len__, build_alias single element
* ``store.py`` — alias_from_mapping, PartitionStore(max_entries<1), cache-hit path
* ``br_name_class.py`` — _rng_from_python_random, parquet_root paths,
  _top_40_table empty fallback, _load_from_parquet(store=None),
  _middle_names_table ValueError, from_bundled_parquet
* ``data_origins.py`` — by_kind content, notes field, file_status tuples
* ``__main__.py`` — entry point is importable and callable
* ``__init__.py`` — __version__ format, re-export correctness
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# alias.py
# ---------------------------------------------------------------------------
from ptbr_sampler.sampling.alias import AliasTable, build_alias, draw


class TestDrawEdgeCases:
    def test_draw_k_zero_returns_empty(self):
        prob, alias = build_alias(np.array([1.0, 2.0, 3.0]))
        rng = np.random.default_rng(0)
        out = draw(prob, alias, 0, rng)
        assert out.shape == (0,)

    def test_draw_k_one_returns_valid_index(self):
        prob, alias = build_alias(np.array([1.0, 9.0]))
        rng = np.random.default_rng(0)
        out = draw(prob, alias, 1, rng)
        assert out.shape == (1,)
        assert out[0] in (0, 1)


class TestBuildAliasSingleElement:
    def test_single_element_prob_is_one(self):
        prob, alias = build_alias(np.array([42.0]))
        assert prob.shape == (1,)
        assert prob[0] == pytest.approx(1.0)
        assert alias[0] == 0

    def test_single_element_draw_always_returns_zero(self):
        prob, alias = build_alias(np.array([1.0]))
        rng = np.random.default_rng(0)
        out = draw(prob, alias, 100, rng)
        assert np.all(out == 0)


class TestAliasTableLen:
    def test_len_from_counts(self):
        t = AliasTable.from_counts(['a', 'b', 'c'], [1, 2, 3])
        assert len(t) == 3

    def test_len_from_weights(self):
        t = AliasTable.from_weights(['x', 'y', 'z', 'w'], [0.1, 0.2, 0.3, 0.4])
        assert len(t) == 4

    def test_len_single(self):
        t = AliasTable.from_counts(['only'], [10])
        assert len(t) == 1

    def test_sample_k_zero_empty(self):
        t = AliasTable.from_counts(['a', 'b'], [1, 1])
        rng = np.random.default_rng(0)
        out = t.sample(0, rng)
        assert len(out) == 0


class TestAliasTableFromWeightsEdge:
    def test_from_weights_empty_rejected(self):
        with pytest.raises(ValueError):
            AliasTable.from_weights([], [])

    def test_from_weights_normalises(self):
        """Weights don't need to sum to 1; they're normalised internally."""
        t = AliasTable.from_weights(['a', 'b'], [3.0, 7.0])
        assert t.weights.sum() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# store.py — alias_from_mapping
# ---------------------------------------------------------------------------

from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore, alias_from_mapping


class TestAliasFromMapping:
    def test_basic_mapping_with_counts(self):
        mapping = {
            'Silva': {'count': 60, 'percentage': 60.0},
            'Santos': {'count': 40, 'percentage': 40.0},
        }
        t = alias_from_mapping(mapping)
        assert isinstance(t, AliasTable)
        assert len(t) == 2
        assert set(t.labels.tolist()) == {'Silva', 'Santos'}

    def test_fallback_to_weights_when_no_counts(self):
        """When all counts are missing, falls back to percentage weights."""
        mapping = {
            'Maria': {'percentage': 70.0},
            'João': {'percentage': 30.0},
        }
        t = alias_from_mapping(mapping)
        assert isinstance(t, AliasTable)
        assert len(t) == 2

    def test_count_only_entries_are_kept(self):
        """Count-only fixtures should use counts rather than being discarded."""
        mapping = {
            'A': {'count': 3},
            'B': {'count': 1},
        }
        t = alias_from_mapping(mapping)
        labels = t.labels.tolist()
        assert set(labels) == {'A', 'B'}
        assert t.weights[labels.index('A')] == pytest.approx(0.75)

    def test_skips_non_positive_entries(self):
        """Entries with percentage ≤ 0 are silently filtered out."""
        mapping = {
            'Good': {'count': 10, 'percentage': 50.0},
            'Zero': {'count': 0, 'percentage': 0.0},
            'Negative': {'count': 5, 'percentage': -1.0},
        }
        t = alias_from_mapping(mapping)
        assert len(t) == 1
        assert t.labels[0] == 'Good'

    def test_skips_non_mapping_values(self):
        """Values that aren't dicts are ignored."""
        mapping = {
            'top_40': {'Silva': 1},  # nested non-conforming dict — no 'percentage'
            'Valid': {'count': 5, 'percentage': 5.0},
        }
        t = alias_from_mapping(mapping)
        assert len(t) == 1
        assert t.labels[0] == 'Valid'

    def test_empty_mapping_raises(self):
        with pytest.raises(ValueError, match='no positive-weight entries'):
            alias_from_mapping({})

    def test_all_nonpositive_raises(self):
        with pytest.raises(ValueError, match='no positive-weight entries'):
            alias_from_mapping({'Zero': {'count': 0, 'percentage': 0.0}})

    def test_invalid_percentage_treated_as_zero(self):
        """Non-numeric percentage falls back to 0.0 and gets filtered."""
        mapping = {
            'Bad': {'count': 1, 'percentage': 'not-a-number'},
            'Good': {'count': 2, 'percentage': 2.0},
        }
        t = alias_from_mapping(mapping)
        assert len(t) == 1
        assert t.labels[0] == 'Good'

    def test_mixed_counts_some_missing(self):
        """When any count is None, have_counts=False and weights path is used."""
        mapping = {
            'A': {'percentage': 60.0},  # no count
            'B': {'count': 40, 'percentage': 40.0},
        }
        t = alias_from_mapping(mapping)
        assert isinstance(t, AliasTable)
        assert set(t.labels.tolist()) == {'A', 'B'}

    def test_counts_take_priority_when_available(self):
        """When counts are present, from_counts is used (not from_weights)."""
        mapping = {
            'X': {'count': 100, 'percentage': 33.3},
            'Y': {'count': 200, 'percentage': 66.7},
        }
        t = alias_from_mapping(mapping)
        # X has count 100, Y has 200 — Y should appear ~2x as often
        rng = np.random.default_rng(42)
        draws = t.sample(10_000, rng)
        frac_y = (draws == 'Y').sum() / len(draws)
        assert 0.60 < frac_y < 0.73

    def test_string_label_coercion(self):
        """Labels are coerced to str via str(), even for non-string keys."""
        mapping = {123: {'count': 1, 'percentage': 1.0}}
        t = alias_from_mapping(mapping)
        assert t.labels[0] == '123'

    def test_skips_non_mapping_top_level_value(self):
        """Top-level non-Mapping values must be skipped, not raise."""
        mapping = {
            'NotADict': 'just-a-string',
            'Good': {'count': 1, 'percentage': 1.0},
        }
        t = alias_from_mapping(mapping)
        assert len(t) == 1
        assert t.labels[0] == 'Good'

    def test_invalid_count_treated_as_zero(self):
        """Non-numeric count falls back to 0 and the entry is filtered when pct also zero."""
        mapping = {
            'Bad': {'count': 'not-a-number', 'percentage': 0.0},
            'Good': {'count': 2, 'percentage': 2.0},
        }
        t = alias_from_mapping(mapping)
        assert len(t) == 1
        assert t.labels[0] == 'Good'


# ---------------------------------------------------------------------------
# store.py — PartitionStore constructor validation and cache-hit path
# ---------------------------------------------------------------------------


class TestPartitionStoreConstructor:
    def test_max_entries_zero_raises(self):
        with pytest.raises(ValueError, match='max_entries must be >= 1'):
            PartitionStore(max_entries=0)

    def test_max_entries_negative_raises(self):
        with pytest.raises(ValueError, match='max_entries must be >= 1'):
            PartitionStore(max_entries=-5)

    def test_default_max_entries_is_64(self):
        """Default max is 64; registering 65 entries should evict the oldest."""
        store = PartitionStore()
        assert len(store) == 0
        t = AliasTable.from_counts(['a'], [1])
        for i in range(65):
            store.register(PartitionSpec.of('root', slot=str(i)), t)
        assert len(store) == 64
        # The first-registered slot should have been evicted; the most recent kept.
        assert PartitionSpec.of('root', slot='0') not in store
        assert PartitionSpec.of('root', slot='64') in store


class TestPartitionStoreCacheHit:
    def test_get_same_spec_twice_hits_cache(self):
        """Second get() should return the same AliasTable object (cache hit)."""
        store = PartitionStore(max_entries=4)
        spec = PartitionSpec.of('x', scope='national')
        t = AliasTable.from_counts(['a', 'b'], [1, 2])
        store.register(spec, t)
        # First get — should be a cache hit since we just registered it
        retrieved1 = store.get(spec)
        retrieved2 = store.get(spec)
        assert retrieved1 is retrieved2

    def test_lru_moves_to_end_on_hit(self):
        """Accessing an older entry should save it from eviction."""
        store = PartitionStore(max_entries=2)
        spec_a = PartitionSpec.of('root', uf='SP')
        spec_b = PartitionSpec.of('root', uf='RJ')
        spec_c = PartitionSpec.of('root', uf='MG')
        t = AliasTable.from_counts(['a'], [1])
        store.register(spec_a, t)
        store.register(spec_b, t)
        # Access spec_a to move it to end
        store.get(spec_a)
        # Adding spec_c should evict spec_b (LRU), not spec_a
        store.register(spec_c, t)
        assert spec_a in store
        assert spec_c in store
        assert spec_b not in store

    def test_contains_false_for_missing(self):
        store = PartitionStore()
        spec = PartitionSpec.of('nonexistent', uf='XX')
        assert spec not in store


class TestPartitionSpecNoFilters:
    def test_empty_filters_path(self, tmp_path: Path):
        """PartitionSpec with no filters produces root/part.parquet."""
        spec = PartitionSpec(root=tmp_path / 'middle_names', filters=())
        assert spec.path() == tmp_path / 'middle_names' / 'part.parquet'

    def test_key_with_empty_filters(self, tmp_path: Path):
        spec = PartitionSpec(root=tmp_path, filters=())
        key = spec.key()
        assert key[1] == ()

    def test_key_different_roots_differ(self, tmp_path: Path):
        a = PartitionSpec(root=tmp_path / 'a', filters=())
        b = PartitionSpec(root=tmp_path / 'b', filters=())
        assert a.key() != b.key()


# ---------------------------------------------------------------------------
# br_name_class.py — new code paths
# ---------------------------------------------------------------------------

from ptbr_sampler.br_name_class import (
    BrazilianNameSampler,
    NameComponents,
    TimePeriod,
    _rng_from_python_random,
)


class TestRngFromPythonRandom:
    def test_returns_numpy_generator(self):
        rng = _rng_from_python_random()
        assert isinstance(rng, np.random.Generator)

    def test_seeding_stdlib_gives_deterministic_rng(self):
        """Seeding Python random makes _rng_from_python_random deterministic."""
        random.seed(42)
        rng1 = _rng_from_python_random()
        val1 = rng1.integers(0, 1_000_000)
        random.seed(42)
        rng2 = _rng_from_python_random()
        val2 = rng2.integers(0, 1_000_000)
        assert val1 == val2

    def test_different_seeds_different_rng(self):
        random.seed(1)
        rng1 = _rng_from_python_random()
        state1 = rng1.bit_generator.state
        random.seed(999_999)
        rng2 = _rng_from_python_random()
        state2 = rng2.bit_generator.state
        assert state1 != state2
        assert rng1.integers(0, 1_000_000_000, size=4).tolist() == [
            895069318,
            244188278,
            820748351,
            865373596,
        ]
        assert rng2.integers(0, 1_000_000_000, size=4).tolist() == [
            56876053,
            101195532,
            175984529,
            616105012,
        ]


def _minimal_name_data() -> dict:
    """Re-usable minimal name data matching conftest.mock_name_data structure."""
    return {
        'common_names_percentage': {
            period.value: {
                'names': {
                    'Maria': {'percentage': 0.5},
                    'João': {'percentage': 0.5},
                },
                'total': 100,
            }
            for period in TimePeriod
        },
        'surnames': {
            'Silva': {'percentage': 0.6},
            'Santos': {'percentage': 0.4},
            'top_40': {
                'Silva': {'percentage': 0.5},
                'Santos': {'percentage': 0.5},
            },
        },
    }


class TestBrazilianNameSamplerParquetRoot:
    def test_nonexistent_parquet_root_silently_ignored(self, tmp_path: Path):
        """When parquet_root doesn't exist, sampler falls back to JSON only."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, parquet_root=tmp_path / 'does_not_exist')
        # parquet_root should be None (not set) since dir doesn't exist
        assert sampler.parquet_root is None
        assert sampler._partition_store is None

    def test_existing_parquet_root_wires_store(self, tmp_path: Path):
        """When parquet_root exists, the store is created."""
        data = _minimal_name_data()
        # Create the directory so it exists
        parquet_dir = tmp_path / 'parquet'
        parquet_dir.mkdir()
        sampler = BrazilianNameSampler(data, parquet_root=parquet_dir)
        assert sampler.parquet_root == parquet_dir
        assert sampler._partition_store is not None

    def test_parquet_root_none_disables_store(self):
        """Explicitly passing parquet_root=None disables Parquet entirely."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, parquet_root=None)
        assert sampler.parquet_root is None
        assert sampler._partition_store is None

    def test_sampler_works_without_parquet(self):
        """A sampler with no Parquet root still generates valid names."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, parquet_root=None)
        random.seed(0)
        name = sampler.get_random_name()
        assert isinstance(name, str)
        assert len(name) > 0


class TestLoadFromParquetStorePath:
    def test_load_from_parquet_no_store_returns_none(self):
        """_load_from_parquet with no store returns None without raising."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, parquet_root=None)
        # _partition_store is None, so _load_from_parquet should return None
        spec = PartitionSpec.of('x', period='ate2010')
        result = sampler._load_from_parquet(spec)
        assert result is None

    def test_load_from_parquet_missing_partition_returns_none(self, tmp_path: Path):
        """If store exists but partition file is missing, returns None."""
        data = _minimal_name_data()
        parquet_dir = tmp_path / 'parquet'
        parquet_dir.mkdir()
        sampler = BrazilianNameSampler(data, parquet_root=parquet_dir)
        spec = PartitionSpec.of(parquet_dir / 'first_names', period='ate1930')
        result = sampler._load_from_parquet(spec)
        assert result is None

    def test_load_from_parquet_missing_pyarrow_falls_back(self):
        class MissingPyarrowStore:
            def get(self, spec: PartitionSpec) -> AliasTable:
                raise RuntimeError('pyarrow is required to load partitions; install pyarrow')

        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, parquet_root=None)
        sampler._partition_store = MissingPyarrowStore()
        assert sampler._load_from_parquet(PartitionSpec.of('x', period='ate2010')) is None

    def test_load_from_parquet_reraises_unrelated_runtime_error(self):
        class BrokenStore:
            def get(self, spec: PartitionSpec) -> AliasTable:
                raise RuntimeError('boom')

        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, parquet_root=None)
        sampler._partition_store = BrokenStore()
        with pytest.raises(RuntimeError, match='boom'):
            sampler._load_from_parquet(PartitionSpec.of('x', period='ate2010'))


class TestTop40FallbackToSurnames:
    def test_empty_top_40_falls_back_to_full_surnames(self):
        """When top_40_surnames is empty, _top_40_table returns full surname table."""
        data = _minimal_name_data()
        data['surnames']['top_40'] = {}  # empty top_40
        sampler = BrazilianNameSampler(data)
        table = sampler._top_40_table()
        # Should be the full surnames table, not an empty table
        assert len(table) >= 2

    def test_top_40_with_entries_uses_top_40(self):
        """When top_40 has entries, _top_40_table uses those entries."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        table = sampler._top_40_table()
        # mock data top_40 has Silva and Santos
        labels = set(table.labels.tolist())
        assert labels == {'Silva', 'Santos'}

    def test_top_40_table_cached_on_second_call(self):
        """The top_40 table is cached — second call returns the same object."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        t1 = sampler._top_40_table()
        t2 = sampler._top_40_table()
        assert t1 is t2


class TestShouldAddMiddleName:
    def test_returns_false_without_data(self):
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        assert sampler._should_add_middle_name() is False

    def test_returns_bool_with_data(self, tmp_path: Path):
        payload = {
            'percentage_with_second': 100.0,
            'second_names': {
                'Augusto': {'count': 1, 'percentage': 100.0},
            },
        }
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(payload), encoding='utf-8')
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, middle_names_path=mp)
        # 100% probability — should always be True.
        assert sampler._should_add_middle_name() is True


class TestGetRandomMiddleName:
    def test_no_middle_data_returns_empty(self):
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        assert sampler._get_random_middle_name() == ''

    def test_with_data_returns_string(self, tmp_path: Path):
        payload = {
            'percentage_with_second': 100.0,
            'second_names': {
                'Augusto': {'count': 1, 'percentage': 100.0},
            },
        }
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(payload), encoding='utf-8')
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, middle_names_path=mp)
        result = sampler._get_random_middle_name()
        assert result == 'Augusto'

    def test_table_none_returns_empty(self):
        """
        Verify _get_random_middle_name yields no middle name when the middle-name alias table cannot be built.
        
        Asserts that when configured second names have no positive weights, calling _get_random_middle_name() produces an empty result.
        """
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        sampler.middle_names_data = {
            'percentage_with_second': 100.0,
            'second_names': {
                'Zero': {'count': 0, 'percentage': 0.0},
            },
        }
        assert sampler._get_random_middle_name() == ''

    def test_get_random_middle_name_wraps_loader_errors(self, monkeypatch):
        """A loader error (KeyError/ValueError/TypeError) is wrapped in ValueError."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        sampler.middle_names_data = {
            'percentage_with_second': 100.0,
            'second_names': {'Augusto': {'count': 1, 'percentage': 100.0}},
        }

        def boom(self):  # noqa: ARG001 - signature must match the bound method
            """
            Always raises a TypeError with the message 'oops'.
            
            Raises:
                TypeError: Always raised with message 'oops'.
            """
            raise TypeError('oops')

        monkeypatch.setattr(BrazilianNameSampler, '_middle_names_table', boom)
        with pytest.raises(ValueError, match='Error processing middle names data'):
            sampler._get_random_middle_name()


class TestMiddleNamesTableEdge:
    def test_middle_names_table_returns_none_when_no_data(self):
        """Without middle_names_data, _middle_names_table returns None."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        assert sampler._middle_names_table() is None

    def test_middle_names_table_returns_none_on_empty_second_names(self):
        """If second_names has no positive-weight entries, returns None."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        sampler.middle_names_data = {
            'percentage_with_second': 50.0,
            'second_names': {
                'Zero': {'count': 0, 'percentage': 0.0},
            },
        }
        result = sampler._middle_names_table()
        assert result is None

    def test_middle_names_table_cached_on_second_call(self, tmp_path: Path):
        """The table is cached — second call returns the same object."""
        payload = {
            'percentage_with_second': 100.0,
            'second_names': {
                'Augusto': {'count': 10, 'percentage': 60.0},
                'Henrique': {'count': 5, 'percentage': 40.0},
            },
        }
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(payload), encoding='utf-8')
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data, middle_names_path=mp)
        t1 = sampler._middle_names_table()
        t2 = sampler._middle_names_table()
        assert t1 is not None
        assert isinstance(t1, AliasTable)
        assert t1 is t2


class TestFirstNamesTableLazy:
    def test_first_names_table_cached(self):
        """Building the alias table twice for the same period returns same object."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        t1 = sampler._first_names_table(TimePeriod.UNTIL_2010)
        t2 = sampler._first_names_table(TimePeriod.UNTIL_2010)
        assert t1 is t2

    def test_first_names_table_different_periods_different_objects(self):
        """Different periods produce independently cached tables."""
        data = _minimal_name_data()
        data['common_names_percentage'][TimePeriod.UNTIL_1930.value]['names'] = {
            'Antônio': {'percentage': 1.0},
        }
        sampler = BrazilianNameSampler(data)
        t1 = sampler._first_names_table(TimePeriod.UNTIL_1930)
        t2 = sampler._first_names_table(TimePeriod.UNTIL_2010)
        # Both are AliasTable instances but different objects (different cache keys)
        assert isinstance(t1, AliasTable)
        assert isinstance(t2, AliasTable)
        assert t1 is not t2
        assert t1.labels.tolist() != t2.labels.tolist()

    def test_surnames_table_cached(self):
        """_surnames_table returns the same object on repeated calls."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        t1 = sampler._surnames_table()
        t2 = sampler._surnames_table()
        assert t1 is t2


class TestDrawMiddleNamesNoTable:
    def test_no_middle_names_data_all_none(self):
        """_draw_middle_names with no data returns all Nones."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        rng = np.random.default_rng(0)
        result = sampler._draw_middle_names(5, raw=False, always_middle=False, rng=rng)
        assert result == [None] * 5

    def test_middle_table_none_all_none(self):
        """When the table can't be built (empty second_names), all slots are None."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        sampler.middle_names_data = {
            'percentage_with_second': 100.0,
            'second_names': {},  # triggers ValueError in alias_from_mapping
        }
        rng = np.random.default_rng(0)
        result = sampler._draw_middle_names(5, raw=False, always_middle=True, rng=rng)
        assert result == [None] * 5


class TestFromBundledParquet:
    def test_from_bundled_parquet_returns_sampler(self):
        """from_bundled_parquet should produce a working BrazilianNameSampler."""
        sampler = BrazilianNameSampler.from_bundled_parquet()
        assert isinstance(sampler, BrazilianNameSampler)
        assert sampler.surname_data is not None
        assert sampler.name_data is not None

    def test_from_bundled_parquet_generates_names(self):
        """A sampler built via from_bundled_parquet can generate names."""
        sampler = BrazilianNameSampler.from_bundled_parquet()
        random.seed(0)
        name = sampler.get_random_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_from_bundled_parquet_has_parquet_root(self):
        """The bundled Parquet data tree exists, so parquet_root should be set."""
        sampler = BrazilianNameSampler.from_bundled_parquet()
        # The bundled Parquet partitions ship with the package
        assert sampler.parquet_root is not None
        assert sampler.parquet_root.exists()


class TestAssembleSurname:
    def test_jr_raw_becomes_JR(self):
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        result = sampler._assemble_surname('Silva', 'JUNIOR', raw=True, with_only_one_surname=False)
        assert result.endswith('JR')

    def test_jr_lower_becomes_Jr(self):
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        result = sampler._assemble_surname('Silva', 'Jr', raw=False, with_only_one_surname=False)
        assert result.endswith('Jr.')

    def test_single_surname_ignores_second(self):
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        result = sampler._assemble_surname('Silva', 'Santos', raw=False, with_only_one_surname=True)
        # Should only contain the first surname (plus optional prefix)
        assert 'Santos' not in result


class TestApplyPrefixRawMode:
    def test_raw_uppercase_unknown_surname_unchanged(self):
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        assert sampler._apply_prefix('UNKNOWN') == 'UNKNOWN'

    def test_raw_santos_gets_uppercase_prefix(self):
        """In raw mode, prefixes should be uppercase."""
        data = _minimal_name_data()
        sampler = BrazilianNameSampler(data)
        seen_prefixed = False
        for seed in range(300):
            random.seed(seed)
            result = sampler._apply_prefix('SANTOS')
            # When prefixed, the prefix token should be upper-case
            parts = result.split()
            if len(parts) > 1:
                assert parts[0].isupper() or parts[0] in ('DOS', 'DE', 'DA', 'DO', 'E', "D'"), f'Unexpected prefix case in {result!r}'
                seen_prefixed = True
        assert seen_prefixed, 'Expected to see at least one prefixed result'


# ---------------------------------------------------------------------------
# data_origins.py — additional coverage
# ---------------------------------------------------------------------------

from ptbr_sampler.data_origins import DATA_ORIGINS, DataOrigin, by_kind


class TestByKindContent:
    def test_by_kind_has_first_names_key(self):
        d = by_kind()
        assert 'First names' in d
        assert isinstance(d['First names'], DataOrigin)

    def test_by_kind_has_cities_key(self):
        d = by_kind()
        assert 'Cities' in d

    def test_by_kind_values_are_data_origins(self):
        for origin in by_kind().values():
            assert isinstance(origin, DataOrigin)

    def test_by_kind_kind_matches_key(self):
        for kind, origin in by_kind().items():
            assert origin.kind == kind


class TestDataOriginNotes:
    def test_states_has_notes(self):
        d = by_kind()
        assert d['States (UFs)'].notes  # Notes should be non-empty for states

    def test_middle_names_has_notes(self):
        d = by_kind()
        assert d['Middle names'].notes

    def test_first_names_has_notes(self):
        d = by_kind()
        assert d['First names'].notes


class TestDataOriginFileStatus:
    def test_file_status_returns_list_of_tuples(self):
        origin = DATA_ORIGINS[0]
        status = origin.file_status()
        assert isinstance(status, list)
        for entry in status:
            assert len(entry) == 2
            path, exists = entry
            assert isinstance(path, Path)
            assert isinstance(exists, bool)

    def test_file_status_nonexistent_returns_false(self, tmp_path: Path):
        origin = DataOrigin(
            kind='Test',
            summary='Test summary',
            files=(tmp_path / 'does_not_exist.json',),
        )
        status = origin.file_status()
        assert len(status) == 1
        _, exists = status[0]
        assert exists is False

    def test_file_status_existing_returns_true(self, tmp_path: Path):
        f = tmp_path / 'exists.json'
        f.write_text('{}', encoding='utf-8')
        origin = DataOrigin(
            kind='Test',
            summary='Test summary',
            files=(f,),
        )
        status = origin.file_status()
        _, exists = status[0]
        assert exists is True

    def test_file_status_empty_files_returns_empty(self):
        origin = DataOrigin(kind='Test', summary='Test', files=())
        assert origin.file_status() == []


class TestDataOriginDimensions:
    def test_first_names_has_period_dimension(self):
        d = by_kind()
        assert 'period' in d['First names'].dimensions

    def test_cities_has_cep_dimension(self):
        d = by_kind()
        dims = ' '.join(d['Cities'].dimensions)
        assert 'cep' in dims.lower()

    def test_states_has_population_percentage(self):
        d = by_kind()
        dims = ' '.join(d['States (UFs)'].dimensions)
        assert 'population_percentage' in dims


# ---------------------------------------------------------------------------
# __init__.py — additional edge cases
# ---------------------------------------------------------------------------


class TestPackageInit:
    def test_version_is_string(self):
        import ptbr_sampler

        assert isinstance(ptbr_sampler.__version__, str)

    def test_version_contains_dots(self):
        import ptbr_sampler

        # Minimal semver-like check
        parts = ptbr_sampler.__version__.split('.')
        assert len(parts) >= 2

    def test_time_period_accessible_from_package(self):
        from ptbr_sampler import TimePeriod

        assert TimePeriod.UNTIL_2010.value == 'ate2010'

    def test_name_components_accessible_from_package(self):
        from ptbr_sampler import NameComponents

        nc = NameComponents('João', None, 'Silva')
        assert nc.first_name == 'João'
        assert nc.middle_name is None
        assert nc.surname == 'Silva'


# ---------------------------------------------------------------------------
# __main__.py — importable and wired to cli.main
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def cli_help_run() -> subprocess.CompletedProcess[str]:
    """
    Run the package's CLI help command and return the completed process result.
    
    Returns:
        subprocess.CompletedProcess[str]: Completed process containing captured `stdout`, `stderr`, and `returncode`.
    """
    return subprocess.run(
        [sys.executable, '-m', 'ptbr_sampler', '--help'],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


class TestMainModule:
    def test_main_module_importable(self):
        """python -m ptbr_sampler should be importable without raising."""
        import ptbr_sampler.__main__ as m

        assert hasattr(m, 'main')

    def test_main_is_callable(self):
        from ptbr_sampler.__main__ import main

        assert callable(main)

    def test_main_module_runs_help(self, cli_help_run):
        """Running python -m ptbr_sampler --help should exit cleanly."""
        assert cli_help_run.returncode == 0


# ---------------------------------------------------------------------------
# cli.py — package-relative paths and generate alias
# ---------------------------------------------------------------------------


class TestCliPackagePaths:
    def test_generate_command_is_listed_in_help(self, cli_help_run):
        """The ``generate`` alias is registered as a command."""
        assert cli_help_run.returncode == 0
        assert 'generate' in cli_help_run.stdout

    def test_sample_command_is_listed_in_help(self, cli_help_run):
        """The ``sample`` command is registered."""
        assert cli_help_run.returncode == 0
        assert 'sample' in cli_help_run.stdout

    def test_sources_command_is_listed_in_help(self, cli_help_run):
        """The ``sources`` command is registered."""
        assert cli_help_run.returncode == 0
        assert 'sources' in cli_help_run.stdout

    def test_package_data_dir_points_inside_package(self):
        """The CLI resolves data files relative to the installed package."""
        from ptbr_sampler import cli

        # _PACKAGE_DATA should be an absolute path inside the package
        assert cli._PACKAGE_DATA.is_absolute()
        assert cli._PACKAGE_DATA.name == 'data'

    def test_package_data_dir_exists(self):
        """The resolved data directory actually exists."""
        from ptbr_sampler import cli

        assert cli._PACKAGE_DATA.exists()


# ---------------------------------------------------------------------------
# Regression: TimePeriod enum values
# ---------------------------------------------------------------------------


class TestTimePeriodEnum:
    def test_all_period_values(self):
        expected_values = {
            'ate1930',
            'ate1940',
            'ate1950',
            'ate1960',
            'ate1970',
            'ate1980',
            'ate1990',
            'ate2000',
            'ate2010',
            'ate2020',
            'after2010',
        }
        actual = {p.value for p in TimePeriod}
        assert actual == expected_values

    def test_time_period_is_str(self):
        """TimePeriod inherits from str, so its values can be used as dict keys."""
        assert isinstance(TimePeriod.UNTIL_2010, str)
        assert TimePeriod.UNTIL_2010 == 'ate2010'

    def test_time_period_count(self):
        assert len(TimePeriod) == 11


# ---------------------------------------------------------------------------
# Regression: NameComponents dataclass
# ---------------------------------------------------------------------------


class TestNameComponentsDataclass:
    def test_none_middle_name(self):
        nc = NameComponents('Ana', None, 'Souza')
        assert nc.middle_name is None

    def test_equality(self):
        nc1 = NameComponents('Ana', 'Lúcia', 'Souza')
        nc2 = NameComponents('Ana', 'Lúcia', 'Souza')
        assert nc1 == nc2

    def test_inequality(self):
        nc1 = NameComponents('Ana', None, 'Silva')
        nc2 = NameComponents('Maria', None, 'Silva')
        assert nc1 != nc2

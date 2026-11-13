"""Tests for the BrazilianNameSampler class."""

import json
import random
from pathlib import Path

import pytest

from ptbr_sampler.br_name_class import (
    LEGACY_2010_PERIODS,
    BrazilianNameSampler,
    NameComponents,
    TimePeriod,
)


def _minimal_middle_names_payload() -> dict:
    return {
        'percentage_with_second': 100.0,
        'second_names': {
            'Augusto': {'count': 10, 'percentage': 0.6},
            'Henrique': {'count': 5, 'percentage': 0.4},
        },
    }


class TestInitialization:
    def test_init_from_dict(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        assert sampler.name_data is not None
        assert sampler.surname_data is not None
        assert sampler.top_40_surnames is not None

    def test_init_invalid_path_raises(self):
        with pytest.raises(FileNotFoundError):
            BrazilianNameSampler('nonexistent_path.json')

    def test_init_missing_surnames_raises(self):
        data = {'common_names_percentage': {p.value: {'names': {'Test': {'percentage': 1.0}}, 'total': 1} for p in LEGACY_2010_PERIODS}}
        with pytest.raises(ValueError, match="Missing 'surnames' data"):
            BrazilianNameSampler(data)

    def test_init_missing_names_raises_key_error(self):
        """When no names_path and no common_names_percentage, KeyError is raised."""
        data = {'surnames': {'Test': {'percentage': 1.0}, 'top_40': {}}}
        with pytest.raises(KeyError):
            BrazilianNameSampler(data)

    def test_init_from_file_path(self, mock_name_data, tmp_path: Path):
        """Loading surname/name data from a file path also works."""
        payload = tmp_path / 'names.json'
        payload.write_text(json.dumps(mock_name_data), encoding='utf-8')
        sampler = BrazilianNameSampler(payload)
        assert sampler.surname_data is not None

    def test_init_with_separate_names_path(self, mock_name_data, tmp_path: Path):
        """names_path argument should override data['common_names_percentage']."""
        # Data without common_names_percentage
        base = {'surnames': mock_name_data['surnames']}
        names_file = tmp_path / 'names_only.json'
        names_file.write_text(
            json.dumps({'common_names_percentage': mock_name_data['common_names_percentage']}),
            encoding='utf-8',
        )
        sampler = BrazilianNameSampler(base, names_path=names_file)
        assert TimePeriod.UNTIL_2010.value in sampler.name_data

    def test_init_with_middle_names_path(self, mock_name_data, tmp_path: Path):
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(_minimal_middle_names_payload()), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        assert sampler.middle_names_data is not None
        assert 'Augusto' in sampler.middle_names_data['second_names']

    def test_init_middle_names_missing_fields_raises(self, mock_name_data, tmp_path: Path):
        bad_middle = tmp_path / 'bad_middle.json'
        bad_middle.write_text(json.dumps({'foo': 'bar'}), encoding='utf-8')
        with pytest.raises(ValueError, match='Missing required fields in middle names file'):
            BrazilianNameSampler(mock_name_data, middle_names_path=bad_middle)

    def test_validate_invalid_names_type_raises(self, mock_name_data):
        mock_name_data['common_names_percentage']['ate1930']['names'] = ['not', 'a', 'dict']
        with pytest.raises(TypeError, match='Invalid names data format'):
            BrazilianNameSampler(mock_name_data)

    def test_validate_invalid_surname_type_raises(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        # Directly test the validator — ``__init__`` indexes ``.get('top_40')``
        # before running _validate_data, so we set the bad value post-hoc.
        sampler.surname_data = ['not-a-dict']
        with pytest.raises(TypeError, match='Invalid surname data format'):
            sampler._validate_data()

    def test_validate_middle_names_missing_keys_raises(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {'second_names': {}}
        with pytest.raises(ValueError, match='Missing required keys'):
            sampler._validate_data()

    def test_validate_middle_names_second_names_not_dict_raises(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 10.0,
            'second_names': 'bad',
        }
        with pytest.raises(TypeError, match="'second_names' must be a dictionary"):
            sampler._validate_data()

    def test_validate_middle_names_empty_raises(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 10.0,
            'second_names': {},
        }
        with pytest.raises(ValueError, match='contains no entries'):
            sampler._validate_data()

    def test_validate_middle_names_entry_missing_keys_raises(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 10.0,
            'second_names': {'Foo': {'count': 1}},  # missing 'percentage'
        }
        with pytest.raises(ValueError, match='Invalid middle name entry structure'):
            sampler._validate_data()


class TestValidation:
    def test_valid_data_passes(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler._validate_data()  # Should not raise

    def test_missing_period_raises(self, mock_name_data):
        mock_name_data['common_names_percentage'].pop('ate1930')
        with pytest.raises(ValueError, match='Missing data for time period'):
            BrazilianNameSampler(mock_name_data)

    def test_missing_names_key_raises(self, mock_name_data):
        mock_name_data['common_names_percentage']['ate1930'] = {'total': 1}
        with pytest.raises(ValueError, match='Missing names data for time period'):
            BrazilianNameSampler(mock_name_data)


class TestNameGeneration:
    def test_returns_string_by_default(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        name = sampler.get_random_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_returns_components(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        result = sampler.get_random_name(return_components=True)
        assert isinstance(result, NameComponents)
        assert result.first_name
        assert result.surname

    def test_raw_format(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        result = sampler.get_random_name(raw=True, return_components=True)
        assert result.first_name.isupper()

    def test_time_period_selection(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        for period in LEGACY_2010_PERIODS:
            name = sampler.get_random_name(time_period=period)
            assert isinstance(name, str)
            assert len(name) > 0

    def test_no_surname(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        result = sampler.get_random_name(include_surname=False, return_components=True)
        assert result.surname == ''

    def test_no_surname_returns_string_with_middle(self, mock_name_data, tmp_path):
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(_minimal_middle_names_payload()), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        random.seed(1)
        name = sampler.get_random_name(include_surname=False, always_middle=True, return_components=False)
        # First name + middle name only (2 tokens)
        parts = name.split()
        assert len(parts) == 2

    def test_no_surname_returns_string_no_middle(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        name = sampler.get_random_name(include_surname=False)
        assert ' ' not in name

    def test_only_middle_returns_components(self, mock_name_data, tmp_path):
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(_minimal_middle_names_payload()), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        result = sampler.get_random_name(only_middle=True, return_components=True)
        assert result.first_name == ''
        assert result.surname == ''
        assert result.middle_name in {'Augusto', 'Henrique'}

    def test_only_middle_returns_string(self, mock_name_data, tmp_path):
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(_minimal_middle_names_payload()), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        name = sampler.get_random_name(only_middle=True, raw=True)
        assert name.isupper()

    def test_full_name_as_string_with_middle(self, mock_name_data, tmp_path):
        mp = tmp_path / 'middles.json'
        mp.write_text(json.dumps(_minimal_middle_names_payload()), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        random.seed(0)
        name = sampler.get_random_name(always_middle=True)
        # first + middle + (surname, which is at least 1 token — possibly with prefix)
        assert len(name.split()) >= 3


class TestSurnameGeneration:
    def test_default_two_surnames(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        surname = sampler.get_random_surname()
        assert isinstance(surname, str)
        assert len(surname) > 0

    def test_single_surname(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        surname = sampler.get_random_surname(with_only_one_surname=True)
        # A single surname may still have a prefix like "da Silva"
        assert isinstance(surname, str)
        assert len(surname) > 0

    def test_top_40(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        surname = sampler.get_random_surname(top_40=True)
        # With our mock data, top_40 only has Silva and Santos
        assert isinstance(surname, str)

    def test_raw_surname(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        surname = sampler.get_random_surname(raw=True)
        # Raw means uppercase
        parts = surname.split()
        for part in parts:
            # Prefixes may be lowercase even in raw mode if not matched, but
            # actual surname tokens should be uppercase
            assert part.isupper() or part.lower() in ('da', 'de', 'do', 'dos', 'das', 'e', "d'")


class TestMiddleNamesInternals:
    def test_no_middle_names_data_returns_empty(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        assert sampler._get_random_middle_name() == ''

    def test_should_add_middle_name_without_data(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        assert sampler._should_add_middle_name() is False

    def test_middle_names_second_names_missing_returns_empty(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {'percentage_with_second': 50.0}
        assert sampler._get_random_middle_name() == ''

    def test_middle_names_empty_second_names(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 10.0,
            'second_names': {},
        }
        assert sampler._get_random_middle_name() == ''

    def test_middle_names_invalid_percentage_skipped(self, mock_name_data, tmp_path):
        mp_payload = {
            'percentage_with_second': 100.0,
            'second_names': {
                'Bad': {'count': 1, 'percentage': 'oops'},
                'Good': {'count': 2, 'percentage': 0.5},
            },
        }
        mp = tmp_path / 'm.json'
        mp.write_text(json.dumps(mp_payload), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        random.seed(0)
        assert sampler._get_random_middle_name() == 'Good'

    def test_middle_names_all_nonpositive_returns_empty(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 100.0,
            'second_names': {'Zero': {'count': 0, 'percentage': 0.0}},
        }
        assert sampler._get_random_middle_name() == ''


class TestApplyPrefix:
    def test_unknown_surname_no_prefix(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        assert sampler._apply_prefix('Unknown') == 'Unknown'

    def test_prefix_not_allowed(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        assert sampler._apply_prefix('Silva', allow_prefix=False) == 'Silva'

    def test_known_surname_gets_prefix_or_not(self, mock_name_data):
        """Silva is in SURNAME_PREFIXES, so result is either prefixed or raw."""
        sampler = BrazilianNameSampler(mock_name_data)
        results = set()
        for seed in range(200):
            random.seed(seed)
            results.add(sampler._apply_prefix('Silva'))
        # Should see at least the unprefixed and one prefixed variant
        assert len(results) > 1


class TestNameComponentsSlots:
    def test_slots_are_used(self):
        nc = NameComponents('João', 'Pedro', 'Silva')
        assert nc.first_name == 'João'
        assert nc.middle_name == 'Pedro'
        assert nc.surname == 'Silva'
        # Verify __slots__ is in effect: assigning a new attribute should fail
        with pytest.raises(AttributeError):
            nc.new_attr = 'test'


class TestBatchSampleNames:
    def test_returns_correct_length(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        results = sampler.batch_sample_names(100)
        assert len(results) == 100

    def test_single_draw(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        results = sampler.batch_sample_names(1)
        assert len(results) == 1
        assert isinstance(results[0], NameComponents)

    def test_all_entries_are_name_components(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        results = sampler.batch_sample_names(50)
        for nc in results:
            assert isinstance(nc, NameComponents)
            assert nc.first_name
            assert nc.surname

    def test_raw_mode(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        results = sampler.batch_sample_names(20, raw=True)
        for nc in results:
            assert nc.first_name.isupper()

    def test_single_surname_mode(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        random.seed(42)
        results = sampler.batch_sample_names(20, with_only_one_surname=True)
        for nc in results:
            assert isinstance(nc.surname, str)
            assert len(nc.surname) > 0

    def test_no_surname_mode(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        results = sampler.batch_sample_names(20, include_surname=False)
        for nc in results:
            assert nc.surname == ''

    def test_batch_with_real_data(self, name_sampler):
        """Test batch with full production dataset."""
        results = name_sampler.batch_sample_names(50)
        assert len(results) == 50
        for nc in results:
            assert nc.first_name
            assert nc.surname

    def test_always_middle(self, name_sampler):
        """With always_middle, every entry should have a middle name."""
        results = name_sampler.batch_sample_names(50, always_middle=True)
        for nc in results:
            assert nc.middle_name is not None
            assert len(nc.middle_name) > 0

    def test_zero_draws(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        assert sampler.batch_sample_names(0) == []

    def test_batch_uses_middle_when_data_present(self, mock_name_data, tmp_path):
        mp_payload = _minimal_middle_names_payload()
        mp = tmp_path / 'm.json'
        mp.write_text(json.dumps(mp_payload), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        # always_middle path populates every slot
        results = sampler.batch_sample_names(20, always_middle=True)
        assert all(nc.middle_name for nc in results)

    def test_batch_conditional_middle(self, mock_name_data, tmp_path):
        # percentage_with_second=0 means no middle names should ever be filled
        payload = dict(_minimal_middle_names_payload())
        payload['percentage_with_second'] = 0.0
        mp = tmp_path / 'm.json'
        mp.write_text(json.dumps(payload), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        random.seed(0)
        results = sampler.batch_sample_names(20)
        assert all(nc.middle_name is None for nc in results)

    def test_batch_skips_invalid_middle_percentages(self, mock_name_data, tmp_path):
        payload = {
            'percentage_with_second': 100.0,
            'second_names': {
                'Broken': {'count': 1, 'percentage': 'bad'},
                'Also': {'count': 1, 'percentage': 0.5},
            },
        }
        mp = tmp_path / 'm.json'
        mp.write_text(json.dumps(payload), encoding='utf-8')
        sampler = BrazilianNameSampler(mock_name_data, middle_names_path=mp)
        results = sampler.batch_sample_names(5, always_middle=True)
        # Only the valid entry should have been selected
        assert all(nc.middle_name == 'Also' for nc in results)


class TestSurnameJrSuffix:
    def test_single_surname_with_junior(self, mock_name_data):
        mock_name_data['surnames']['Junior'] = {'percentage': 10.0}
        sampler = BrazilianNameSampler(mock_name_data)
        # Force surname to always resolve to Junior by nuking all other entries
        sampler.surname_data = {'Junior': {'percentage': 1.0}}
        # Two surnames: first normal (only Junior in pool), second also Junior —
        # second surname should render as "Jr." in non-raw.
        surname = sampler.get_random_surname()
        assert surname.endswith('Jr.')

    def test_single_surname_with_junior_raw(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.surname_data = {'Junior': {'percentage': 1.0}}
        surname = sampler.get_random_surname(raw=True)
        assert surname.endswith('JR')

    def test_batch_surname_with_junior(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.surname_data = {'Junior': {'percentage': 1.0}}
        results = sampler.batch_sample_names(5)
        assert all(nc.surname.endswith('Jr.') for nc in results)

    def test_batch_surname_with_junior_raw(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.surname_data = {'Junior': {'percentage': 1.0}}
        results = sampler.batch_sample_names(5, raw=True)
        assert all(nc.surname.endswith('JR') for nc in results)


def _write_test_partition(dest_dir: Path, names: list[str], counts: list[int]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    dest_dir.mkdir(parents=True, exist_ok=True)
    tot = float(sum(counts))
    pq.write_table(
        pa.table(
            {
                'name': pa.array(names, type=pa.string()),
                'count': pa.array(counts, type=pa.int64()),
                'weight': pa.array([c / tot for c in counts], type=pa.float64()),
            }
        ),
        dest_dir / 'part.parquet',
    )


def _write_test_sex_prior(
    dest_dir: Path,
    rows: list[tuple[str, str, int, int | None, int | None, int, float, float, str]],
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    dest_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                'name': pa.array([r[0] for r in rows], type=pa.string()),
                'canonical_key': pa.array([r[1] for r in rows], type=pa.string()),
                'count_total': pa.array([r[2] for r in rows], type=pa.int64()),
                'count_male': pa.array([r[3] for r in rows], type=pa.int64()),
                'count_female': pa.array([r[4] for r in rows], type=pa.int64()),
                'residual_unassigned': pa.array([r[5] for r in rows], type=pa.int64()),
                'p_male': pa.array([r[6] for r in rows], type=pa.float64()),
                'p_female': pa.array([r[7] for r in rows], type=pa.float64()),
                'censoring_regime': pa.array([r[8] for r in rows], type=pa.string()),
            }
        ),
        dest_dir / 'part.parquet',
    )


def test_legacy_2010_json_validation_ignores_2022_only_time_periods(mock_name_data):
    """Adding TimePeriod.ALL / UNTIL_2020 / PERIOD_2020_2022 must not break 2010 JSON validation."""
    assert len(LEGACY_2010_PERIODS) == 9
    assert len(TimePeriod) == 12
    sampler = BrazilianNameSampler(mock_name_data)
    assert sampler.census_year == 2010
    assert sampler.get_random_name()
    with pytest.raises(ValueError, match='census_year=2010'):
        sampler.get_random_name(time_period=TimePeriod.ALL)
    with pytest.raises(ValueError, match='census_year=2010'):
        sampler.get_random_name(time_period=TimePeriod.PERIOD_2020_2022)


def test_from_parquet_defaults_to_2022_and_from_bundled_parquet_matches():
    sampler = BrazilianNameSampler.from_parquet()
    bundled = BrazilianNameSampler.from_bundled_parquet()
    assert sampler.census_year == 2022
    assert bundled.census_year == 2022
    assert sampler.conditioning_mode == 'strict'
    assert sampler.parquet_root is not None and sampler.parquet_root.exists()
    nc = sampler.get_random_name(return_components=True)
    assert nc.first_name and nc.surname


def test_census_2022_rejects_legacy_ate1930_and_supports_ate1940():
    sampler = BrazilianNameSampler.from_parquet()
    with pytest.raises(ValueError, match='ate1930'):
        sampler.get_random_name(time_period=TimePeriod.UNTIL_1930)
    assert sampler.get_random_name(time_period=TimePeriod.UNTIL_1940)


def test_census_2022_strict_mode_rejects_unobserved_joints():
    sampler = BrazilianNameSampler.from_parquet()
    with pytest.raises(ValueError, match="conditioning_mode='estimated'"):
        sampler.get_random_name(time_period=TimePeriod.ALL, uf='SP', sex='F')
    with pytest.raises(ValueError, match="conditioning_mode='estimated'"):
        sampler.get_random_name(time_period=TimePeriod.PERIOD_2020_2022, sex='M')
    sampler_est = BrazilianNameSampler.from_parquet(conditioning_mode='estimated')
    with pytest.raises(ValueError, match='UF x cohort'):
        sampler_est.get_random_name(time_period=TimePeriod.PERIOD_2020_2022, uf='SP')


def test_census_2022_estimated_mode_computes_exact_bayes_weights_and_excludes_suppressed_sex(tmp_path: Path):
    import math

    root_2022 = tmp_path / 'census_year=2022'
    _write_test_partition(root_2022 / 'first_names' / 'period=ate2020', ['Maria', 'Joao', 'Rara'], [100, 100, 30])
    _write_test_partition(root_2022 / 'surnames' / 'scope=national', ['Silva', 'Santos'], [60, 40])
    _write_test_sex_prior(
        root_2022 / 'sex_prior' / 'scope=national',
        rows=[
            ('Maria', 'maria', 1000, 100, 900, 0, 0.10, 0.90, 'both_observed'),
            ('Joao', 'joao', 1000, 900, 100, 0, 0.90, 0.10, 'both_observed'),
            ('Rara', 'rara', 30, None, 25, 5, math.nan, 25.0 / 30.0, 'one_null_suppressed_positive'),
        ],
    )
    sampler = BrazilianNameSampler.from_parquet_root(
        root_2022,
        census_year=2022,
        conditioning_mode='estimated',
    )
    table_m = sampler._first_names_table(TimePeriod.UNTIL_2020, sex='M')
    by_m = dict(zip(table_m.labels.tolist(), table_m.induced_probabilities().tolist(), strict=True))
    assert 'Rara' not in by_m
    assert abs(by_m['Joao'] - 0.90) < 1e-12
    assert abs(by_m['Maria'] - 0.10) < 1e-12

    table_f = sampler._first_names_table(TimePeriod.UNTIL_2020, sex='F')
    by_f = dict(zip(table_f.labels.tolist(), table_f.induced_probabilities().tolist(), strict=True))
    assert abs(by_f['Maria'] - (90.0 / 125.0)) < 1e-12
    assert abs(by_f['Joao'] - (10.0 / 125.0)) < 1e-12
    assert abs(by_f['Rara'] - (25.0 / 125.0)) < 1e-12


def test_census_2022_two_surname_draw_prevents_identical_stems(tmp_path: Path):
    root_2022 = tmp_path / 'census_year=2022'
    _write_test_partition(root_2022 / 'first_names' / 'scope=national', ['Maria'], [100])
    _write_test_partition(root_2022 / 'surnames' / 'scope=national', ['Silva', 'Santos'], [90, 10])
    sampler = BrazilianNameSampler.from_parquet_root(root_2022, census_year=2022)
    random.seed(7)
    batches = sampler.batch_sample_names(500, time_period=TimePeriod.ALL, raw=True)
    for comp in batches:
        tokens = [t for t in comp.surname.split() if t not in {'DA', 'DE', 'DO', 'DOS', 'DAS', 'E'}]
        assert len(tokens) == 2
        assert tokens[0] != tokens[1]


def test_census_2022_estimated_mode_supports_uf_sex_and_cohort_sex_under_5ms():
    import time

    sampler = BrazilianNameSampler.from_parquet(conditioning_mode='estimated')
    t0_cpu = time.process_time()
    names_uf = sampler.batch_sample_names(
        50,
        time_period=TimePeriod.ALL,
        ufs=['SP'] * 50,
        sexes=['F'] * 50,
    )
    cold_cpu_ms = (time.process_time() - t0_cpu) * 1000.0
    assert len(names_uf) == 50
    assert cold_cpu_ms < 250.0

    t0_warm = time.process_time()
    warm_uf = sampler.batch_sample_names(
        50,
        time_period=TimePeriod.ALL,
        ufs=['SP'] * 50,
        sexes=['F'] * 50,
    )
    warm_cpu_ms = (time.process_time() - t0_warm) * 1000.0
    assert len(warm_uf) == 50
    assert warm_cpu_ms < 5.0

    names_cohort = sampler.batch_sample_names(
        50,
        time_period=TimePeriod.PERIOD_2020_2022,
        sexes=['M'] * 50,
    )
    assert len(names_cohort) == 50


def test_census_2022_never_emits_duplicate_surname_stems():
    sampler = BrazilianNameSampler.from_parquet()
    draws = sampler.batch_sample_names(1000, time_period=TimePeriod.ALL, ufs=['SP'] * 1000)
    for nc in draws:
        tokens = [tok.lower() for tok in nc.surname.split() if tok.lower() not in {'da', 'de', 'do', 'dos', 'das', 'e', "d'"}]
        assert len(tokens) == len(set(tokens))


def test_name_sampler_preloaded_data_and_path_traversal_rejection(mock_name_data):
    sampler = BrazilianNameSampler(None, preloaded_data=mock_name_data)
    assert sampler.get_random_name()

    with pytest.raises(ValueError, match='traversal|Null byte'):
        BrazilianNameSampler('../../../etc/passwd')
    with pytest.raises(ValueError, match='traversal|Null byte'):
        BrazilianNameSampler('bad\x00path.json')
    with pytest.raises(ValueError, match='traversal|Null byte'):
        BrazilianNameSampler(mock_name_data, names_path='../../../etc/passwd')
    with pytest.raises(ValueError, match='traversal|Null byte'):
        BrazilianNameSampler(mock_name_data, middle_names_path='../../../etc/passwd')


def test_name_sampler_rejects_outside_allowed_roots_and_non_json_paths(mock_name_data):
    for bad_target in ('/etc/passwd', '/etc/shadow.json', '/var/tmp/../etc/hosts.json'):
        with pytest.raises(ValueError, match='JSON|outside|traversal'):
            BrazilianNameSampler(bad_target)
        with pytest.raises(ValueError, match='JSON|outside|traversal'):
            BrazilianNameSampler(mock_name_data, names_path=bad_target)
        with pytest.raises(ValueError, match='JSON|outside|traversal'):
            BrazilianNameSampler(mock_name_data, middle_names_path=bad_target)

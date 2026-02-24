"""Tests for the BrazilianNameSampler class."""

import random

import pytest

from src.br_name_class import BrazilianNameSampler, NameComponents, TimePeriod


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
        data = {
            'common_names_percentage': {
                p.value: {'names': {'Test': {'percentage': 1.0}}, 'total': 1}
                for p in TimePeriod
            }
        }
        with pytest.raises(ValueError, match="Missing 'surnames' data"):
            BrazilianNameSampler(data)

    def test_init_missing_names_raises_key_error(self):
        """When no names_path and no common_names_percentage, KeyError is raised."""
        data = {'surnames': {'Test': {'percentage': 1.0}, 'top_40': {}}}
        with pytest.raises(KeyError):
            BrazilianNameSampler(data)


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
        for period in TimePeriod:
            name = sampler.get_random_name(time_period=period)
            assert isinstance(name, str)
            assert len(name) > 0

    def test_no_surname(self, mock_name_data):
        sampler = BrazilianNameSampler(mock_name_data)
        result = sampler.get_random_name(include_surname=False, return_components=True)
        assert result.surname == ''


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

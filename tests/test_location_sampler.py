"""Tests for the BrazilianLocationSampler class."""

import json
import logging
import random

import pytest

from ptbr_sampler.br_location_class import BrazilianLocationSampler


class TestInitialization:
    def test_init_from_dict(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        assert sampler.data == mock_location_data
        assert len(sampler.state_weights) == 2
        assert len(sampler.city_weights_by_state) == 2

    def test_init_missing_cities_raises(self):
        with pytest.raises(ValueError, match="Missing 'cities' or 'states'"):
            BrazilianLocationSampler({'states': {'X': {}}, 'cities': {}})

    def test_init_missing_states_raises(self):
        with pytest.raises(ValueError, match="Missing 'cities' or 'states'"):
            BrazilianLocationSampler({'states': {}, 'cities': {'x': {}}})

    def test_abbr_to_name_built(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        assert sampler.abbr_to_name == {'SP': 'São Paulo', 'RJ': 'Rio de Janeiro'}

    def test_init_from_path(self, mock_location_data, tmp_path):
        """Passing a file path should load the JSON payload from disk."""
        path = tmp_path / 'loc.json'
        path.write_text(json.dumps(mock_location_data), encoding='utf-8')
        sampler = BrazilianLocationSampler(path)
        assert sampler.abbr_to_name == {'SP': 'São Paulo', 'RJ': 'Rio de Janeiro'}

    def test_update_with_empty_cities_noop(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        before = dict(sampler.city_data_by_name)
        sampler.update_cities({})
        assert sampler.city_data_by_name == before

    def test_update_with_empty_states_noop(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        before = list(sampler.state_names)
        sampler.update_states({})
        assert sampler.state_names == before


class TestGetState:
    def test_returns_valid_state(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(42)
        state_name, state_abbr = sampler.get_state()
        assert state_name in ['São Paulo', 'Rio de Janeiro']
        assert state_abbr in ['SP', 'RJ']

    def test_weighted_distribution(self, mock_location_data):
        """SP has 60% weight, RJ 40%. Over many draws, SP should appear more."""
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(0)
        counts = {'SP': 0, 'RJ': 0}
        for _ in range(1000):
            _, abbr = sampler.get_state()
            counts[abbr] += 1
        assert counts['SP'] > counts['RJ']


class TestGetCity:
    def test_returns_valid_city_for_state(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        city_name, state_abbr = sampler.get_city('SP')
        assert city_name in ['São Paulo', 'Campinas']
        assert state_abbr == 'SP'

    def test_rj_city(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        city_name, state_abbr = sampler.get_city('RJ')
        assert city_name == 'Rio de Janeiro'
        assert state_abbr == 'RJ'

    def test_invalid_state_raises(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        with pytest.raises(ValueError, match='No cities found for state: XX'):
            sampler.get_city('XX')

    def test_random_state_when_none(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        city_name, state_abbr = sampler.get_city()
        assert city_name in ['São Paulo', 'Campinas', 'Rio de Janeiro']
        assert state_abbr in ['SP', 'RJ']


class TestGetStateAndCity:
    def test_returns_consistent_tuple(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(42)
        state_name, state_abbr, city_name = sampler.get_state_and_city()
        assert state_name in ['São Paulo', 'Rio de Janeiro']
        assert state_abbr in ['SP', 'RJ']
        # City must belong to the returned state
        city_data = sampler.city_data_by_name[city_name]
        assert city_data['city_uf'] == state_abbr


class TestCepFormatting:
    def test_format_with_dash(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        assert sampler._format_cep('12345678', True) == '12345-678'

    def test_format_without_dash(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        assert sampler._format_cep('12345-678', False) == '12345678'

    def test_format_already_dashed(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        assert sampler._format_cep('12345-678', True) == '12345-678'


class TestRandomCep:
    def test_cep_in_range(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(42)
        cep_str = sampler._get_random_cep_for_city('Campinas')
        cep_int = int(cep_str.replace('-', ''))
        assert 13000000 <= cep_int <= 13139999

    def test_city_not_found_raises(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        with pytest.raises(ValueError, match='City not found'):
            sampler._get_random_cep_for_city('Nonexistent')

    def test_prefers_ceps_list_when_present(self, mock_location_data):
        """When a city has a 'ceps' list, a CEP should be drawn from it."""
        mock_location_data['cities']['campinas']['ceps'] = ['13001-000', '13099-999']
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(0)
        cep = sampler._get_random_cep_for_city('Campinas')
        assert cep in ('13001-000', '13099-999')

    def test_format_full_location_with_cep(self, mock_location_data):
        """format_full_location should embed a CEP when include_cep=True."""
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(1)
        formatted = sampler.format_full_location(
            'Campinas', 'São Paulo', 'SP', include_cep=True, cep_without_dash=False
        )
        # "City, State (SP), CEP"
        assert formatted.count(', ') == 2
        assert 'Campinas' in formatted
        assert formatted.rsplit(', ', 1)[1].count('-') == 1


class TestBatchSampleLocations:
    def test_returns_correct_length(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        results = sampler.batch_sample_locations(100)
        assert len(results) == 100

    def test_single_draw(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        results = sampler.batch_sample_locations(1)
        assert len(results) == 1
        assert 'state_name' in results[0]
        assert 'state_abbr' in results[0]
        assert 'city_name' in results[0]

    def test_all_entries_valid(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        results = sampler.batch_sample_locations(200)
        valid_states = {'São Paulo', 'Rio de Janeiro'}
        valid_abbrs = {'SP', 'RJ'}
        valid_cities = {'São Paulo', 'Campinas', 'Rio de Janeiro'}
        for entry in results:
            assert entry['state_name'] in valid_states
            assert entry['state_abbr'] in valid_abbrs
            assert entry['city_name'] in valid_cities
            # City belongs to its state
            city_data = sampler.city_data_by_name[entry['city_name']]
            assert city_data['city_uf'] == entry['state_abbr']

    def test_batch_with_real_data(self, location_sampler):
        """Test batch with full production dataset."""
        results = location_sampler.batch_sample_locations(50)
        assert len(results) == 50
        for entry in results:
            assert entry['state_name']
            assert entry['state_abbr']
            assert entry['city_name']

    def test_zero_draws(self, mock_location_data):
        """batch_sample_locations(0) should return an empty list."""
        sampler = BrazilianLocationSampler(mock_location_data)
        assert sampler.batch_sample_locations(0) == []

    def test_batch_logs_warning_when_state_has_no_cities(self, mock_location_data, caplog):
        """If a state lacks cities, the batch emits 'Unknown' and warns."""
        # Register a new state (Amazonas) but never add cities for it.
        mock_location_data['states']['Amazonas'] = {
            'state_abbr': 'AM',
            # Weight large enough that we are near-guaranteed to draw it.
            'population_percentage': 100.0,
        }
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(123)
        with caplog.at_level(logging.WARNING, logger='ptbr_sampler.br_location_class'):
            results = sampler.batch_sample_locations(10)
        assert any(entry['city_name'] == 'Unknown' for entry in results)
        assert any('No cities found' in rec.message for rec in caplog.records)


class TestUpdateData:
    def test_update_cities(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        new_city = {
            'new_city': {
                'city_name': 'Nova Cidade',
                'city_uf': 'SP',
                'population_percentage_state': 0.1,
                'cep_range_begins': '14000-000',
                'cep_range_ends': '14999-999',
            }
        }
        sampler.update_cities(new_city)
        assert 'Nova Cidade' in sampler.city_data_by_name

    def test_update_cities_invalid_raises(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        with pytest.raises(ValueError, match='cities_data must be a dictionary'):
            sampler.update_cities('not a dict')

    def test_update_states(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        new_state = {
            'Minas Gerais': {
                'state_abbr': 'MG',
                'population_percentage': 0.1,
            }
        }
        sampler.update_states(new_state)
        assert 'Minas Gerais' in sampler.state_names

    def test_update_states_invalid_raises(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        with pytest.raises(ValueError, match='states_data must be a dictionary'):
            sampler.update_states(42)


class TestFormatting:
    def test_format_full_location(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        location = sampler.format_full_location('Campinas', 'São Paulo', 'SP')
        assert 'Campinas' in location
        assert 'São Paulo' in location
        assert 'SP' in location

    def test_format_full_location_no_cep(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        location = sampler.format_full_location('Campinas', 'São Paulo', 'SP', include_cep=False)
        assert location == 'Campinas, São Paulo (SP)'

    def test_get_random_location_city_only(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        loc = sampler.get_random_location(city_only=True)
        assert loc in ['São Paulo', 'Campinas', 'Rio de Janeiro']

    def test_get_random_location_state_abbr_only(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        loc = sampler.get_random_location(state_abbr_only=True)
        assert loc in ['SP', 'RJ']

    def test_get_random_location_state_full_only(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        loc = sampler.get_random_location(state_full_only=True)
        assert loc in ['São Paulo', 'Rio de Janeiro']

    def test_get_random_location_cep_only(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        loc = sampler.get_random_location(only_cep=True)
        assert len(loc) == 9
        assert loc[5] == '-'

    def test_get_random_location_cep_no_dash(self, mock_location_data):
        sampler = BrazilianLocationSampler(mock_location_data)
        loc = sampler.get_random_location(only_cep=True, cep_without_dash=True)
        assert len(loc) == 8
        assert '-' not in loc

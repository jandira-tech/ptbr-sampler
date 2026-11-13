"""Shared test configuration and fixtures."""

import json
from pathlib import Path

import pytest

from ptbr_sampler.br_name_class import LEGACY_2010_PERIODS

DATA_DIR = Path(__file__).parent.parent / 'ptbr_sampler' / 'data'


@pytest.fixture(scope='session')
def locations_data() -> dict:
    """Load location dataset once for the entire test session."""
    path = DATA_DIR / 'cities_with_ceps.json'
    if not path.exists():
        pytest.skip(f'Test data not found: {path}')
    with path.open(encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture(scope='session')
def location_sampler():
    """Session-scoped location sampler instance using real data."""
    from ptbr_sampler.br_location_class import BrazilianLocationSampler

    path = DATA_DIR / 'cities_with_ceps.json'
    if not path.exists():
        pytest.skip(f'Test data not found: {path}')
    return BrazilianLocationSampler(path)


@pytest.fixture(scope='session')
def name_sampler():
    """Session-scoped name sampler instance using real data."""
    from ptbr_sampler.br_name_class import BrazilianNameSampler

    surnames_path = DATA_DIR / 'surnames_data.json'
    names_path = DATA_DIR / 'names_data.json'
    middle_names_path = DATA_DIR / 'middle_names.json'

    for p in (surnames_path, names_path, middle_names_path):
        if not p.exists():
            pytest.skip(f'Test data not found: {p}')

    # Build combined data dict the same way sampler.py does
    with surnames_path.open(encoding='utf-8') as f:
        surnames_data = json.load(f)
    with names_path.open(encoding='utf-8') as f:
        names_data = json.load(f)

    name_data = {'surnames': surnames_data['surnames']}
    name_data.update(names_data)

    return BrazilianNameSampler(name_data, middle_names_path, None)


@pytest.fixture
def mock_location_data() -> dict:
    """Minimal valid location data structure for unit tests."""
    return {
        'states': {
            'São Paulo': {
                'state_abbr': 'SP',
                'population_percentage': 0.6,
            },
            'Rio de Janeiro': {
                'state_abbr': 'RJ',
                'population_percentage': 0.4,
            },
        },
        'cities': {
            'sao_paulo': {
                'city_name': 'São Paulo',
                'city_uf': 'SP',
                'population_percentage_state': 0.5,
                'cep_range_begins': '01000-000',
                'cep_range_ends': '05999-999',
            },
            'campinas': {
                'city_name': 'Campinas',
                'city_uf': 'SP',
                'population_percentage_state': 0.5,
                'cep_range_begins': '13000-000',
                'cep_range_ends': '13139-999',
            },
            'rio_de_janeiro': {
                'city_name': 'Rio de Janeiro',
                'city_uf': 'RJ',
                'population_percentage_state': 1.0,
                'cep_range_begins': '20000-000',
                'cep_range_ends': '23799-999',
            },
        },
    }


@pytest.fixture
def mock_name_data() -> dict:
    """Minimal valid name data structure for unit tests."""
    return {
        'common_names_percentage': {
            period.value: {
                'names': {
                    'Maria': {'percentage': 0.3},
                    'João': {'percentage': 0.3},
                    'Ana': {'percentage': 0.2},
                    'Pedro': {'percentage': 0.2},
                },
                'total': 100,
            }
            for period in LEGACY_2010_PERIODS
        },
        'surnames': {
            'Silva': {'percentage': 0.3},
            'Santos': {'percentage': 0.2},
            'Oliveira': {'percentage': 0.15},
            'Souza': {'percentage': 0.15},
            'Costa': {'percentage': 0.1},
            'Pereira': {'percentage': 0.1},
            'top_40': {
                'Silva': {'percentage': 0.5},
                'Santos': {'percentage': 0.5},
            },
        },
    }


@pytest.fixture
def seeded_random():
    """Fixture that seeds random for deterministic tests, restores state after."""
    import random

    state = random.getstate()
    random.seed(42)
    yield
    random.setstate(state)

"""Smoke tests: verify imports, basic generation, and CLI help."""

import subprocess
import sys
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent.parent / 'src' / 'data'


def test_imports():
    """Verify all public modules import without error."""
    from sample import TimePeriod, sample  # noqa: F401
    from src.br_location_class import BrazilianLocationSampler  # noqa: F401
    from src.br_name_class import BrazilianNameSampler, NameComponents  # noqa: F401
    from src.document_sampler import DocumentSampler  # noqa: F401
    from src.sampler import sample as sampler_sample  # noqa: F401


def test_time_period_enum():
    """Verify TimePeriod enum has expected members."""
    from src.br_name_class import TimePeriod

    assert len(TimePeriod) == 9
    assert TimePeriod.UNTIL_2010.value == 'ate2010'
    assert TimePeriod.UNTIL_1930.value == 'ate1930'


@pytest.fixture
def _skip_if_no_data():
    """Skip if data files are missing."""
    required = [
        DATA_DIR / 'cities_with_ceps.json',
        DATA_DIR / 'names_data.json',
        DATA_DIR / 'surnames_data.json',
        DATA_DIR / 'middle_names.json',
    ]
    for p in required:
        if not p.exists():
            pytest.skip(f'Test data not found: {p}')


@pytest.mark.usefixtures('_skip_if_no_data')
def test_sample_returns_dict():
    """Basic smoke test: sample(q=1) returns a dict."""
    from sample import sample

    result = sample(q=1)
    assert isinstance(result, dict)
    assert 'name' in result


@pytest.mark.usefixtures('_skip_if_no_data')
def test_sample_returns_list_for_multiple():
    """sample(q=5) returns a list of 5 dicts."""
    from sample import sample

    result = sample(q=5)
    assert isinstance(result, list)
    assert len(result) == 5
    assert all(isinstance(r, dict) for r in result)


def test_document_sampler_generates():
    """DocumentSampler produces valid document strings."""
    from src.document_sampler import DocumentSampler

    ds = DocumentSampler()
    cpf = ds.generate_cpf()
    assert isinstance(cpf, str)
    assert len(cpf) > 0

    pis = ds.generate_pis()
    assert isinstance(pis, str)

    cnpj = ds.generate_cnpj()
    assert isinstance(cnpj, str)

    cei = ds.generate_cei()
    assert isinstance(cei, str)


@pytest.mark.usefixtures('_skip_if_no_data')
def test_location_sampler_basic():
    """BrazilianLocationSampler loads and returns a state."""
    from src.br_location_class import BrazilianLocationSampler

    sampler = BrazilianLocationSampler(DATA_DIR / 'cities_with_ceps.json')
    state_name, state_abbr = sampler.get_state()
    assert isinstance(state_name, str)
    assert len(state_abbr) == 2


def test_name_components_creation():
    """NameComponents dataclass with slots works correctly."""
    from src.br_name_class import NameComponents

    nc = NameComponents('João', 'Pedro', 'Silva')
    assert nc.first_name == 'João'
    assert nc.middle_name == 'Pedro'
    assert nc.surname == 'Silva'


def test_json_cache_module_attribute():
    """Verify the JSON cache exists at module level in sampler."""
    from src.sampler import _json_cache

    assert isinstance(_json_cache, dict)

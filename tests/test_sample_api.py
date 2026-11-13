"""Tests for the public sample.py API wrapper."""

import pytest

from sample import TimePeriod, sample


@pytest.fixture(autouse=True)
def _skip_if_no_data():
    """Skip if runtime data files are unavailable."""
    from ptbr_sampler.datasets import has_runtime_data_available

    if not has_runtime_data_available():
        pytest.skip('Runtime dataset artifacts not available locally')


class TestBasicAPI:
    def test_single_sample_returns_dict(self):
        result = sample(q=1)
        assert isinstance(result, dict)

    def test_multiple_samples_returns_list(self):
        result = sample(q=5)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_default_q_returns_dict(self):
        result = sample()
        assert isinstance(result, dict)


class TestKwargs:
    def test_all_data(self):
        result = sample(q=1, all_data=True)
        assert result['cpf']
        assert result['rg']
        assert result['pis']
        assert result['cnpj']
        assert result['cei']

    def test_time_period(self):
        result = sample(q=1, time_period=TimePeriod.UNTIL_1950)
        assert result['name']

    def test_name_raw(self):
        result = sample(q=1, name_raw=True)
        assert result['name'].isupper()

    def test_only_cpf(self):
        result = sample(q=1, only_cpf=True)
        assert result['cpf']

    def test_city_only(self):
        result = sample(q=1, city_only=True)
        assert result['city']


class TestSaveToJsonl:
    def test_save_creates_file(self, tmp_path):
        output = tmp_path / 'test_output.jsonl'
        sample(q=2, save_to_jsonl=str(output))
        assert output.exists()
        lines = output.read_text().strip().split('\n')
        assert len(lines) == 2


class TestTypeAnnotation:
    def test_signature_accepts_none(self):
        """Verify the fixed type annotation works: str | None = None."""
        # This test just verifies the function can be called with save_to_jsonl=None
        result = sample(q=1, save_to_jsonl=None)
        assert isinstance(result, dict)


def test_sample_defaults_to_census_2022():
    res = sample(q=3)
    assert len(res) == 3
    with pytest.raises(ValueError, match='ate1930'):
        sample(q=1, time_period=TimePeriod.UNTIL_1930)


def test_sample_census_2010_opt_in_preserves_ate1930():
    res = sample(q=2, census_year=2010, time_period=TimePeriod.UNTIL_1930)
    assert len(res) == 2


def test_sample_census_2022_modes():
    res = sample(
        q=10,
        time_period=TimePeriod.PERIOD_2020_2022,
        sex_conditioning='POPULATION',
        conditioning_mode='estimated',
    )
    assert len(res) == 10
    res_uf = sample(q=10, uf_conditioning=True)
    assert len(res_uf) == 10

"""Tests for the public sample.py API wrapper."""

import pytest

from sample import TimePeriod, sample


@pytest.fixture(autouse=True)
def _skip_if_no_data():
    """Skip if data files are missing."""
    from pathlib import Path

    data_dir = Path(__file__).parent.parent / 'src' / 'data'
    required = [
        data_dir / 'cities_with_ceps.json',
        data_dir / 'names_data.json',
        data_dir / 'surnames_data.json',
        data_dir / 'middle_names.json',
    ]
    for p in required:
        if not p.exists():
            pytest.skip(f'Test data not found: {p}')


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

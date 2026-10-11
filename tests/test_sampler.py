"""Integration tests for src.sampler.sample()."""

from pathlib import Path

import pytest

from ptbr_sampler.br_name_class import TimePeriod
from ptbr_sampler.sampler import sample

DATA_DIR = Path(__file__).parent.parent / 'ptbr_sampler' / 'data'

# Default paths matching CLI defaults
DEFAULT_KWARGS = {
    'qty': 1,
    'q': None,
    'city_only': False,
    'state_abbr_only': False,
    'state_full_only': False,
    'only_cep': False,
    'cep_without_dash': False,
    'make_api_call': False,
    'time_period': TimePeriod.UNTIL_2010,
    'return_only_name': False,
    'name_raw': False,
    'json_path': DATA_DIR / 'cities_with_ceps.json',
    'names_path': DATA_DIR / 'names_data.json',
    'middle_names_path': DATA_DIR / 'middle_names.json',
    'only_surname': False,
    'top_40': False,
    'with_only_one_surname': False,
    'always_middle': False,
    'only_middle': False,
    'always_cpf': True,
    'always_pis': False,
    'always_cnpj': False,
    'always_cei': False,
    'always_rg': True,
    'always_phone': True,
    'only_cpf': False,
    'only_pis': False,
    'only_cnpj': False,
    'only_cei': False,
    'only_rg': False,
    'only_fone': False,
    'include_issuer': True,
    'only_document': False,
    'surnames_path': DATA_DIR / 'surnames_data.json',
    'locations_path': DATA_DIR / 'locations_data.json',
    'save_to_jsonl': None,
    'all_data': False,
}


def _sample(**overrides):
    """Call sample() with default args plus any overrides."""
    kwargs = {**DEFAULT_KWARGS, **overrides}
    return sample(**kwargs)


@pytest.fixture(autouse=True)
def _skip_if_no_data():
    """Skip all tests in this module if data files are missing."""
    required = [
        DATA_DIR / 'cities_with_ceps.json',
        DATA_DIR / 'names_data.json',
        DATA_DIR / 'surnames_data.json',
        DATA_DIR / 'middle_names.json',
    ]
    for p in required:
        if not p.exists():
            pytest.skip(f'Test data not found: {p}')


class TestSingleSample:
    def test_returns_dict(self):
        result = _sample(qty=1)
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = _sample(qty=1)
        for key in ('name', 'city', 'state', 'state_abbr', 'cpf', 'rg'):
            assert key in result

    def test_name_is_nonempty(self):
        result = _sample(qty=1)
        assert result['name']

    def test_city_is_nonempty(self):
        result = _sample(qty=1)
        assert result['city']


class TestMultipleSamples:
    def test_returns_list(self):
        result = _sample(qty=3)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_each_has_keys(self):
        results = _sample(qty=3)
        for r in results:
            assert 'name' in r
            assert 'city' in r

    def test_batch_path_used(self):
        """With qty > 1, batch methods should produce valid results."""
        results = _sample(qty=10)
        assert len(results) == 10
        for r in results:
            assert r['name']
            assert r['city']


class TestAllData:
    def test_all_data_flag(self):
        result = _sample(qty=1, all_data=True)
        assert result['cpf']
        assert result['rg']
        assert result['phone']
        assert result['pis']
        assert result['cnpj']
        assert result['cei']


class TestDocumentOnly:
    def test_only_document(self):
        result = _sample(qty=1, only_document=True, always_cpf=True)
        assert isinstance(result, dict)
        assert result['cpf']

    def test_only_cpf(self):
        result = _sample(qty=1, only_cpf=True)
        assert isinstance(result, dict)
        assert result['cpf']


class TestNameOnly:
    def test_return_only_name(self):
        result = _sample(qty=1, return_only_name=True)
        assert isinstance(result, dict)
        assert result['name']

    def test_only_surname(self):
        result = _sample(qty=1, only_surname=True)
        assert isinstance(result, dict)
        assert result['surnames']


class TestLocationFormats:
    def test_city_only(self):
        result = _sample(qty=1, city_only=True)
        assert isinstance(result, dict)
        assert result['city']

    def test_state_abbr_only(self):
        result = _sample(qty=1, state_abbr_only=True)
        assert isinstance(result, dict)


class TestQAlias:
    def test_q_takes_precedence(self):
        result = _sample(qty=1, q=3)
        assert isinstance(result, list)
        assert len(result) == 3


class TestRandomMode:
    """The random=True escape hatch documented in the README and
    docs/architecture.md. We can't easily test the empirical-distribution
    flattening end-to-end in a smoke test (city/state space is too big),
    but we can confirm the flag is plumbed through and the sampler still
    produces the same output shape."""

    def test_random_mode_returns_same_shape(self):
        result = _sample(qty=1, random=True)
        assert isinstance(result, dict)
        for key in ('name', 'city', 'state', 'state_abbr', 'cpf', 'rg'):
            assert key in result

    def test_random_mode_batch(self):
        results = _sample(qty=5, random=True)
        assert isinstance(results, list)
        assert len(results) == 5
        for r in results:
            assert r['name']
            assert r['city']

    def test_random_mode_default_is_false(self):
        # Smoke-check: omitting ``random`` keyword keeps realistic path.
        result = _sample(qty=1)
        assert isinstance(result, dict)


class TestUfSexConditioningNameOnly:
    """``experimental_uf_sex_conditioning`` reaches the name-only path too."""

    def _spy(self, monkeypatch):
        from ptbr_sampler.br_name_class import BrazilianNameSampler

        calls: list[dict] = []
        original = BrazilianNameSampler.get_random_name

        def spy(self, *args, **kwargs):
            calls.append(kwargs)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(BrazilianNameSampler, 'get_random_name', spy)
        return calls

    def test_name_only_draw_receives_the_row_uf_and_a_sex(self, monkeypatch):
        calls = self._spy(monkeypatch)
        results = _sample(qty=3, return_only_name=True, experimental_uf_sex_conditioning=True)

        assert len(calls) == 3
        for call, row in zip(calls, results, strict=True):
            assert call['uf'] == row['state_abbr']
            assert call['sex'] in ('M', 'F')

    def test_name_only_draw_is_unconditioned_by_default(self, monkeypatch):
        calls = self._spy(monkeypatch)
        _sample(qty=2, return_only_name=True)

        assert [(c['uf'], c['sex']) for c in calls] == [(None, None), (None, None)]

    @pytest.mark.parametrize('fork', ['only_surname', 'only_middle'])
    def test_surname_and_middle_forks_draw_no_sex(self, monkeypatch, fork):
        """Those forks never read a sex, so the flag must not spend RNG draws on one."""
        import ptbr_sampler.sampler as sampler_module

        flips: list[int] = []
        monkeypatch.setattr(sampler_module, '_coin_flip_sexes', lambda n: flips.append(n) or ['F'] * n)
        _sample(qty=2, experimental_uf_sex_conditioning=True, **{fork: True})

        assert flips == []

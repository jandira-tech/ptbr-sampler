"""Tests for the optional ptbr_sampler.faker provider and install_ptbr helper."""

from __future__ import annotations

import importlib
import random
import subprocess
import sys
import warnings

import pytest
from faker import Faker
from faker.providers import BaseProvider

from ptbr_sampler import TimePeriod
from ptbr_sampler.datasets import ensure_data_file
from ptbr_sampler.faker import PTBRProvider, install_ptbr
from ptbr_sampler.utils.cei import validate_cei
from ptbr_sampler.utils.cnpj import validate_cnpj
from ptbr_sampler.utils.cpf import validate_cpf
from ptbr_sampler.utils.pis import validate_pis


def _make_fake(**options) -> Faker:
    fake = Faker('pt_BR')
    fake.seed_instance(2026)
    return install_ptbr(fake, **options)


def test_base_package_import_does_not_require_faker() -> None:
    code = """
import importlib.abc
import sys

class BlockFaker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'faker' or fullname.startswith('faker.'):
            raise ModuleNotFoundError("No module named 'faker'")
        return None

sys.meta_path.insert(0, BlockFaker())
import ptbr_sampler
assert 'faker' not in sys.modules
assert not hasattr(ptbr_sampler, 'PTBRProvider')
try:
    import ptbr_sampler.faker
except ImportError as exc:
    assert 'ptbr-sampler[faker]' in str(exc) or 'faker' in str(exc).lower()
else:
    raise AssertionError('Expected ImportError when faker is unavailable')
"""
    res = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)
    assert res.returncode == 0, f'stdout={res.stdout}\nstderr={res.stderr}'


def test_public_provider_api_and_complete_profile() -> None:
    fake = _make_fake()
    assert isinstance(fake, Faker)

    profile = fake.ptbr_profile()
    expected_keys = {
        'name',
        'middle_name',
        'surnames',
        'city',
        'state',
        'state_abbr',
        'cep',
        'street',
        'neighborhood',
        'building_number',
        'cpf',
        'rg',
        'pis',
        'cnpj',
        'cei',
        'phone',
    }
    assert set(profile.keys()) == expected_keys
    assert profile['name']
    assert profile['surnames']
    assert profile['city']
    assert len(profile['state_abbr']) == 2
    assert '-' in profile['cep'] and len(profile['cep']) == 9
    assert validate_cpf(profile['cpf'])
    assert validate_pis(profile['pis'])
    assert validate_cnpj(profile['cnpj'])
    assert validate_cei(profile['cei'])
    assert profile['rg']
    assert profile['phone'].startswith('(')

    assert fake.ptbr_name()
    assert fake.ptbr_first_name()
    assert fake.ptbr_middle_name()
    assert fake.ptbr_surname()
    assert fake.ptbr_city()
    assert fake.ptbr_state()
    assert len(fake.ptbr_state_abbr()) == 2
    assert len(fake.ptbr_cep()) == 9
    assert len(fake.ptbr_postcode()) == 9
    assert '\n' in fake.ptbr_address()
    assert fake.ptbr_street()
    assert fake.ptbr_neighborhood()
    assert fake.ptbr_building_number().isdigit()
    assert fake.ptbr_phone().startswith('(')
    assert fake.ptbr_phone_number().startswith('(')


def test_profile_location_cep_rg_and_ddd_are_internally_coherent() -> None:
    import json

    cities_payload = json.loads(ensure_data_file('cities_with_ceps.json').read_text(encoding='utf-8'))
    cities_by_name = {c['city_name']: c for c in cities_payload['cities'].values()}
    states_by_name = cities_payload['states']

    fake = _make_fake(uf_conditioning=True)
    for _ in range(10):
        p = fake.ptbr_profile()
        assert states_by_name[p['state']]['state_abbr'] == p['state_abbr']
        city_meta = cities_by_name[p['city']]
        assert city_meta['city_uf'] == p['state_abbr']
        ddd = str(city_meta['ddd'])
        assert p['phone'].startswith(f'({ddd}) ')
        expected_issuer = 'DETRAN-RJ' if p['state_abbr'] == 'RJ' else f"SSP-{p['state_abbr']}"
        assert expected_issuer in p['rg']


@pytest.mark.parametrize(
    ('method_name', 'validator', 'digits_len'),
    [
        ('ptbr_cpf', validate_cpf, 11),
        ('ptbr_pis', validate_pis, 11),
        ('ptbr_cnpj', validate_cnpj, 14),
        ('ptbr_cei', validate_cei, 12),
    ],
)
def test_documents_validate_and_support_call_level_formatting(method_name: str, validator, digits_len: int) -> None:
    fake = _make_fake()
    formatted_val = getattr(fake, method_name)(formatted=True)
    raw_val = getattr(fake, method_name)(formatted=False)
    assert validator(formatted_val)
    assert validator(raw_val)
    assert not formatted_val.isdigit()
    assert raw_val.isdigit() and len(raw_val) == digits_len

    rg_fmt = fake.ptbr_rg(formatted=True)
    rg_raw = fake.ptbr_rg(formatted=False)
    assert not rg_fmt.isdigit()
    assert rg_raw.isdigit()


def test_provider_level_formatting_and_cep_dash_options() -> None:
    fake = _make_fake(formatted=False, cep_without_dash=True)
    p = fake.ptbr_profile()
    assert p['cpf'].isdigit() and len(p['cpf']) == 11
    assert p['cnpj'].isdigit() and len(p['cnpj']) == 14
    assert p['pis'].isdigit() and len(p['pis']) == 11
    assert p['cei'].isdigit() and len(p['cei']) == 12
    assert p['rg'].isdigit()
    assert p['cep'].isdigit() and len(p['cep']) == 8
    assert fake.ptbr_cep().isdigit()
    assert '-' in fake.ptbr_cep(cep_without_dash=False)


def test_conditioning_options_validation_and_forwarding() -> None:
    fake_rj = _make_fake(uf='RJ', sex_conditioning='F', conditioning_mode='estimated')
    profiles = [fake_rj.ptbr_profile() for _ in range(6)]
    assert all(p['state_abbr'] == 'RJ' for p in profiles)

    fake_hist = _make_fake(time_period=TimePeriod.UNTIL_1980)
    assert fake_hist.ptbr_first_name()

    with pytest.raises(ValueError, match='conditioning_mode'):
        _make_fake(uf='RJ', sex_conditioning='F', conditioning_mode='strict')

    with pytest.raises(ValueError, match='Unknown UF'):
        _make_fake(uf='ZZ')

    with pytest.raises(ValueError, match='not supported for census_year=2022'):
        _make_fake(census_year=2022, time_period=TimePeriod.UNTIL_1930)

    with pytest.raises(TypeError, match='Unsupported PTBRProvider option'):
        _make_fake(nonexistent_flag=True)


def test_canonical_options_take_precedence_over_aliases() -> None:
    fake_a = Faker('pt_BR')
    install_ptbr(fake_a, random=False, uniform=True, top_40=True, top40=False, sex_conditioning='F', sex='M')
    fake_b = Faker('pt_BR')
    install_ptbr(fake_b, random=False, top_40=True, sex_conditioning='F')

    fake_a.seed_instance(808)
    fake_b.seed_instance(808)
    assert [fake_a.ptbr_profile() for _ in range(4)] == [fake_b.ptbr_profile() for _ in range(4)]


@pytest.mark.parametrize('seed_mode', ['class_seed', 'instance_seed'])
def test_seeding_reproduces_profiles_and_scalars_across_fresh_instances(seed_mode: str) -> None:
    def run_once() -> tuple[list[dict], list[str], list[str]]:
        if seed_mode == 'class_seed':
            Faker.seed(5150)
            f = install_ptbr(Faker('pt_BR'), uf_conditioning=True)
        else:
            f = install_ptbr(Faker('pt_BR'), uf_conditioning=True)
            f.seed_instance(5150)
        return (
            [f.ptbr_profile() for _ in range(3)],
            [f.ptbr_name() for _ in range(4)],
            [f.ptbr_cpf() for _ in range(4)],
        )

    first_run = run_once()
    second_run = run_once()
    assert first_run == second_run


def test_global_random_seed_does_not_affect_seeded_provider() -> None:
    f1 = install_ptbr(Faker('pt_BR'))
    f1.seed_instance(9001)
    random.seed(1)
    seq_1 = [f1.ptbr_profile() for _ in range(3)]

    f2 = install_ptbr(Faker('pt_BR'))
    f2.seed_instance(9001)
    random.seed(999999)
    seq_2 = [f2.ptbr_profile() for _ in range(3)]

    assert seq_1 == seq_2


def test_default_install_never_overrides_standard_pt_br_methods() -> None:
    baseline = Faker('pt_BR')
    baseline.seed_instance(1234)
    expected = (baseline.name(), baseline.city(), baseline.cpf())

    installed = Faker('pt_BR')
    install_ptbr(installed, aliases=False)
    installed.seed_instance(1234)
    actual = (installed.name(), installed.city(), installed.cpf())

    assert actual == expected


@pytest.mark.parametrize('locales', ['pt_BR', ['pt_BR', 'en_US']])
def test_aliases_install_and_reinstall_cleanup_while_preserving_third_party_providers(locales) -> None:
    class CustomNameProvider(BaseProvider):
        def custom_tag(self) -> str:
            return 'CUSTOM_OK'

    fake = Faker(locales)
    install_ptbr(fake, aliases=True, uf='SP', formatted=False)
    for leaf in list(fake.factories) if getattr(fake, 'factories', None) else [fake]:
        leaf.add_provider(CustomNameProvider)

    assert fake.state_abbr() == 'SP'
    assert fake.cpf().isdigit() and len(fake.cpf()) == 11
    assert fake.custom_tag() == 'CUSTOM_OK'

    # Re-installing with aliases=False must replace previous PTBRProvider and restore standard formatters
    install_ptbr(fake, aliases=False, uf='BA', formatted=True)
    assert fake.ptbr_state_abbr() == 'BA'
    assert not fake.ptbr_cpf().isdigit()
    assert fake.custom_tag() == 'CUSTOM_OK'

    # None of the leaf generators should retain multiple PTBRProvider instances
    from ptbr_sampler.faker import _iter_leaf_generators

    for leaf in _iter_leaf_generators(fake):
        ptbr_providers = [p for p in leaf.providers if isinstance(p, PTBRProvider)]
        assert len(ptbr_providers) == 1
        assert type(ptbr_providers[0]) is PTBRProvider


def test_fast_scalar_methods_skip_unrelated_work(mocker) -> None:
    import ptbr_sampler.sampler as sampler_mod

    fake = _make_fake()
    spy_doc = mocker.spy(sampler_mod.DocumentSampler, 'generate_cpf')
    spy_addr = mocker.spy(sampler_mod, '_generate_offline_address_batch')

    first = fake.ptbr_first_name()
    city = fake.ptbr_city()
    assert first and city
    assert spy_doc.call_count == 0
    assert spy_addr.call_count == 0


@pytest.mark.asyncio
async def test_faker_provider_methods_run_inside_active_asyncio_loop() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        fake = _make_fake(uf='PR')
        p = fake.ptbr_profile()
        n = fake.ptbr_name()
        c = fake.ptbr_city()
        doc = fake.ptbr_cpf()
    assert p['state_abbr'] == 'PR'
    assert n and c and validate_cpf(doc)
    assert [w for w in caught if 'never awaited' in str(w.message)] == []
    assert importlib.import_module('ptbr_sampler.faker').PTBRProvider is PTBRProvider


def test_install_ptbr_invalidates_multilocale_cached_method_mapping() -> None:
    fake = Faker(['pt_BR', 'en_US'])
    assert not hasattr(fake, 'ptbr_cpf')
    assert '_cached_ptbr_cpf_mapping' in fake.__dict__

    install_ptbr(fake)
    assert hasattr(fake, 'ptbr_cpf')
    assert validate_cpf(fake.ptbr_cpf())


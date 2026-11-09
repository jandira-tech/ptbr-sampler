"""Integration tests for the optional Faker provider adapter."""

import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

faker = pytest.importorskip('faker')

from faker import Faker
from faker.providers import BaseProvider

from ptbr_sampler.faker import PTBRProvider, install_ptbr
from ptbr_sampler.utils.cei import validate_cei
from ptbr_sampler.utils.cnpj import validate_cnpj
from ptbr_sampler.utils.cpf import validate_cpf
from ptbr_sampler.utils.pis import validate_pis


def make_fake(**options):
    fake = Faker('pt_BR')
    install_ptbr(fake, **options)
    return fake


@pytest.mark.asyncio
@pytest.mark.filterwarnings('error::RuntimeWarning')
async def test_offline_provider_methods_work_inside_a_running_event_loop():
    fake = make_fake(uf='SP')

    profile = fake.ptbr_profile()
    assert profile['state_abbr'] == 'SP'
    assert fake.ptbr_first_name()
    assert fake.ptbr_city()  # scalar fields also avoid asyncio.run in offline mode
    assert validate_cpf(fake.ptbr_cpf())
    assert fake.ptbr_address()


@pytest.mark.asyncio
@pytest.mark.filterwarnings('error::RuntimeWarning')
async def test_online_cep_inside_event_loop_fails_clearly_without_leaking_coroutine():
    fake = make_fake(make_api_call=True)

    with pytest.raises(RuntimeError, match='running event loop'):
        fake.ptbr_address()


def profile_batch(fake):
    return [fake.ptbr_profile(), fake.ptbr_name(), fake.ptbr_cpf(), fake.ptbr_city()]


def test_base_package_import_does_not_require_faker():
    root = Path(__file__).resolve().parents[1]
    code = r"""
import sys
class BlockFaker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'faker' or fullname.startswith('faker.'):
            raise ModuleNotFoundError('blocked optional faker')
sys.meta_path.insert(0, BlockFaker())
sys.path.insert(0, sys.argv[1])
import ptbr_sampler
assert not hasattr(ptbr_sampler, 'PTBRProvider')
try:
    import ptbr_sampler.faker
except ModuleNotFoundError as error:
    assert 'blocked optional faker' in str(error)
else:
    raise AssertionError('ptbr_sampler.faker must guard the optional dependency')
"""
    result = subprocess.run([sys.executable, '-I', '-c', code, str(root)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_public_provider_api_and_complete_profile():
    fake = make_fake(uf='SP')
    provider = fake.providers[0]

    assert isinstance(provider, PTBRProvider)
    profile = fake.ptbr_profile()
    assert set(profile) == {
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
    assert all(isinstance(value, str) for value in profile.values())
    assert all(profile[key] for key in ('name', 'surnames', 'city', 'state', 'cep', 'street', 'neighborhood', 'building_number'))
    assert profile['state_abbr'] == 'SP'
    assert re.fullmatch(r'\d{5}-\d{3}', profile['cep'])
    assert re.fullmatch(r'\(\d{2}\) \d{4,5}-\d{4}', profile['phone'])

    full_name = fake.ptbr_name()
    assert isinstance(full_name, str)
    assert len(full_name.split()) >= 2
    for method_name in (
        'ptbr_first_name',
        'ptbr_middle_name',
        'ptbr_surname',
        'ptbr_city',
        'ptbr_state',
        'ptbr_state_abbr',
        'ptbr_cep',
        'ptbr_postcode',
        'ptbr_address',
        'ptbr_street',
        'ptbr_neighborhood',
        'ptbr_building_number',
        'ptbr_rg',
        'ptbr_phone',
        'ptbr_phone_number',
    ):
        value = getattr(fake, method_name)()
        assert isinstance(value, str), method_name
        assert value, method_name


def test_profile_name_location_cep_and_ddd_are_internally_coherent():
    fake = make_fake(uf='RJ', always_middle=True)
    profile = fake.ptbr_profile()

    assert profile['state_abbr'] == 'RJ'
    assert profile['state'] == 'Rio de Janeiro'
    assert profile['cep'][:2] in {'20', '21', '22', '23', '24', '25', '26', '27', '28'}
    ddd = profile['phone'][1:3]
    assert ddd in {'21', '22', '24'}
    full_name = ' '.join(part for part in (profile['name'], profile['middle_name'], profile['surnames']) if part)
    assert full_name.split()[-1] in profile['surnames']


@pytest.mark.parametrize(
    ('method_name', 'validator', 'digits'),
    [
        ('ptbr_cpf', validate_cpf, 11),
        ('ptbr_pis', validate_pis, 11),
        ('ptbr_cnpj', validate_cnpj, 14),
        ('ptbr_cei', validate_cei, 12),
    ],
)
def test_documents_are_valid_and_support_call_level_formatting(method_name, validator, digits):
    fake = make_fake()

    formatted = getattr(fake, method_name)()
    unformatted = getattr(fake, method_name)(formatted=False)
    assert validator(formatted)
    assert validator(unformatted)
    assert re.fullmatch(rf'\d{{{digits}}}', unformatted)
    assert not formatted.isdigit()


def test_factory_formatting_default_and_cep_formatting_are_configurable():
    fake = make_fake(formatted=False, cep_without_dash=True)

    assert fake.ptbr_cpf().isdigit()
    assert not fake.ptbr_cpf(formatted=True).isdigit()
    assert re.fullmatch(r'\d{8}', fake.ptbr_cep())
    assert re.fullmatch(r'\d{8}', fake.ptbr_profile()['cep'])
    assert re.fullmatch(r'\d{8}', fake.ptbr_address().rsplit(' ', 1)[-1])
    assert re.fullmatch(r'\d{5}-\d{3}', fake.ptbr_cep(cep_without_dash=False))


def test_sampler_configuration_and_period_conflict_are_forwarded():
    fake = make_fake(cohort='current', time_period='ate1950', sex_conditioning='F', uniform=True, top40=True, uf='SP')
    profile = fake.ptbr_profile()

    assert profile['state_abbr'] == 'SP'
    assert profile['surnames']
    conflicting = make_fake(cohort='census2022', time_period='ate1950')
    with pytest.raises(ValueError, match='cannot be combined'):
        conflicting.ptbr_profile()


@pytest.mark.parametrize('seed_method', ['class', 'instance'])
def test_seeding_reproduces_profiles_and_components_across_fresh_instances(seed_method):
    def generate():
        fake = make_fake(uf='SP')
        if seed_method == 'class':
            Faker.seed(827)
        else:
            fake.seed_instance(827)
        return profile_batch(fake)

    assert generate() == generate()


def test_global_random_seed_does_not_change_seeded_provider_output():
    fake = make_fake(uf='SP')
    fake.seed_instance(991)
    random.seed(1)
    expected = profile_batch(fake)

    fake.seed_instance(991)
    random.seed(999999)
    assert profile_batch(fake) == expected


def test_installations_do_not_share_configuration_or_alias_methods():
    sp = make_fake(uf='SP', aliases=True, formatted=False)
    rj = make_fake(uf='RJ')

    assert sp.ptbr_state_abbr() == 'SP'
    assert rj.ptbr_state_abbr() == 'RJ'
    assert sp.ptbr_cpf().isdigit()
    assert not rj.ptbr_cpf().isdigit()
    assert rj.cpf.__self__.__class__.__module__.startswith('faker.providers')
    assert sp.cpf.__self__.__class__.__module__ == 'ptbr_sampler.faker'
    assert isinstance(sp.name(), str)
    assert isinstance(sp.first_name(), str)
    assert isinstance(sp.last_name(), str)
    assert isinstance(sp.city(), str)
    assert isinstance(sp.state(), str)
    assert isinstance(sp.postcode(), str)
    assert isinstance(sp.cpf(), str)
    assert isinstance(sp.cnpj(), str)
    assert isinstance(sp.pis(), str)
    assert isinstance(sp.phone_number(), str)
    assert sp.ptbr_profile()


def test_default_install_never_changes_standard_pt_br_results_or_methods():
    native = Faker('pt_BR')
    native.seed_instance(1234)
    expected = (native.name(), native.first_name(), native.last_name(), native.city(), native.state(), native.postcode())
    expected_methods = set(dir(native))

    other = Faker('pt_BR')
    install_ptbr(other)
    native.seed_instance(1234)
    actual = (native.name(), native.first_name(), native.last_name(), native.city(), native.state(), native.postcode())

    assert actual == expected
    assert set(dir(native)) == expected_methods
    assert other.cpf.__self__.__class__.__module__.startswith('faker.providers')


@pytest.mark.parametrize('locales', ['pt_BR', ['pt_BR', 'en_US']])
def test_repeated_install_replaces_participating_providers_and_aliases(locales):
    fake = Faker(locales)
    for index in range(100):
        install_ptbr(fake, aliases=index % 2 == 0, uf='SP' if index % 2 == 0 else 'RJ')

    for factory in fake._factories:
        participating = [provider for provider in factory.providers if isinstance(provider, PTBRProvider)]
        assert len(participating) == 1
        assert participating[0]._options['uf'] == 'RJ'
        assert factory.ptbr_state_abbr() == 'RJ'
        assert not isinstance(factory.state_abbr.__self__, PTBRProvider)


def leaf_generators(fake):
    """Expose each actual Faker Generator behind possibly nested proxies."""
    for factory in fake._factories:
        nested = getattr(factory, '_factories', None)
        if nested:
            yield from leaf_generators(factory)
        else:
            yield factory


@pytest.mark.parametrize('locales', ['pt_BR', ['pt_BR', 'en_US']])
def test_proxy_reinstall_removes_aliases_from_every_underlying_generator(locales):
    fake = Faker(locales)
    install_ptbr(fake, aliases=True)
    install_ptbr(fake, aliases=False)

    for generator in leaf_generators(fake):
        assert len([provider for provider in generator.providers if isinstance(provider, PTBRProvider)]) == 1
        for alias in ('cpf', 'cnpj', 'pis', 'state_abbr'):
            formatter = getattr(generator, alias, None)
            assert formatter is None or not isinstance(formatter.__self__, PTBRProvider), (alias, formatter)


@pytest.mark.parametrize('locales', ['pt_BR', ['pt_BR', 'en_US']])
def test_reinstall_preserves_later_third_party_formatter_overrides(locales):
    class OtherProvider(BaseProvider):
        def name(self):
            return 'other-provider'

    fake = Faker(locales)
    install_ptbr(fake, aliases=True, uf='SP')
    generators = list(leaf_generators(fake))
    for generator in generators:
        generator.add_provider(OtherProvider)
        assert generator.name() == 'other-provider'

    install_ptbr(fake, aliases=False, uf='RJ')

    for generator in generators:
        assert generator.name() == 'other-provider'
        assert isinstance(generator.name.__self__, OtherProvider)
        assert generator.ptbr_state_abbr() == 'RJ'


def test_canonical_options_take_precedence_over_legacy_aliases():
    fake = make_fake(random=True, uniform=False, top_40=True, top40=False)
    options = fake.providers[0]._options

    assert options['random'] is True
    assert options['top_40'] is True
    assert 'uniform' not in options
    assert 'top40' not in options


def test_first_name_skips_full_profile_address_and_document_operations(mocker):
    address_async = mocker.patch('ptbr_sampler.sampler.get_address_data_batch', new_callable=mocker.AsyncMock)
    address_sync = mocker.patch('ptbr_sampler.sampler._get_offline_address_data_batch', create=True)
    batch_names = mocker.patch('ptbr_sampler.br_name_class.BrazilianNameSampler.batch_sample_names')
    cpf = mocker.patch('ptbr_sampler.document_sampler.DocumentSampler.generate_cpf')
    fake = make_fake()

    assert fake.ptbr_first_name()
    address_async.assert_not_called()
    address_sync.assert_not_called()
    batch_names.assert_not_called()
    cpf.assert_not_called()


def test_city_skips_name_address_and_document_operations(mocker):
    address_async = mocker.patch('ptbr_sampler.sampler.get_address_data_batch', new_callable=mocker.AsyncMock)
    address_sync = mocker.patch('ptbr_sampler.sampler._get_offline_address_data_batch', create=True)
    get_name = mocker.patch('ptbr_sampler.br_name_class.BrazilianNameSampler.get_random_name')
    batch_names = mocker.patch('ptbr_sampler.br_name_class.BrazilianNameSampler.batch_sample_names')
    cpf = mocker.patch('ptbr_sampler.document_sampler.DocumentSampler.generate_cpf')
    fake = make_fake(uf='SP')

    assert fake.ptbr_city()
    address_async.assert_not_called()
    address_sync.assert_not_called()
    get_name.assert_not_called()
    batch_names.assert_not_called()
    cpf.assert_not_called()


def test_repeated_scalar_calls_are_deterministic_for_fixed_seed_and_configuration():
    def generate():
        fake = make_fake(uf='SP', cohort='census2022', formatted=False)
        fake.seed_instance(144)
        return [fake.ptbr_first_name(), fake.ptbr_city(), fake.ptbr_cpf(), fake.ptbr_street()]

    assert generate() == generate()


def test_multi_locale_proxy_uses_public_generator_provider_api_without_cross_contamination():
    sp = Faker(['pt_BR', 'en_US'])
    rj = Faker(['pt_BR', 'en_US'])
    install_ptbr(sp, uf='SP')
    install_ptbr(rj, uf='RJ')

    for factory in sp._factories:
        factory.seed_instance(82)
        assert factory.ptbr_state_abbr() == 'SP'
    for factory in rj._factories:
        factory.seed_instance(82)
        assert factory.ptbr_state_abbr() == 'RJ'
    assert sp.ptbr_profile()['state_abbr'] == 'SP'
    assert rj.ptbr_profile()['state_abbr'] == 'RJ'

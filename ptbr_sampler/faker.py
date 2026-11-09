"""Optional `Faker <https://faker.readthedocs.io/>`_ integration.

Install the extra with ``pip install 'ptbr-sampler[faker]'`` and register the
provider on each Faker instance that should use it::

    from faker import Faker
    from ptbr_sampler.faker import install_ptbr

    fake = Faker('pt_BR')
    install_ptbr(fake, uf='SP', cohort='current')
    fake.seed_instance(42)
    profile = fake.ptbr_profile()  # A coherent dict of strings.
    cpf = fake.ptbr_cpf(formatted=False)  # Eleven digits.

No Faker locale is modified. Importing :mod:`ptbr_sampler` itself does not
import this module, so Faker remains an optional runtime dependency.
"""

import re
from pathlib import Path
from typing import Any

from faker.providers import BaseProvider

from ptbr_sampler.br_name_class import Cohort
from ptbr_sampler.sampler import sample

_DATA_DIR = Path(__file__).resolve().parent / 'data'

# These are the public sample.py wrapper's defaults, expressed against the
# packaged public sampler so installed wheels do not depend on a top-level
# checkout-only module. Provider methods only choose sampling branches; all
# random generation remains in the existing sampler and its injected RNG.
_SAMPLE_DEFAULTS: dict[str, Any] = {
    'qty': 1,
    'q': None,
    'city_only': False,
    'state_abbr_only': False,
    'state_full_only': False,
    'only_cep': False,
    'cep_without_dash': False,
    'make_api_call': False,
    'time_period': None,
    'cohort': Cohort.CURRENT,
    'uf': None,
    'return_only_name': False,
    'name_raw': False,
    'json_path': _DATA_DIR / 'cities_with_ceps.json',
    'names_path': _DATA_DIR / 'names_data.json',
    'middle_names_path': _DATA_DIR / 'middle_names.json',
    'only_surname': False,
    'top_40': False,
    'with_only_one_surname': False,
    'always_middle': False,
    'only_middle': False,
    'always_cpf': False,
    'always_pis': False,
    'always_cnpj': False,
    'always_cei': False,
    'always_rg': False,
    'always_phone': False,
    'only_cpf': False,
    'only_pis': False,
    'only_cnpj': False,
    'only_cei': False,
    'only_rg': False,
    'only_fone': False,
    'include_issuer': True,
    'only_document': False,
    'surnames_path': _DATA_DIR / 'surnames_data.json',
    'locations_path': _DATA_DIR / 'locations_data.json',
    'save_to_jsonl': None,
    'all_data': False,
    'random': False,
    'experimental_uf_sex_conditioning': False,
    'sex_conditioning': None,
    'include_address': True,
    'location_only': False,
}

_DOCUMENT_KEYS = ('cpf', 'pis', 'cnpj', 'cei', 'rg')


class PTBRProvider(BaseProvider):
    """Brazilian profiles backed exclusively by :func:`ptbr_sampler.sampler.sample`.

    ``ptbr_profile()`` returns a ``dict[str, str]`` with the sampler's sixteen
    standard keys. Every other ``ptbr_*`` method returns one independent
    string. A full name is the first, optional middle, and surname components
    joined with spaces; an address is ``street, number - neighborhood,
    city - UF, CEP``. Document methods accept ``formatted=True/False``;
    ``None`` (the default) inherits the installation's ``formatted`` option.
    """

    _options: dict[str, Any] = {}

    def _sample(self, **overrides: Any) -> dict[str, str]:
        options = {**_SAMPLE_DEFAULTS, **self._options, **overrides, 'rng': self.generator.random}
        options.pop('formatted', None)
        result = sample(**options)
        if not isinstance(result, dict):  # pragma: no cover - qty is always one
            raise TypeError('PTBRProvider expected one sample')
        return result

    def _formatted(self, formatted: bool | None) -> bool:
        return self._options.get('formatted', True) if formatted is None else formatted

    @staticmethod
    def _digits(value: str) -> str:
        return re.sub(r'\D', '', value)

    def ptbr_profile(self) -> dict[str, str]:
        """Return one coherent full profile as a dictionary of strings.

        UF, city, CEP, DDD/phone, RG, first name, and surnames all come from
        the same sampler row. For example, ``install_ptbr(fake, uf='RJ')``
        guarantees ``profile['state_abbr'] == 'RJ'``.
        """
        profile = self._sample(all_data=True)
        if not self._formatted(None):
            for key in _DOCUMENT_KEYS:
                profile[key] = self._digits(profile[key])
        if self._options.get('cep_without_dash', False):
            profile['cep'] = self._digits(profile['cep'])
        return profile

    def ptbr_name(self) -> str:
        """Return a full name, joining non-empty name components with spaces."""
        row = self._sample(return_only_name=True, include_address=False)
        return ' '.join(part for part in (row['name'], row['middle_name'], row['surnames']) if part)

    def ptbr_first_name(self) -> str:
        """Return one non-empty first name as a string."""
        return self._sample(return_only_name=True, include_address=False)['name']

    def ptbr_middle_name(self) -> str:
        """Return one non-empty middle name using the dedicated sampler branch."""
        return self._sample(only_middle=True, include_address=False)['middle_name']

    def ptbr_surname(self) -> str:
        """Return one non-empty surname (possibly a compound surname)."""
        return self._sample(only_surname=True, include_address=False)['surnames']

    def ptbr_city(self) -> str:
        """Return a city name as a string."""
        return self._sample(city_only=True, location_only=True, include_address=False)['city']

    def ptbr_state(self) -> str:
        """Return a full federative-unit name as a string."""
        return self._sample(state_full_only=True, location_only=True, include_address=False)['state']

    def ptbr_state_abbr(self) -> str:
        """Return a two-letter federative-unit abbreviation."""
        return self._sample(state_abbr_only=True, location_only=True, include_address=False)['state_abbr']

    def ptbr_cep(self, *, cep_without_dash: bool | None = None) -> str:
        """Return a CEP string, overriding installation formatting if requested."""
        options = {} if cep_without_dash is None else {'cep_without_dash': cep_without_dash}
        value = self._sample(only_cep=True, location_only=True, include_address=False, **options)['cep']
        without_dash = self._options.get('cep_without_dash', False) if cep_without_dash is None else cep_without_dash
        return self._digits(value) if without_dash else value

    def ptbr_postcode(self, *, cep_without_dash: bool | None = None) -> str:
        """Return a CEP; Faker-style postcode synonym for :meth:`ptbr_cep`."""
        return self.ptbr_cep(cep_without_dash=cep_without_dash)

    def ptbr_address(self) -> str:
        """Return one internally coherent formatted street address string."""
        row = self._sample()
        cep = self._digits(row['cep']) if self._options.get('cep_without_dash', False) else row['cep']
        return f'{row["street"]}, {row["building_number"]} - {row["neighborhood"]}, {row["city"]} - {row["state_abbr"]}, {cep}'

    def ptbr_street(self) -> str:
        """Return a non-empty street name."""
        return self._sample()['street']

    def ptbr_neighborhood(self) -> str:
        """Return a non-empty neighborhood name."""
        return self._sample()['neighborhood']

    def ptbr_building_number(self) -> str:
        """Return a non-empty building number string."""
        return self._sample()['building_number']

    def _document(self, key: str, flag: str, formatted: bool | None) -> str:
        value = self._sample(only_document=True, include_address=False, **{flag: True})[key]
        return value if self._formatted(formatted) else self._digits(value)

    def ptbr_cpf(self, formatted: bool | None = None) -> str:
        """Return a valid CPF; ``formatted=False`` returns exactly 11 digits."""
        return self._document('cpf', 'only_cpf', formatted)

    def ptbr_rg(self, formatted: bool | None = None) -> str:
        """Return an RG string; ``formatted=False`` removes punctuation/issuer."""
        return self._document('rg', 'only_rg', formatted)

    def ptbr_pis(self, formatted: bool | None = None) -> str:
        """Return a valid PIS/PASEP; unformatted output has 11 digits."""
        return self._document('pis', 'only_pis', formatted)

    def ptbr_cnpj(self, formatted: bool | None = None) -> str:
        """Return a valid CNPJ; unformatted output has 14 digits."""
        return self._document('cnpj', 'only_cnpj', formatted)

    def ptbr_cei(self, formatted: bool | None = None) -> str:
        """Return a valid CEI; unformatted output has 12 digits."""
        return self._document('cei', 'only_cei', formatted)

    def ptbr_phone(self) -> str:
        """Return a phone string whose DDD belongs to its sampled city."""
        return self._sample(only_document=True, only_fone=True, include_address=False)['phone']

    def ptbr_phone_number(self) -> str:
        """Return a phone string; synonym for :meth:`ptbr_phone`."""
        return self.ptbr_phone()


_ALIAS_NAMES = (
    'name',
    'first_name',
    'last_name',
    'city',
    'state',
    'state_abbr',
    'postcode',
    'address',
    'cpf',
    'cnpj',
    'pis',
    'phone_number',
)
_MISSING_FORMATTER = object()


class _AliasPTBRProvider(PTBRProvider):
    """Opt-in standard method aliases, added only to an explicit Faker instance."""

    def name(self) -> str:
        return self.ptbr_name()

    def first_name(self) -> str:
        return self.ptbr_first_name()

    def last_name(self) -> str:
        return self.ptbr_surname()

    def city(self) -> str:
        return self.ptbr_city()

    def state(self) -> str:
        return self.ptbr_state()

    def state_abbr(self) -> str:
        return self.ptbr_state_abbr()

    def postcode(self, *, cep_without_dash: bool | None = None) -> str:
        return self.ptbr_postcode(cep_without_dash=cep_without_dash)

    def address(self) -> str:
        return self.ptbr_address()

    def cpf(self, formatted: bool | None = None) -> str:
        return self.ptbr_cpf(formatted)

    def cnpj(self, formatted: bool | None = None) -> str:
        return self.ptbr_cnpj(formatted)

    def pis(self, formatted: bool | None = None) -> str:
        return self.ptbr_pis(formatted)

    def phone_number(self) -> str:
        return self.ptbr_phone()


def _leaf_generators(fake: Any):
    """Yield actual generators owned by this instance, through nested proxies."""
    factories = getattr(fake, '_factories', None)
    if not factories:
        yield fake
        return
    for factory in factories:
        yield from _leaf_generators(factory)


def install_ptbr(fake: Any, aliases: bool = False, **options: Any) -> Any:
    """Install a newly configured provider on one Faker instance and return it.

    Options are forwarded to the public sampler: ``cohort``, ``time_period``,
    ``uf``, ``sex_conditioning``, ``random`` (or ``uniform``), ``top40`` (or
    ``top_40``); canonical ``random``/``top_40`` values win if both forms are
    supplied. Also accepts ``name_raw``, ``always_middle``, ``with_only_one_surname``,
    ``cep_without_dash``, and ``include_issuer``. The adapter-only
    ``formatted=False`` selects unformatted documents by default; individual
    document calls can override it with ``formatted=True``.

    ``aliases=False`` installs only ``ptbr_*`` methods. ``aliases=True`` also
    overrides standard methods *on this Faker instance only*. Multi-locale
    proxies are supported by calling each underlying generator's public
    ``add_provider`` API; every generator retains its own random stream.
    """
    normalized = dict(options)
    top40 = normalized.pop('top40', None)
    if 'top40' in options and 'top_40' not in normalized:
        normalized['top_40'] = top40
    uniform = normalized.pop('uniform', None)
    if 'uniform' in options and 'random' not in normalized:
        normalized['random'] = uniform

    base = _AliasPTBRProvider if aliases else PTBRProvider
    provider_type = type('ConfiguredPTBRProvider', (base,), {'_options': normalized})
    for generator in _leaf_generators(fake):
        previous = [provider for provider in generator.providers if isinstance(provider, PTBRProvider)]
        for provider in previous:
            for name, formatter in getattr(provider, '_original_formatters', {}).items():
                current = getattr(generator, name, None)
                if getattr(current, '__self__', None) is not provider:
                    continue
                if formatter is _MISSING_FORMATTER:
                    generator.__dict__.pop(name, None)
                else:
                    generator.set_formatter(name, formatter)
            generator.providers.remove(provider)

        provider = provider_type(generator)
        provider._original_formatters = {name: getattr(generator, name, _MISSING_FORMATTER) for name in _ALIAS_NAMES} if aliases else {}
        generator.add_provider(provider)
    return fake


__all__ = ['PTBRProvider', 'install_ptbr']

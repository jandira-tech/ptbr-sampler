"""Optional Faker integration for ``ptbr-sampler``.

Install with ``pip install "ptbr-sampler[faker]"``.

Usage::

    from faker import Faker
    from ptbr_sampler.faker import PTBRProvider, install_ptbr

    fake = install_ptbr(Faker('pt_BR'))
    fake.seed_instance(42)
    profile = fake.ptbr_profile()
    cpf = fake.ptbr_cpf()
"""

from __future__ import annotations

import random as _stdlib_random
from typing import Any, Literal, cast

try:
    from faker import Faker
    from faker.providers import BaseProvider
except ImportError as exc:  # pragma: no cover - verified via subprocess in test_faker_provider.py
    raise ImportError("Faker integration requires the optional 'faker' extra. Install it with: pip install 'ptbr-sampler[faker]'") from exc

from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import CENSUS_2022_OBSERVED_MALE_SHARE, TimePeriod, resolve_time_period
from ptbr_sampler.datasets import PACKAGE_DATA_DIR
from ptbr_sampler.document_sampler import DocumentSampler
from ptbr_sampler.sampler import (
    _get_default_location_sampler,
    _get_default_name_sampler,
)
from ptbr_sampler.sampler import (
    sample as _sampler_sample,
)
from ptbr_sampler.utils.address_for_offline import AddressProvider_for_offline
from ptbr_sampler.utils.phone import generate_phone_number

_CANONICAL_AND_ALIAS_OPTIONS: frozenset[str] = frozenset(
    {
        'census_year',
        'time_period',
        'conditioning_mode',
        'uf',
        'uf_conditioning',
        'sex_conditioning',
        'sex',
        'experimental_uf_sex_conditioning',
        'experimental_uf_sex',
        'random',
        'random_mode',
        'uniform',
        'top_40',
        'top40',
        'with_only_one_surname',
        'one_surname',
        'always_middle',
        'name_raw',
        'raw',
        'include_issuer',
        'formatted',
        'cep_without_dash',
    }
)

_ALIAS_STANDARD_METHODS: tuple[str, ...] = (
    'name',
    'first_name',
    'first_name_female',
    'first_name_male',
    'last_name',
    'city',
    'state',
    'state_abbr',
    'postcode',
    'address',
    'street_address',
    'bairro',
    'neighborhood',
    'building_number',
    'cpf',
    'cnpj',
    'rg',
    'phone_number',
)


def _pick_option(kwargs: dict[str, Any], canonical: str, *aliases: str, default: Any) -> Any:
    if canonical in kwargs:
        return kwargs[canonical]
    for alias in aliases:
        if alias in kwargs:
            return kwargs[alias]
    return default


def _parse_provider_options(options: dict[str, Any]) -> dict[str, Any]:
    unknown = set(options.keys()) - _CANONICAL_AND_ALIAS_OPTIONS
    if unknown:
        joined = ', '.join(sorted(unknown))
        raise TypeError(f'Unsupported PTBRProvider option(s): {joined}')

    census_year = int(_pick_option(options, 'census_year', default=2022))
    if census_year not in (2010, 2022):
        raise ValueError(f'census_year must be 2010 or 2022; got {census_year!r}')

    conditioning_mode = str(_pick_option(options, 'conditioning_mode', default='strict'))
    if conditioning_mode not in ('strict', 'estimated'):
        raise ValueError(f"conditioning_mode must be 'strict' or 'estimated'; got {conditioning_mode!r}")

    time_period_raw = _pick_option(options, 'time_period', default=None)
    resolved_period = resolve_time_period(time_period_raw, census_year)

    uf_norm = BrazilianLocationSampler.normalize_uf(_pick_option(options, 'uf', default=None))
    uf_conditioning = bool(_pick_option(options, 'uf_conditioning', default=False))
    experimental_uf_sex = bool(_pick_option(options, 'experimental_uf_sex_conditioning', 'experimental_uf_sex', default=False))

    sex_raw = _pick_option(options, 'sex_conditioning', 'sex', default=None)
    sex_norm: str | None = None
    if sex_raw is not None:
        sc = str(sex_raw).strip().upper()
        if sc not in ('M', 'F', 'MIXED', 'POPULATION'):
            raise ValueError(f"sex_conditioning must be 'M', 'F', 'mixed', 'population', or None; got {sex_raw!r}")
        if sc == 'POPULATION' and census_year != 2022:
            raise ValueError("sex_conditioning='population' requires census_year=2022")
        sex_norm = sc

    condition_uf = uf_conditioning or experimental_uf_sex or (uf_norm is not None)
    if census_year == 2022:
        if condition_uf and resolved_period != TimePeriod.ALL:
            raise ValueError(
                'Census 2022 does not provide UF x cohort joint distributions '
                "(time_period != 'all' cannot be combined with UF conditioning)."
            )
        if conditioning_mode == 'strict':
            if condition_uf and (sex_norm is not None or experimental_uf_sex):
                raise ValueError(
                    'Census 2022 does not publish exact UF x sex joint tables; '
                    "pass conditioning_mode='estimated' to opt into Bayes composition."
                )
            if resolved_period != TimePeriod.ALL and sex_norm is not None:
                raise ValueError(
                    'Census 2022 does not publish exact cohort x sex joint tables; '
                    "pass conditioning_mode='estimated' to opt into Bayes composition."
                )

    return {
        'census_year': census_year,
        'resolved_period': resolved_period,
        'conditioning_mode': conditioning_mode,
        'uf': uf_norm,
        'uf_conditioning': uf_conditioning,
        'sex_conditioning': sex_norm,
        'experimental_uf_sex_conditioning': experimental_uf_sex,
        'random': bool(_pick_option(options, 'random', 'random_mode', 'uniform', default=False)),
        'top_40': bool(_pick_option(options, 'top_40', 'top40', default=False)),
        'with_only_one_surname': bool(_pick_option(options, 'with_only_one_surname', 'one_surname', default=False)),
        'always_middle': bool(_pick_option(options, 'always_middle', default=False)),
        'name_raw': bool(_pick_option(options, 'name_raw', 'raw', default=False)),
        'include_issuer': bool(_pick_option(options, 'include_issuer', default=True)),
        'formatted': bool(_pick_option(options, 'formatted', default=True)),
        'cep_without_dash': bool(_pick_option(options, 'cep_without_dash', default=False)),
    }


class PTBRProvider(BaseProvider):
    """Faker provider backed by IBGE Census 2022 / 2010 distributions and Brazilian check-digit rules.

    All draws route exclusively through ``self.generator.random`` so ``Faker.seed(...)`` and
    ``fake.seed_instance(...)`` are reproducible without touching global Python or NumPy RNG state.
    """

    def __init__(self, generator: Any, **options: Any) -> None:
        parsed = _parse_provider_options(options)
        super().__init__(generator)
        self._census_year: int = parsed['census_year']
        self._resolved_period: TimePeriod = parsed['resolved_period']
        self._conditioning_mode: Literal['strict', 'estimated'] = parsed['conditioning_mode']
        self._uf: str | None = parsed['uf']
        self._uf_conditioning: bool = parsed['uf_conditioning']
        self._sex_conditioning: str | None = parsed['sex_conditioning']
        self._experimental_uf_sex: bool = parsed['experimental_uf_sex_conditioning']
        self._random_mode: bool = parsed['random']
        self._top_40: bool = parsed['top_40']
        self._with_only_one_surname: bool = parsed['with_only_one_surname']
        self._always_middle: bool = parsed['always_middle']
        self._name_raw: bool = parsed['name_raw']
        self._include_issuer: bool = parsed['include_issuer']
        self._formatted: bool = parsed['formatted']
        self._cep_without_dash: bool = parsed['cep_without_dash']
        self._doc_sampler = DocumentSampler()

    def _rng(self) -> _stdlib_random.Random:
        return self.generator.random  # type: ignore[no-any-return]

    def _location_sampler(self) -> BrazilianLocationSampler:
        return _get_default_location_sampler()

    def _name_sampler(self):
        return _get_default_name_sampler(
            census_year=self._census_year,
            conditioning_mode=self._conditioning_mode,
        )

    def _resolve_uf(self, uf: str | None, *, rng: _stdlib_random.Random, draw_if_conditioned: bool = False) -> str | None:
        if uf is not None:
            return BrazilianLocationSampler.normalize_uf(uf)
        if self._uf is not None:
            return self._uf
        if draw_if_conditioned and (self._uf_conditioning or self._experimental_uf_sex):
            _, state_abbr = self._location_sampler().get_state(
                random_mode=self._random_mode,
                rng=rng,
            )
            return state_abbr
        return None

    def _resolve_sex(self, sex: str | None, *, rng: _stdlib_random.Random) -> str | None:
        raw = sex if sex is not None else self._sex_conditioning
        if raw is None:
            if self._experimental_uf_sex:
                return rng.choice(('M', 'F'))
            return None
        norm = str(raw).strip().upper()
        if norm in ('M', 'F'):
            return norm
        if norm == 'MIXED':
            return rng.choice(('M', 'F'))
        if norm == 'POPULATION':
            return 'M' if rng.random() < CENSUS_2022_OBSERVED_MALE_SHARE else 'F'
        raise ValueError(f"sex must be 'M', 'F', 'mixed', 'population', or None; got {sex!r}")

    # ------------------------------------------------------------------
    # Coherent complete profile
    # ------------------------------------------------------------------

    def ptbr_profile(
        self,
        *,
        all_data: bool = True,
        uf: str | None = None,
        sex: str | None = None,
        formatted: bool | None = None,
        cep_without_dash: bool | None = None,
    ) -> dict[str, Any]:
        """Generate a complete, internally coherent Brazilian synthetic profile."""
        fmt = self._formatted if formatted is None else formatted
        no_dash = self._cep_without_dash if cep_without_dash is None else cep_without_dash
        uf_eff = BrazilianLocationSampler.normalize_uf(uf) if uf is not None else self._uf
        sex_eff = sex if sex is not None else self._sex_conditioning

        profile = _sampler_sample(
            qty=1,
            q=1,
            city_only=False,
            state_abbr_only=False,
            state_full_only=False,
            only_cep=False,
            cep_without_dash=no_dash,
            make_api_call=False,
            time_period=self._resolved_period,
            return_only_name=False,
            name_raw=self._name_raw,
            json_path=PACKAGE_DATA_DIR / 'cities_with_ceps.json',
            names_path=PACKAGE_DATA_DIR / 'names_data.json',
            middle_names_path=PACKAGE_DATA_DIR / 'middle_names.json',
            only_surname=False,
            top_40=self._top_40,
            with_only_one_surname=self._with_only_one_surname,
            always_middle=self._always_middle,
            only_middle=False,
            always_cpf=True,
            always_pis=all_data,
            always_cnpj=all_data,
            always_cei=all_data,
            always_rg=True,
            always_phone=True,
            only_cpf=False,
            only_pis=False,
            only_cnpj=False,
            only_cei=False,
            only_rg=False,
            only_fone=False,
            include_issuer=self._include_issuer,
            only_document=False,
            surnames_path=PACKAGE_DATA_DIR / 'surnames_data.json',
            locations_path=PACKAGE_DATA_DIR / 'locations_data.json',
            save_to_jsonl=None,
            all_data=False,
            random=self._random_mode,
            experimental_uf_sex_conditioning=self._experimental_uf_sex,
            sex_conditioning=sex_eff,
            census_year=self._census_year,
            conditioning_mode=self._conditioning_mode,
            uf_conditioning=self._uf_conditioning,
            uf=uf_eff,
            formatted=fmt,
            rng=self._rng(),
            include_address=True,
        )
        return cast(dict[str, Any], profile)

    # ------------------------------------------------------------------
    # Fast scalar name methods
    # ------------------------------------------------------------------

    def ptbr_first_name(self, sex: str | None = None, uf: str | None = None) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=True)
        sex_eff = self._resolve_sex(sex, rng=rng)
        res = self._name_sampler().get_random_name(
            time_period=self._resolved_period,
            include_middle=False,
            raw=self._name_raw,
            include_surname=False,
            always_middle=False,
            return_components=False,
            random_mode=self._random_mode,
            uf=uf_eff,
            sex=sex_eff,
            rng=rng,
        )
        return str(res)

    def ptbr_first_name_female(self, uf: str | None = None) -> str:
        return self.ptbr_first_name(sex='F', uf=uf)

    def ptbr_first_name_male(self, uf: str | None = None) -> str:
        return self.ptbr_first_name(sex='M', uf=uf)

    def ptbr_middle_name(self) -> str:
        res = self._name_sampler().get_random_name(
            time_period=self._resolved_period,
            raw=self._name_raw,
            only_middle=True,
            return_components=False,
            random_mode=self._random_mode,
            rng=self._rng(),
        )
        return str(res)

    def ptbr_surname(
        self,
        uf: str | None = None,
        *,
        top_40: bool | None = None,
        one_surname: bool | None = None,
    ) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=True)
        return self._name_sampler().get_random_surname(
            top_40=self._top_40 if top_40 is None else top_40,
            raw=self._name_raw,
            with_only_one_surname=self._with_only_one_surname if one_surname is None else one_surname,
            random_mode=self._random_mode,
            uf=uf_eff if self._census_year == 2022 else None,
            rng=rng,
        )

    def ptbr_name(self, sex: str | None = None, uf: str | None = None) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=True)
        sex_eff = self._resolve_sex(sex, rng=rng)
        res = self._name_sampler().get_random_name(
            time_period=self._resolved_period,
            include_middle=True,
            raw=self._name_raw,
            include_surname=True,
            top_40=self._top_40,
            with_only_one_surname=self._with_only_one_surname,
            always_middle=self._always_middle,
            return_components=False,
            random_mode=self._random_mode,
            uf=uf_eff,
            sex=sex_eff,
            rng=rng,
        )
        return str(res)

    # ------------------------------------------------------------------
    # Fast scalar location & offline address methods
    # ------------------------------------------------------------------

    def ptbr_state(self, uf: str | None = None) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
        state_name, _ = self._location_sampler().get_state(
            random_mode=self._random_mode,
            uf=uf_eff,
            rng=rng,
        )
        return state_name

    def ptbr_state_abbr(self, uf: str | None = None) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
        _, state_abbr = self._location_sampler().get_state(
            random_mode=self._random_mode,
            uf=uf_eff,
            rng=rng,
        )
        return state_abbr

    def ptbr_city(self, uf: str | None = None) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
        _, _, city_name = self._location_sampler().get_state_and_city(
            random_mode=self._random_mode,
            uf=uf_eff,
            rng=rng,
        )
        return city_name

    def ptbr_cep(
        self,
        *,
        cep_without_dash: bool | None = None,
        formatted: bool | None = None,
        uf: str | None = None,
    ) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
        loc_sampler = self._location_sampler()
        _, _, city_name = loc_sampler.get_state_and_city(
            random_mode=self._random_mode,
            uf=uf_eff,
            rng=rng,
        )
        raw_cep = loc_sampler._get_random_cep_for_city(city_name, rng=rng)
        if cep_without_dash is not None:
            include_dash = not cep_without_dash
        elif formatted is not None:
            include_dash = formatted
        else:
            include_dash = not self._cep_without_dash
        return loc_sampler._format_cep(raw_cep, with_dash=include_dash)

    def ptbr_postcode(
        self,
        *,
        cep_without_dash: bool | None = None,
        formatted: bool | None = None,
        uf: str | None = None,
    ) -> str:
        return self.ptbr_cep(cep_without_dash=cep_without_dash, formatted=formatted, uf=uf)

    def ptbr_street(self) -> str:
        ap = AddressProvider_for_offline(rng=self._rng())
        return f'{ap.street_prefix()} {ap.last_name()}'

    def ptbr_street_address(self) -> str:
        ap = AddressProvider_for_offline(rng=self._rng())
        return f'{ap.street_prefix()} {ap.last_name()}, {ap.building_number()}'

    def ptbr_neighborhood(self) -> str:
        ap = AddressProvider_for_offline(rng=self._rng())
        return ap.bairro()

    def ptbr_building_number(self) -> str:
        ap = AddressProvider_for_offline(rng=self._rng())
        return ap.building_number()

    def ptbr_address(self, uf: str | None = None) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
        loc_sampler = self._location_sampler()
        _, state_abbr, city_name = loc_sampler.get_state_and_city(
            random_mode=self._random_mode,
            uf=uf_eff,
            rng=rng,
        )
        raw_cep = loc_sampler._get_random_cep_for_city(city_name, rng=rng)
        cep_str = loc_sampler._format_cep(raw_cep, with_dash=not self._cep_without_dash)
        ap = AddressProvider_for_offline(rng=rng)
        street = f'{ap.street_prefix()} {ap.last_name()}'
        building = ap.building_number()
        bairro = ap.bairro()
        return f'{street}, {building} - {bairro}\n{cep_str} {city_name} / {state_abbr}'

    # ------------------------------------------------------------------
    # Fast scalar document & phone methods
    # ------------------------------------------------------------------

    def ptbr_cpf(self, formatted: bool | None = None) -> str:
        fmt = self._formatted if formatted is None else formatted
        return self._doc_sampler.generate_cpf(formatted=fmt, rng=self._rng())

    def ptbr_pis(self, formatted: bool | None = None) -> str:
        fmt = self._formatted if formatted is None else formatted
        return self._doc_sampler.generate_pis(formatted=fmt, rng=self._rng())

    def ptbr_cnpj(self, formatted: bool | None = None) -> str:
        fmt = self._formatted if formatted is None else formatted
        return self._doc_sampler.generate_cnpj(formatted=fmt, rng=self._rng())

    def ptbr_cei(self, formatted: bool | None = None) -> str:
        fmt = self._formatted if formatted is None else formatted
        return self._doc_sampler.generate_cei(formatted=fmt, rng=self._rng())

    def ptbr_rg(
        self,
        uf: str | None = None,
        *,
        include_issuer: bool | None = None,
        formatted: bool | None = None,
    ) -> str:
        rng = self._rng()
        uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
        if uf_eff is None:
            _, uf_eff = self._location_sampler().get_state(
                random_mode=self._random_mode,
                rng=rng,
            )
        fmt = self._formatted if formatted is None else formatted
        inc_issuer = self._include_issuer if include_issuer is None else include_issuer
        return self._doc_sampler.generate_rg(
            uf_eff,
            include_issuer=inc_issuer,
            formatted=fmt,
            rng=rng,
        )

    def ptbr_phone(self, ddd: str | None = None, uf: str | None = None) -> str:
        rng = self._rng()
        if ddd is None:
            uf_eff = self._resolve_uf(uf, rng=rng, draw_if_conditioned=False)
            loc_sampler = self._location_sampler()
            _, _, city_name = loc_sampler.get_state_and_city(
                random_mode=self._random_mode,
                uf=uf_eff,
                rng=rng,
            )
            city_meta = loc_sampler.city_data_by_name.get(city_name, {})
            ddd = str(city_meta.get('ddd', '11'))
        return generate_phone_number(ddd, rng=rng)

    def ptbr_phone_number(self, ddd: str | None = None, uf: str | None = None) -> str:
        return self.ptbr_phone(ddd=ddd, uf=uf)


class _AliasedPTBRProvider(PTBRProvider):
    """Subclass used when ``install_ptbr(..., aliases=True)`` overrides standard Faker formatters."""

    def name(self) -> str:
        return self.ptbr_name()

    def first_name(self) -> str:
        return self.ptbr_first_name()

    def first_name_female(self) -> str:
        return self.ptbr_first_name_female()

    def first_name_male(self) -> str:
        return self.ptbr_first_name_male()

    def last_name(self) -> str:
        return self.ptbr_surname()

    def city(self) -> str:
        return self.ptbr_city()

    def state(self) -> str:
        return self.ptbr_state()

    def state_abbr(self, include_freely_associated_states: bool = True) -> str:
        return self.ptbr_state_abbr()

    def postcode(self, formatted: bool | None = None) -> str:
        return self.ptbr_cep(formatted=formatted)

    def address(self) -> str:
        return self.ptbr_address()

    def street_address(self) -> str:
        return self.ptbr_street_address()

    def bairro(self) -> str:
        return self.ptbr_neighborhood()

    def neighborhood(self) -> str:
        return self.ptbr_neighborhood()

    def building_number(self) -> str:
        return self.ptbr_building_number()

    def cpf(self) -> str:
        return self.ptbr_cpf()

    def cnpj(self) -> str:
        return self.ptbr_cnpj()

    def rg(self) -> str:
        return self.ptbr_rg()

    def phone_number(self) -> str:
        return self.ptbr_phone_number()


def _iter_leaf_generators(fake: Any) -> list[Any]:
    """Unwrap ``faker.proxy.Faker`` containers down to leaf ``faker.generator.Generator`` instances."""
    sub_factories = getattr(fake, '_factories', None)
    if sub_factories:
        leaves: list[Any] = []
        for sub in sub_factories:
            leaves.extend(_iter_leaf_generators(sub))
        return leaves
    return [fake]


def _iter_proxy_containers(fake: Any) -> list[Any]:
    """Collect ``faker.proxy.Faker`` wrappers so cached method lookups can be invalidated."""
    sub_factories = getattr(fake, '_factories', None)
    if not sub_factories:
        return []
    proxies = [fake]
    for sub in sub_factories:
        proxies.extend(_iter_proxy_containers(sub))
    return proxies


def _cleanup_previous_ptbr_providers(leaf: Any) -> None:
    """Remove previously attached PTBRProvider instances from ``leaf`` and restore shadowed formatters."""
    existing_ptbr = [p for p in leaf.providers if isinstance(p, PTBRProvider)]
    if not existing_ptbr:
        return

    remaining = [p for p in leaf.providers if not isinstance(p, PTBRProvider)]
    leaf.providers = remaining

    formatters = getattr(leaf, 'formatters', None)
    for attr_name in list(vars(leaf).keys()):
        val = getattr(leaf, attr_name, None)
        bound_self = getattr(val, '__self__', None)
        if isinstance(bound_self, PTBRProvider):
            delattr(leaf, attr_name)
            if isinstance(formatters, dict):
                formatters.pop(attr_name, None)

    # Re-bind standard methods from remaining providers (lowest priority first so highest wins)
    for provider in reversed(remaining):
        for method_name in _ALIAS_STANDARD_METHODS:
            method = getattr(provider, method_name, None)
            if callable(method):
                leaf.set_formatter(method_name, method)


def install_ptbr(
    fake: Faker,
    *,
    aliases: bool = False,
    override_standard: bool | None = None,
    **options: Any,
) -> Faker:
    """Attach :class:`PTBRProvider` to ``fake`` (all leaf generators) and return ``fake``.

    By default (``aliases=False``), standard ``Faker('pt_BR')`` methods such as ``fake.name()``,
    ``fake.city()``, and ``fake.cpf()`` remain untouched while ``fake.ptbr_*`` methods become
    available. Pass ``aliases=True`` (or ``override_standard=True``) to also override standard
    Faker formatter names.
    """
    # Validate eagerly before mutating any generator state
    _parse_provider_options(options)
    enable_aliases = aliases if override_standard is None else override_standard
    provider_cls = _AliasedPTBRProvider if enable_aliases else PTBRProvider

    leaves = _iter_leaf_generators(fake)
    for leaf in leaves:
        _cleanup_previous_ptbr_providers(leaf)
        provider = provider_cls(leaf, **options)
        leaf.add_provider(provider)

    # Refresh Faker single/multi-locale proxy caches if present
    for proxy in _iter_proxy_containers(fake):
        factory_map = getattr(proxy, '_factory_map', None)
        for method_name in dir(_AliasedPTBRProvider):
            if not method_name.startswith('_'):
                proxy.__dict__.pop(method_name, None)
                if isinstance(factory_map, dict):
                    factory_map.pop(method_name, None)

    return fake


__all__ = ['PTBRProvider', 'install_ptbr']

#!/usr/bin/env python3
"""Sample module providing a clean API for the Brazilian data generator.

Thin wrapper around :func:`ptbr_sampler.sampler.sample` that makes it easier
to use programmatically (sensible defaults, single-keyword ``q`` alias,
unwrapped dict return when ``q == 1``). Defaults to IBGE Censo 2022
(``census_year=2022``, ``time_period=TimePeriod.ALL``).
"""

from pathlib import Path

from ptbr_sampler.br_name_class import TimePeriod
from ptbr_sampler.sampler import sample as sampler_function

# Default data paths — resolved lazily via ptbr_sampler.datasets on first draw.
_DATA_DIR = Path(__file__).parent / 'ptbr_sampler' / 'data'

_DEFAULTS = {
    'qty': 1,
    'city_only': False,
    'state_abbr_only': False,
    'state_full_only': False,
    'only_cep': False,
    'cep_without_dash': False,
    'make_api_call': False,
    'time_period': None,
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
    'surnames_path': _DATA_DIR / 'surnames_data.json',
    'locations_path': _DATA_DIR / 'locations_data.json',
    'save_to_jsonl': None,
    'all_data': False,
    'random': False,
    'experimental_uf_sex_conditioning': False,
    'census_year': 2022,
    'conditioning_mode': 'strict',
    'uf_conditioning': False,
    'sex_conditioning': None,
}


def sample(
    q: int | None = None,
    save_to_jsonl: str | None = None,
    all_data: bool = False,
    random: bool = False,
    experimental_uf_sex_conditioning: bool = False,
    census_year: int = 2022,
    conditioning_mode: str = 'strict',
    uf_conditioning: bool = False,
    **kwargs,
) -> dict | list[dict]:
    """Generate random Brazilian name, location, and document samples.

    Defaults to IBGE Censo 2022 (``census_year=2022``, ``TimePeriod.ALL``,
    ``conditioning_mode='strict'``). Pass ``census_year=2010`` to opt into the
    historical 2010 vintage.
    """
    merged = {**_DEFAULTS, **kwargs}
    merged['q'] = q
    merged['save_to_jsonl'] = save_to_jsonl
    merged['all_data'] = all_data
    merged['random'] = random
    merged['experimental_uf_sex_conditioning'] = experimental_uf_sex_conditioning
    merged['census_year'] = census_year
    merged['conditioning_mode'] = conditioning_mode
    merged['uf_conditioning'] = uf_conditioning

    return sampler_function(**merged)


__all__ = ['TimePeriod', 'sample']

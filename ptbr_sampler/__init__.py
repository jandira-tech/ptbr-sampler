"""Brazilian Name and Location Generator.

This package provides tools for generating realistic Brazilian names and
locations based on population data and historical naming patterns.

Top-level exports:
    sample                   — ergonomic profile generator (defaults to Census 2022).
    BrazilianLocationSampler — state/city/CEP sampler.
    BrazilianNameSampler     — alias-table-backed name sampler.
    TimePeriod               — birth-period buckets.
    NameComponents           — (first_name, middle_name, surname) triple.
    app, main                — Typer CLI (``ptbr`` entry point).

The CLI is installed as the ``ptbr`` console script; see ``pyproject.toml``.
"""

from typing import Any

from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import BrazilianNameSampler, NameComponents, TimePeriod
from ptbr_sampler.cli import app, main
from ptbr_sampler.datasets import PACKAGE_DATA_DIR
from ptbr_sampler.sampler import sample as _sampler_function

_SAMPLE_DEFAULTS: dict[str, Any] = {
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
    'json_path': PACKAGE_DATA_DIR / 'cities_with_ceps.json',
    'names_path': PACKAGE_DATA_DIR / 'names_data.json',
    'middle_names_path': PACKAGE_DATA_DIR / 'middle_names.json',
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
    'surnames_path': PACKAGE_DATA_DIR / 'surnames_data.json',
    'locations_path': PACKAGE_DATA_DIR / 'locations_data.json',
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
    **kwargs: Any,
) -> dict | list[dict]:
    """Generate random Brazilian name, location, and document samples.

    Defaults to IBGE Censo 2022 (``census_year=2022``, ``TimePeriod.ALL``,
    ``conditioning_mode='strict'``). Pass ``census_year=2010`` to opt into the
    historical 2010 vintage.
    """
    merged = {**_SAMPLE_DEFAULTS, **kwargs}
    merged['q'] = q
    merged['save_to_jsonl'] = save_to_jsonl
    merged['all_data'] = all_data
    merged['random'] = random
    merged['experimental_uf_sex_conditioning'] = experimental_uf_sex_conditioning
    merged['census_year'] = census_year
    merged['conditioning_mode'] = conditioning_mode
    merged['uf_conditioning'] = uf_conditioning
    return _sampler_function(**merged)


__all__ = [
    'BrazilianLocationSampler',
    'BrazilianNameSampler',
    'NameComponents',
    'TimePeriod',
    'app',
    'main',
    'sample',
]

__version__ = '0.3.0'

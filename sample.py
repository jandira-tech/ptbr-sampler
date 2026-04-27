#!/usr/bin/env python3
"""Sample module providing a clean API for the Brazilian data generator.

Thin wrapper around :func:`ptbr_sampler.sampler.sample` that makes it easier
to use programmatically (sensible defaults, single-keyword ``q`` alias,
unwrapped dict return when ``q == 1``).
"""

from pathlib import Path

from ptbr_sampler.br_name_class import TimePeriod
from ptbr_sampler.sampler import sample as sampler_function

# Default data paths — bundled inside the installed package.
_DATA_DIR = Path(__file__).parent / 'ptbr_sampler' / 'data'

_DEFAULTS = {
    'qty': 1,
    'city_only': False,
    'state_abbr_only': False,
    'state_full_only': False,
    'only_cep': False,
    'cep_without_dash': False,
    'make_api_call': False,
    'time_period': TimePeriod.UNTIL_2010,
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
}


def sample(
    q: int | None = None,
    save_to_jsonl: str | None = None,
    all_data: bool = False,
    random: bool = False,
    **kwargs,
) -> dict | list[dict]:
    """
    Generate random Brazilian name, location, and document samples.

    Args:
        q: Number of samples to generate. Overrides ``qty`` if provided.
            When ``q`` is None, falls back to ``qty`` from kwargs (or the
            default of 1).
        save_to_jsonl: Path to save generated samples as JSONL
        all_data: Include all possible data in the generated samples
        random: Explicit random mode (opt-out of realism). When ``True``, the
            sampler ignores population weights for locations and frequency
            weights for names, and uses a flat 50% middle-name flag in place
            of the empirical 30.99% rate. Default ``False`` keeps the
            realism-by-default path described in the README.
        **kwargs: Additional parameters passed directly to cli.sample

    Common keyword arguments:
        time_period: TimePeriod enum for name generation era
        city_only: Return only city names
        state_abbr_only: Return only state abbreviations
        state_full_only: Return only full state names
        only_cep: Return only CEP (Brazilian postal code)
        cep_without_dash: Format CEP without dash
        return_only_name: Return only names without location
        name_raw: Return names in raw format (all caps)
        only_surname: Return only surnames
        top_40: Use only top 40 surnames
        with_only_one_surname: Use single surname
        always_middle: Always include middle name
        only_middle: Return only middle names
        always_cpf: Include CPF in documents
        always_pis: Include PIS in documents
        always_cnpj: Include CNPJ in documents
        always_cei: Include CEI in documents
        always_rg: Include RG in documents
        only_cpf: Generate only CPF
        only_pis: Generate only PIS
        only_cnpj: Generate only CNPJ
        only_cei: Generate only CEI
        only_rg: Generate only RG
        include_issuer: Include issuing state in RG

    Returns:
        A dictionary with the generated sample if q=1, or a list of dictionaries if q>1.
        Each dictionary contains the following keys:
        - name: First name
        - middle_name: Middle name (if generated)
        - surnames: Last names
        - city: City name
        - state: State name
        - state_abbr: State abbreviation
        - cep: CEP (Brazilian postal code)
        - cpf: CPF number (Brazilian ID)
        - rg: RG number (Brazilian ID)
        - pis: PIS number (if requested)
        - cnpj: CNPJ number (if requested)
        - cei: CEI number (if requested)
    """
    # Build full kwargs with defaults, letting explicit kwargs override
    merged = {**_DEFAULTS, **kwargs}

    # Map the top-level parameters. ``q`` only overrides ``qty`` when provided
    # explicitly so callers can still pass ``qty=N`` via kwargs.
    merged['q'] = q
    merged['save_to_jsonl'] = save_to_jsonl
    merged['all_data'] = all_data
    merged['random'] = random

    return sampler_function(**merged)


# Export the TimePeriod enum for convenience
__all__ = ['TimePeriod', 'sample']

"""
Brazilian Sample Generator

Core functionality for generating Brazilian name, location, and document samples.
"""

import asyncio
import copy
import functools
import json
import random as _stdlib_random
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiofiles

from ptbr_sampler.datasets import (
    PACKAGE_DATA_DIR,
    ensure_data_file,
    ensure_parquet_root,
    resolve_bundled_or_custom_path,
    resolve_partition_path,
)
from ptbr_sampler.utils.address_for_offline import AddressProvider_for_offline
from ptbr_sampler.utils.phone import generate_phone_number

from .br_location_class import BrazilianLocationSampler
from .br_name_class import (
    CENSUS_2022_OBSERVED_MALE_SHARE,
    BrazilianNameSampler,
    NameComponents,
    TimePeriod,
    resolve_time_period,
)
from .document_sampler import DocumentSampler

# Module-level JSON and sampler caches to avoid re-parsing on repeated calls.
_json_cache: dict[str, dict] = {}
_json_cache_lock = threading.RLock()
_sampler_cache_lock = threading.RLock()
_location_sampler_cache: dict[tuple[str, int, str | None, int | None], BrazilianLocationSampler] = {}


def _load_json_cached(path: str | Path) -> dict:
    """Load JSON data from a file, returning a cached copy after first load.

    The returned dict is shared — callers that need to mutate it should
    copy it first.
    """
    key = str(Path(path).resolve())
    with _json_cache_lock:
        if key not in _json_cache:
            with Path(path).open(encoding='utf-8') as f:
                _json_cache[key] = json.load(f)
        return _json_cache[key]


def _coin_flip_sexes(n: int, *, rng: _stdlib_random.Random | None = None) -> list[str]:
    """Draw ``n`` sexes 50/50 for rows with no sex given.

    The module is imported as ``_stdlib_random`` because :func:`sample`
    names its explicit-random flag ``random``.
    """
    chooser = rng.choice if rng is not None else _stdlib_random.choice
    return [chooser(('M', 'F')) for _ in range(n)]


def _population_sexes_2022(n: int, *, rng: _stdlib_random.Random | None = None) -> list[str]:
    """Draw ``n`` sexes from the observed IBGE 2022 national sex share."""
    rand = rng.random if rng is not None else _stdlib_random.random
    return ['M' if rand() < CENSUS_2022_OBSERVED_MALE_SHARE else 'F' for _ in range(n)]


def _custom_path_or_none(path: str | Path | None, default_relpath: str) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.resolve() == (PACKAGE_DATA_DIR / default_relpath).resolve():
        return None
    return str(candidate.resolve())


@functools.lru_cache(maxsize=8)
def _get_cached_name_sampler_unlocked(
    census_year: int,
    conditioning_mode: str,
    parquet_root_str: str | None,
    custom_names_path: str | None,
    custom_surnames_path: str | None,
    resolved_middle_path: str | None,
) -> BrazilianNameSampler:
    if census_year == 2022 and custom_names_path is None and custom_surnames_path is None:
        if parquet_root_str is None:
            raise ValueError('census_year=2022 default path requires parquet_root_str')
        return BrazilianNameSampler.from_parquet_root(
            Path(parquet_root_str),
            middle_names_path=resolved_middle_path,
            census_year=2022,
            conditioning_mode=conditioning_mode,  # type: ignore[arg-type]
            path_resolver=resolve_partition_path,
        )
    surnames_file = Path(custom_surnames_path) if custom_surnames_path else ensure_data_file('surnames_data.json')
    names_file = Path(custom_names_path) if custom_names_path else ensure_data_file('names_data.json')
    surnames_data = copy.deepcopy(_load_json_cached(surnames_file))
    name_data = {'surnames': surnames_data['surnames']}
    name_data.update(copy.deepcopy(_load_json_cached(names_file)))
    use_parquet = custom_names_path is None and custom_surnames_path is None and parquet_root_str is not None
    return BrazilianNameSampler(
        None,
        resolved_middle_path,
        None,
        parquet_root=Path(parquet_root_str) if use_parquet else None,
        census_year=census_year,
        conditioning_mode=conditioning_mode,  # type: ignore[arg-type]
        path_resolver=resolve_partition_path if use_parquet else None,
        preloaded_data=name_data,
    )


def _get_cached_name_sampler(
    census_year: int,
    conditioning_mode: str,
    parquet_root_str: str | None,
    custom_names_path: str | None,
    custom_surnames_path: str | None,
    resolved_middle_path: str | None,
) -> BrazilianNameSampler:
    with _sampler_cache_lock:
        return _get_cached_name_sampler_unlocked(
            census_year,
            conditioning_mode,
            parquet_root_str,
            custom_names_path,
            custom_surnames_path,
            resolved_middle_path,
        )


def _get_cached_location_sampler(
    json_path: str | Path,
    locations_path: str | Path | None,
) -> BrazilianLocationSampler:
    resolved_json_path = resolve_bundled_or_custom_path(json_path, 'cities_with_ceps.json')
    location_json = _load_json_cached(resolved_json_path)

    resolved_loc_str: str | None = None
    locations_data: dict[str, Any] | None = None
    if locations_path:
        try:
            resolved_loc_path = resolve_bundled_or_custom_path(locations_path, 'locations_data.json')
            locations_data = _load_json_cached(resolved_loc_path)
            if not isinstance(locations_data, dict):
                raise TypeError('locations_data root must be a JSON object')
            resolved_loc_str = str(resolved_loc_path.resolve())
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
            print(f'Warning: Could not use locations_path data: {e}')
            locations_data = None
            resolved_loc_str = None

    cache_key = (
        str(resolved_json_path.resolve()),
        id(location_json),
        resolved_loc_str,
        id(locations_data) if locations_data is not None else None,
    )
    with _sampler_cache_lock:
        cached = _location_sampler_cache.get(cache_key)
        if cached is not None:
            return cached

        sampler = BrazilianLocationSampler(copy.deepcopy(location_json))
        if locations_data is not None:
            try:
                loc_copy = copy.deepcopy(locations_data)
                if 'cities' in loc_copy:
                    sampler.update_cities(loc_copy['cities'])
                if 'states' in loc_copy:
                    sampler.update_states(loc_copy['states'])
            except (KeyError, TypeError) as e:
                print(f'Warning: Could not use locations_path data: {e}')
                sampler = BrazilianLocationSampler(copy.deepcopy(location_json))

        if len(_location_sampler_cache) >= 16:
            _location_sampler_cache.clear()
        _location_sampler_cache[cache_key] = sampler
        return sampler


def _get_default_location_sampler() -> BrazilianLocationSampler:
    """Return the cached default BrazilianLocationSampler for scalar callers (e.g. Faker)."""
    return _get_cached_location_sampler(
        PACKAGE_DATA_DIR / 'cities_with_ceps.json',
        PACKAGE_DATA_DIR / 'locations_data.json',
    )


def _get_default_name_sampler(
    *,
    census_year: int = 2022,
    conditioning_mode: str = 'strict',
) -> BrazilianNameSampler:
    """Return the cached default BrazilianNameSampler for scalar callers (e.g. Faker)."""
    resolved_middle_path = str(resolve_bundled_or_custom_path(PACKAGE_DATA_DIR / 'middle_names.json', 'middle_names.json'))
    parquet_root_str = str(ensure_parquet_root(census_year))
    return _get_cached_name_sampler(
        census_year,
        conditioning_mode,
        parquet_root_str,
        None,
        None,
        resolved_middle_path,
    )


def parse_result(
    location: str,
    name_components: NameComponents,
    documents: dict[str, str],
    state_info: tuple[str, str, str] | None = None,
    address_data: dict | None = None,
) -> dict:
    """Parse sample results into a standardized dictionary format.

    Args:
        location: Full location string
        name_components: Named tuple with name components
        documents: Dictionary of document numbers
        state_info: Optional tuple of (state_name, state_abbr, city_name)
        address_data: Optional dictionary with address data (street, neighborhood, building_number)

    Returns:
        dict: Structured dictionary with parsed components
    """
    result = {
        'name': name_components.first_name if name_components else '',
        'middle_name': name_components.middle_name if name_components else '',
        'surnames': name_components.surname if name_components else '',
        'city': '',
        'state': '',
        'state_abbr': '',
        'cep': '',
        'street': '',
        'neighborhood': '',
        'building_number': '',
        'cpf': documents.get('cpf', ''),
        'rg': documents.get('rg', ''),
        'pis': documents.get('pis', ''),
        'cnpj': documents.get('cnpj', ''),
        'cei': documents.get('cei', ''),
        'phone': documents.get('phone', ''),
    }

    if state_info:
        result['state'], result['state_abbr'], result['city'] = state_info
    elif location and ', ' in location:
        # Parse location string if available
        try:
            city_part, state_part = location.split(', ')
            if ' - ' in city_part:
                result['city'], cep = city_part.split(' - ')
                result['cep'] = cep
            else:
                result['city'] = city_part

            if '(' in state_part:
                result['state'], abbr = state_part.split(' (')
                result['state_abbr'] = abbr.rstrip(')')
            else:
                result['state'] = state_part
        except ValueError:
            pass

    # Add address data if available
    if address_data:
        result['street'] = address_data.get('street', '')
        result['neighborhood'] = address_data.get('neighborhood', '')
        result['building_number'] = address_data.get('building_number', '')

        # If we have city/state from address_data, use it (API mode)
        if address_data.get('city'):
            result['city'] = address_data.get('city', '')
        if address_data.get('state'):
            result['state'] = address_data.get('state', '')
        if address_data.get('cep'):
            result['cep'] = address_data.get('cep', '')

    return result


def _save_to_jsonl_sync(data: list[dict], filename: str, append: bool = True) -> None:
    """Write sample records to a UTF-8 JSONL file synchronously."""
    mode = 'a' if append else 'w'
    file_path = Path(filename)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open(mode, encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


async def save_to_jsonl_file(data: list[dict], filename: str, append: bool = True) -> None:
    """Save generated samples to a JSONL file asynchronously.

    Args:
        data: List of dictionaries containing sample data
        filename: Path to the output JSONL file
        append: If True, append to existing file instead of overwriting
    """
    mode = 'a' if append else 'w'

    # Create a directory for the file if it doesn't exist
    file_path = Path(filename)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(file_path, mode, encoding='utf-8') as f:
        for item in data:
            await f.write(json.dumps(item, ensure_ascii=False) + '\n')


def _generate_offline_address_batch(
    ceps: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
    *,
    cep_without_dash: bool = False,
    rng: _stdlib_random.Random | None = None,
) -> list[dict]:
    """Generate offline synthetic street/neighborhood/building data synchronously."""
    address_data_list: list[dict] = []
    address_provider = AddressProvider_for_offline(rng=rng)
    for i, cep in enumerate(ceps):
        formatted_cep = cep
        if cep_without_dash:
            formatted_cep = formatted_cep.replace('-', '')
        elif '-' not in formatted_cep and len(formatted_cep) == 8:
            formatted_cep = f'{formatted_cep[:5]}-{formatted_cep[5:]}'

        address_data = {
            'street': address_provider.street_prefix() + ' ' + address_provider.last_name(),
            'neighborhood': address_provider.bairro(),
            'building_number': address_provider.building_number(),
            'cep': formatted_cep,
        }
        address_data_list.append(address_data)

        if progress_callback and i % max(1, len(ceps) // 10) == 0:
            progress_callback(0, f'Generating address data: {i + 1}/{len(ceps)}')
    return address_data_list


async def get_address_data_batch(
    ceps: list[str],
    make_api_call: bool = False,
    progress_callback: Callable[[int, str], None] | None = None,
    *,
    cep_without_dash: bool = False,
    rng: _stdlib_random.Random | None = None,
) -> list[dict]:
    """
    Get address data for multiple CEPs, either from API or generated.

    Args:
        ceps: List of CEPs to get address data for
        make_api_call: Whether to make API calls or generate data
        progress_callback: Optional callback function to report progress

    Returns:
        List of dictionaries with address data (street, neighborhood, building_number)
    """
    if not make_api_call:
        return _generate_offline_address_batch(
            ceps,
            progress_callback=progress_callback,
            cep_without_dash=cep_without_dash,
            rng=rng,
        )

    address_data_list: list[dict] = []

    # Use cep_wrapper to get real data for multiple CEPs
    from .utils.cep_wrapper import workers_for_multiple_cep  # noqa: PLC0415 - optional Node-backed CEP integration stays lazy.

    # Format CEPs to remove dashes before API call
    formatted_ceps = [cep.replace('-', '') for cep in ceps]

    # Update progress if callback is provided
    if progress_callback:
        progress_callback(0, 'API calls: Connecting to service')

    # Get data from API
    cep_data_list = await workers_for_multiple_cep(formatted_ceps)

    # Update progress if callback is provided
    if progress_callback:
        progress_callback(0, 'API calls: Processing responses')

    fallback_provider = AddressProvider_for_offline(rng=rng)

    # Process each CEP result
    for i, cep_data in enumerate(cep_data_list):
        cep_val = cep_data.get('cep', '')
        if cep_without_dash and cep_val:
            cep_val = cep_val.replace('-', '')
        address_data = {
            'street': '',
            'neighborhood': '',
            'building_number': '',
            'cep': cep_val,
            'state': cep_data.get('state', ''),
            'city': cep_data.get('city', ''),
        }

        # Extract data from API response if no error
        if 'error' not in cep_data:
            address_data['street'] = cep_data.get('street', '')
            address_data['neighborhood'] = cep_data.get('neighborhood', '')

        # If neighborhood is empty, use address_for_offline
        if not address_data['neighborhood']:
            address_data['neighborhood'] = fallback_provider.bairro()

        # If street is empty, use address_for_offline
        if not address_data['street']:
            address_data['street'] = fallback_provider.street_prefix() + ' ' + fallback_provider.last_name()

        # Always get building number from address_for_offline
        address_data['building_number'] = fallback_provider.building_number()

        address_data_list.append(address_data)

        # Update progress occasionally if callback is provided
        if progress_callback and i % max(1, len(cep_data_list) // 10) == 0:
            progress_callback(0, f'API calls: Processed {i + 1}/{len(cep_data_list)} addresses')

    # Final update for API calls completion
    if progress_callback:
        progress_callback(0, 'API calls processing completed')

    return address_data_list


async def get_address_data(
    cep: str,
    make_api_call: bool = False,
    *,
    cep_without_dash: bool = False,
    rng: _stdlib_random.Random | None = None,
) -> dict:
    """
    Get address data for a single CEP, either from API or generated.

    Args:
        cep: The CEP to get address data for
        make_api_call: Whether to make API calls or generate data

    Returns:
        Dictionary with address data (street, neighborhood, building_number)
    """
    result = await get_address_data_batch(
        [cep],
        make_api_call,
        cep_without_dash=cep_without_dash,
        rng=rng,
    )
    return result[0] if result else {}


def _has_running_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def sample(
    qty: int,
    q: int | None,
    city_only: bool,
    state_abbr_only: bool,
    state_full_only: bool,
    only_cep: bool,
    cep_without_dash: bool,
    make_api_call: bool,
    time_period: TimePeriod | None,
    return_only_name: bool,
    name_raw: bool,
    json_path: str | Path,
    names_path: str | Path,
    middle_names_path: str | Path,
    only_surname: bool,
    top_40: bool,
    with_only_one_surname: bool,
    always_middle: bool,
    only_middle: bool,
    always_cpf: bool,
    always_pis: bool,
    always_cnpj: bool,
    always_cei: bool,
    always_rg: bool,
    always_phone: bool,
    only_cpf: bool,
    only_pis: bool,
    only_cnpj: bool,
    only_cei: bool,
    only_rg: bool,
    only_fone: bool,
    include_issuer: bool,
    only_document: bool,
    surnames_path: str | Path,
    locations_path: str | Path,
    save_to_jsonl: str | None,
    all_data: bool,
    progress_callback: Callable[[int, str], None] | None = None,
    append_to_jsonl: bool = False,
    random: bool = False,
    experimental_uf_sex_conditioning: bool = False,
    sex_conditioning: str | None = None,
    census_year: int = 2022,
    conditioning_mode: str = 'strict',
    uf_conditioning: bool = False,
    uf: str | None = None,
    formatted: bool = True,
    rng: _stdlib_random.Random | None = None,
    include_address: bool = True,
) -> dict | list[dict]:
    """Generate randomized Brazilian profiles composed of name, location, and document fields."""
    actual_qty = q if q is not None else qty
    if actual_qty < 0:
        raise ValueError(f'Sample quantity must be >= 0; got {actual_qty}')

    if census_year not in (2010, 2022):
        raise ValueError(f'census_year must be 2010 or 2022; got {census_year!r}')
    if conditioning_mode not in ('strict', 'estimated'):
        raise ValueError(f"conditioning_mode must be 'strict' or 'estimated'; got {conditioning_mode!r}")

    uf_norm = BrazilianLocationSampler.normalize_uf(uf)

    custom_names_path = _custom_path_or_none(names_path, 'names_data.json')
    custom_surnames_path = _custom_path_or_none(surnames_path, 'surnames_data.json')
    effective_census_year = 2010 if (custom_names_path is not None or custom_surnames_path is not None) else census_year
    resolved_period = resolve_time_period(time_period, effective_census_year)

    sex_conditioning_norm: str | None = None
    if sex_conditioning is not None:
        sc = str(sex_conditioning).strip().upper()
        if sc not in ('M', 'F', 'MIXED', 'POPULATION'):
            raise ValueError(f"sex_conditioning must be 'M', 'F', 'mixed', 'population', or None; got {sex_conditioning!r}")
        if sc == 'POPULATION' and effective_census_year != 2022:
            raise ValueError("sex_conditioning='population' requires census_year=2022")
        sex_conditioning_norm = sc

    # If all_data is True, override other flags to include everything
    if all_data:
        always_cpf = True
        always_pis = True
        always_cnpj = True
        always_cei = True
        always_rg = True
        always_phone = True
        always_middle = True
        only_cpf = False
        only_pis = False
        only_cnpj = False
        only_cei = False
        only_rg = False
        only_fone = False
        only_surname = False
        only_middle = False
        only_cep = False
        city_only = False
        state_abbr_only = False
        state_full_only = False
        return_only_name = False
        only_document = False

    condition_uf = uf_conditioning or experimental_uf_sex_conditioning or (uf_norm is not None)
    draws_first_names = not (
        only_document or any([only_cpf, only_pis, only_cnpj, only_cei, only_rg, only_fone]) or only_surname or only_middle
    )
    if effective_census_year == 2022 and draws_first_names:
        if condition_uf and resolved_period != TimePeriod.ALL:
            raise ValueError(
                'Census 2022 does not provide UF x cohort joint distributions '
                "(time_period != 'all' cannot be combined with UF conditioning)."
            )
        if conditioning_mode == 'strict':
            if condition_uf and (sex_conditioning_norm is not None or experimental_uf_sex_conditioning):
                raise ValueError(
                    'Census 2022 does not publish exact UF x sex joint tables; '
                    "pass conditioning_mode='estimated' to opt into Bayes composition."
                )
            if resolved_period != TimePeriod.ALL and sex_conditioning_norm is not None:
                raise ValueError(
                    'Census 2022 does not publish exact cohort x sex joint tables; '
                    "pass conditioning_mode='estimated' to opt into Bayes composition."
                )

    if make_api_call and _has_running_event_loop():
        raise RuntimeError(
            'Cannot run sample(..., make_api_call=True) inside a running event loop; '
            'use make_api_call=False or await get_address_data_batch(...) directly.'
        )

    if actual_qty == 0:
        if save_to_jsonl:
            if _has_running_event_loop():
                _save_to_jsonl_sync([], save_to_jsonl, append=append_to_jsonl)
            else:
                asyncio.run(save_to_jsonl_file([], save_to_jsonl, append=append_to_jsonl))
        if progress_callback:
            progress_callback(0, 'Complete')
        return []

    try:
        location_sampler = _get_cached_location_sampler(json_path, locations_path)
        doc_sampler = DocumentSampler()

        resolved_middle_path = str(resolve_bundled_or_custom_path(middle_names_path, 'middle_names.json')) if middle_names_path else None

        if custom_names_path is None and custom_surnames_path is None:
            parquet_root_str = str(ensure_parquet_root(effective_census_year))
            name_sampler = _get_cached_name_sampler(
                effective_census_year,
                conditioning_mode,
                parquet_root_str,
                None,
                None,
                resolved_middle_path,
            )
        else:
            surnames_file = Path(custom_surnames_path) if custom_surnames_path else ensure_data_file('surnames_data.json')
            names_file = Path(custom_names_path) if custom_names_path else ensure_data_file('names_data.json')
            surnames_data = copy.deepcopy(_load_json_cached(surnames_file))
            name_data = {'surnames': surnames_data['surnames']}
            name_data.update(copy.deepcopy(_load_json_cached(names_file)))
            name_sampler = BrazilianNameSampler(
                None,
                resolved_middle_path,
                None,
                parquet_root=None,
                census_year=effective_census_year,
                conditioning_mode=conditioning_mode,  # type: ignore[arg-type]
                preloaded_data=name_data,
            )

        results: list[tuple[str | None, NameComponents | None, dict[str, str]]] = []
        state_city_info: list[tuple[str, str, str]] = []
        pre_sampled_ceps: list[str] | None = None

        def _draw_coin_sexes(count: int) -> list[str]:
            return _coin_flip_sexes(count) if rng is None else _coin_flip_sexes(count, rng=rng)

        def _draw_pop_sexes(count: int) -> list[str]:
            return _population_sexes_2022(count) if rng is None else _population_sexes_2022(count, rng=rng)

        per_row_sexes: list[str] | None = None
        if sex_conditioning_norm == 'MIXED':
            per_row_sexes = _draw_coin_sexes(actual_qty)
        elif sex_conditioning_norm == 'POPULATION':
            per_row_sexes = _draw_pop_sexes(actual_qty)
        elif sex_conditioning_norm in ('M', 'F'):
            per_row_sexes = [sex_conditioning_norm] * actual_qty

        if only_document:
            for i in range(actual_qty):
                documents = {}
                state_name, state_abbr, city_name = location_sampler.get_state_and_city(
                    random_mode=random,
                    uf=uf_norm,
                    rng=rng,
                )
                state_city_info.append((state_name, state_abbr, city_name))

                if always_cpf or only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf(formatted=formatted, rng=rng)
                if always_pis or only_pis:
                    documents['pis'] = doc_sampler.generate_pis(formatted=formatted, rng=rng)
                if always_cnpj or only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj(formatted=formatted, rng=rng)
                if always_cei or only_cei:
                    documents['cei'] = doc_sampler.generate_cei(formatted=formatted, rng=rng)
                if always_rg or only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, formatted=formatted, rng=rng)}'
                if always_phone or only_fone:
                    city_data = location_sampler.city_data_by_name.get(city_name, {})
                    ddd = city_data.get('ddd', None)
                    documents['phone'] = generate_phone_number(ddd, rng=rng)

                results.append((None, None, documents))

                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating documents')

        elif any([only_cpf, only_pis, only_cnpj, only_cei, only_rg, only_fone]):
            for i in range(actual_qty):
                documents = {}
                state_name, state_abbr, city_name = location_sampler.get_state_and_city(
                    random_mode=random,
                    uf=uf_norm,
                    rng=rng,
                )
                state_city_info.append((state_name, state_abbr, city_name))
                if only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf(formatted=formatted, rng=rng)
                if only_pis:
                    documents['pis'] = doc_sampler.generate_pis(formatted=formatted, rng=rng)
                if only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj(formatted=formatted, rng=rng)
                if only_cei:
                    documents['cei'] = doc_sampler.generate_cei(formatted=formatted, rng=rng)
                if only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, formatted=formatted, rng=rng)}'
                if only_fone:
                    city_data = location_sampler.city_data_by_name.get(city_name, {})
                    ddd = city_data.get('ddd', None)
                    documents['phone'] = generate_phone_number(ddd, rng=rng)

                results.append((None, None, documents))

                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating specific documents')

        elif return_only_name or only_surname or only_middle:
            name_only_sexes = per_row_sexes
            if experimental_uf_sex_conditioning and name_only_sexes is None and draws_first_names:
                name_only_sexes = _draw_coin_sexes(actual_qty)
            for i in range(actual_qty):
                documents = {}
                name_components = None

                state_name, state_abbr, city_name = location_sampler.get_state_and_city(
                    random_mode=random,
                    uf=uf_norm,
                    rng=rng,
                )
                state_city_info.append((state_name, state_abbr, city_name))

                if only_surname:
                    name_components = NameComponents(
                        '',
                        None,
                        name_sampler.get_random_surname(
                            top_40=top_40,
                            raw=name_raw,
                            with_only_one_surname=with_only_one_surname,
                            random_mode=random,
                            uf=state_abbr if (condition_uf and effective_census_year == 2022) else None,
                            rng=rng,
                        ),
                    )
                elif only_middle:
                    name_components = name_sampler.get_random_name(
                        raw=name_raw,
                        only_middle=True,
                        return_components=True,
                        random_mode=random,
                        rng=rng,
                    )
                else:
                    name_components = name_sampler.get_random_name(
                        time_period=resolved_period,
                        raw=name_raw,
                        include_surname=True,
                        top_40=top_40,
                        with_only_one_surname=with_only_one_surname,
                        always_middle=always_middle,
                        return_components=True,
                        random_mode=random,
                        uf=state_abbr if condition_uf else None,
                        sex=name_only_sexes[i] if name_only_sexes is not None else None,
                        rng=rng,
                    )

                    if always_cpf:
                        documents['cpf'] = doc_sampler.generate_cpf(formatted=formatted, rng=rng)
                    if always_pis:
                        documents['pis'] = doc_sampler.generate_pis(formatted=formatted, rng=rng)
                    if always_cnpj:
                        documents['cnpj'] = doc_sampler.generate_cnpj(formatted=formatted, rng=rng)
                    if always_cei:
                        documents['cei'] = doc_sampler.generate_cei(formatted=formatted, rng=rng)
                    if always_rg:
                        documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, formatted=formatted, rng=rng)}'
                    if always_phone:
                        city_data = location_sampler.city_data_by_name.get(city_name, {})
                        ddd = city_data.get('ddd', None)
                        documents['phone'] = generate_phone_number(ddd, rng=rng)

                location_str = f'{city_name} - , {state_name} ({state_abbr})'
                results.append((location_str, name_components, documents))

                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating names')
        else:
            batch_locations = location_sampler.batch_sample_locations(
                actual_qty,
                random_mode=random,
                uf=uf_norm,
                rng=rng,
            )
            batch_ufs: list[str] | None = [loc['state_abbr'] for loc in batch_locations] if condition_uf else None
            batch_sexes: list[str] | None = per_row_sexes
            if experimental_uf_sex_conditioning and batch_sexes is None:
                batch_sexes = _draw_coin_sexes(actual_qty)
            batch_names = name_sampler.batch_sample_names(
                actual_qty,
                time_period=resolved_period,
                raw=name_raw,
                include_surname=True,
                top_40=top_40,
                with_only_one_surname=with_only_one_surname,
                always_middle=always_middle,
                random_mode=random,
                ufs=batch_ufs,
                sexes=batch_sexes,
                rng=rng,
            )

            if only_cep:
                pre_sampled_ceps = []

            for i in range(actual_qty):
                documents = {}

                loc = batch_locations[i]
                state_name, state_abbr, city_name = loc['state_name'], loc['state_abbr'], loc['city_name']

                state_city_info.append((state_name, state_abbr, city_name))

                if city_only:
                    location = city_name
                elif state_abbr_only:
                    location = state_abbr
                elif state_full_only:
                    location = state_name
                elif only_cep:
                    raw_cep = location_sampler._get_random_cep_for_city(city_name, rng=rng)
                    location = location_sampler._format_cep(raw_cep, not cep_without_dash)
                    if pre_sampled_ceps is not None:
                        pre_sampled_ceps.append(location)
                else:
                    location = location_sampler.format_full_location(
                        city_name,
                        state_name,
                        state_abbr,
                        include_cep=False,
                        cep_without_dash=cep_without_dash,
                        rng=rng,
                    )

                if always_cpf or only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf(formatted=formatted, rng=rng)
                if always_pis or only_pis:
                    documents['pis'] = doc_sampler.generate_pis(formatted=formatted, rng=rng)
                if always_cnpj or only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj(formatted=formatted, rng=rng)
                if always_cei or only_cei:
                    documents['cei'] = doc_sampler.generate_cei(formatted=formatted, rng=rng)
                if always_rg or only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, formatted=formatted, rng=rng)}'
                if always_phone or only_fone:
                    city_data = location_sampler.city_data_by_name.get(city_name, {})
                    ddd = city_data.get('ddd', None)
                    documents['phone'] = generate_phone_number(ddd, rng=rng)

                name_components = batch_names[i]

                results.append((location, name_components, documents))

                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating complete profiles')

        all_ceps: list[str] = []
        all_state_city_info = list(state_city_info)
        address_data_list: list[dict] = []

        if include_address or make_api_call or only_cep:
            if progress_callback:
                progress_callback(actual_qty // 2, 'Preparing address data')

            if pre_sampled_ceps is not None:
                all_ceps = list(pre_sampled_ceps)
            else:
                for i in range(actual_qty):
                    state_name, state_abbr, city_name = all_state_city_info[i]
                    cep = location_sampler._get_random_cep_for_city(city_name, rng=rng)
                    formatted_cep = location_sampler._format_cep(cep, not cep_without_dash)
                    all_ceps.append(formatted_cep)

            if include_address or make_api_call:
                if make_api_call:
                    if progress_callback:
                        progress_callback(actual_qty * 3 // 4, 'API calls starting')
                    address_data_list = asyncio.run(
                        get_address_data_batch(
                            all_ceps,
                            make_api_call=True,
                            progress_callback=progress_callback,
                            cep_without_dash=cep_without_dash,
                            rng=rng,
                        )
                    )
                    if progress_callback:
                        progress_callback(actual_qty * 4 // 5, 'API calls completed')
                else:
                    address_data_list = _generate_offline_address_batch(
                        all_ceps,
                        progress_callback=progress_callback,
                        cep_without_dash=cep_without_dash,
                        rng=rng,
                    )

        if progress_callback:
            progress_callback(actual_qty * 9 // 10, 'Finalizing results')

        results_with_state_info = []

        for i in range(actual_qty):
            state_name, state_abbr, city_name = all_state_city_info[i]
            formatted_cep = all_ceps[i] if i < len(all_ceps) else ''
            location_str = f'{city_name} - {formatted_cep}, {state_name} ({state_abbr})'
            location, name_components, documents = results[i]
            results_with_state_info.append((location_str, name_components, documents))

        parsed_results = []
        for i, (location, name_components, documents) in enumerate(results_with_state_info):
            address_data = address_data_list[i] if i < len(address_data_list) else {}
            result_dict = parse_result(location, name_components, documents, state_info=None, address_data=address_data)
            parsed_results.append(result_dict)

        if save_to_jsonl:
            if progress_callback:
                progress_callback(actual_qty * 95 // 100, 'Saving to JSONL file')

            records_to_save = parsed_results if isinstance(parsed_results, list) else [parsed_results]
            if _has_running_event_loop():
                _save_to_jsonl_sync(records_to_save, save_to_jsonl, append=append_to_jsonl)
            else:
                asyncio.run(save_to_jsonl_file(records_to_save, save_to_jsonl, append=append_to_jsonl))

        if progress_callback:
            progress_callback(actual_qty, 'Complete')

        return parsed_results[0] if actual_qty == 1 else parsed_results
    except json.JSONDecodeError as e:
        raise RuntimeError(f'Error generating samples: {e}') from e
    except (ValueError, TypeError):
        raise
    except RuntimeError as e:
        msg = str(e)
        if 'PTBR_SAMPLER_OFFLINE' in msg or 'SHA-256 mismatch' in msg or 'Byte-length mismatch' in msg or 'running event loop' in msg:
            raise
        raise RuntimeError(f'Error generating samples: {e}') from e
    except Exception as e:
        raise RuntimeError(f'Error generating samples: {e}') from e

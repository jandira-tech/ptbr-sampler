"""
Brazilian Sample Generator

Core functionality for generating Brazilian name, location, and document samples.
"""

import asyncio
import copy
import json
import random as _stdlib_random
import threading
from collections import OrderedDict
from collections.abc import Callable
from functools import wraps
from pathlib import Path

import aiofiles

from ptbr_sampler.utils.address_for_offline import AddressProvider_for_offline
from ptbr_sampler.utils.phone import generate_phone_number

from .br_location_class import BrazilianLocationSampler
from .br_name_class import BrazilianNameSampler, Cohort, NameComponents, TimePeriod
from .data_pipeline.registry import UF_CODES
from .document_sampler import DocumentSampler

# Module-level JSON cache to avoid re-parsing on repeated sample() calls.
_json_cache: dict[str, dict] = {}
# Fully initialized samplers are immutable during sampling. Keep a small LRU;
# random streams and scalar document generators remain strictly per call.
_sampler_cache: OrderedDict[tuple, tuple[BrazilianLocationSampler, BrazilianNameSampler]] = OrderedDict()
_SAMPLER_CACHE_SIZE = 8
_sampler_cache_lock = threading.RLock()


def _synchronized_sampler_cache(function):
    """Make cache lookup, construction, and eviction one atomic operation."""

    @wraps(function)
    def synchronized(*args, **kwargs):
        with _sampler_cache_lock:
            return function(*args, **kwargs)

    return synchronized


def _load_json_cached(path: str | Path) -> dict:
    """Load JSON data from a file, returning a cached copy after first load.

    The returned dict is shared — callers that need to mutate it should
    copy it first.
    """
    key = str(Path(path).resolve())
    if key not in _json_cache:
        with Path(path).open(encoding='utf-8') as f:
            _json_cache[key] = json.load(f)
    return _json_cache[key]


def _coin_flip_sexes(n: int, rng: _stdlib_random.Random | None = None) -> list[str]:
    """Draw ``n`` sexes 50/50 for rows with no sex given.

    The module is imported as ``_stdlib_random`` because :func:`sample`
    names its explicit-random flag ``random``.
    """
    rng = _stdlib_random if rng is None else rng
    return [rng.choice(('M', 'F')) for _ in range(n)]


def _resolved_cache_path(path: str | Path | None) -> str | None:
    return str(Path(path).resolve()) if path is not None else None


@_synchronized_sampler_cache
def _get_cached_samplers(
    *,
    json_path: str | Path,
    locations_path: str | Path | None,
    surnames_path: str | Path,
    names_path: str | Path | None,
    middle_names_path: str | Path | None,
    parquet_root: Path | None,
    lru_size: int,
    fixed_uf: str | None,
) -> tuple[BrazilianLocationSampler, BrazilianNameSampler]:
    """Return path-isolated, reusable samplers with their alias LRU intact."""
    key = (
        _resolved_cache_path(json_path),
        _resolved_cache_path(locations_path),
        _resolved_cache_path(surnames_path),
        _resolved_cache_path(names_path),
        _resolved_cache_path(middle_names_path),
        _resolved_cache_path(parquet_root),
        lru_size,
        fixed_uf,
    )
    cached = _sampler_cache.get(key)
    if cached is not None:
        _sampler_cache.move_to_end(key)
        return cached

    location_sampler = BrazilianLocationSampler(copy.deepcopy(_load_json_cached(json_path)))
    if locations_path:
        try:
            locations_data = copy.deepcopy(_load_json_cached(locations_path))
            if 'cities' in locations_data:
                location_sampler.update_cities(locations_data['cities'])
            if 'states' in locations_data:
                location_sampler.update_states(locations_data['states'])
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
            print(f'Warning: Could not use locations_path data: {e}')

    if fixed_uf is not None:
        states = {name: state for name, state in location_sampler.data['states'].items() if state.get('state_abbr') == fixed_uf}
        cities = {key: city for key, city in location_sampler.data['cities'].items() if city.get('city_uf') == fixed_uf}
        if not states or not cities:
            raise ValueError(f'uf {fixed_uf} has no bundled location data')
        location_sampler.data['cities'] = cities
        location_sampler.data['states'] = states
        location_sampler._calculate_weights()

    surnames_data = copy.deepcopy(_load_json_cached(surnames_path))
    name_data = {'surnames': surnames_data['surnames']}
    if names_path:
        name_data.update(copy.deepcopy(_load_json_cached(names_path)))
    name_sampler = BrazilianNameSampler(
        name_data,
        middle_names_path,
        None,
        parquet_root=parquet_root,
        lru_size=lru_size,
    )
    value = (location_sampler, name_sampler)
    _sampler_cache[key] = value
    _sampler_cache.move_to_end(key)
    while len(_sampler_cache) > _SAMPLER_CACHE_SIZE:
        _sampler_cache.popitem(last=False)
    return value


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


def _get_offline_address_data_batch(
    ceps: list[str],
    progress_callback: Callable[[int, str], None] | None = None,
    rng: _stdlib_random.Random | None = None,
) -> list[dict]:
    """Generate offline addresses synchronously, including inside async callers."""
    address_data_list = []
    for i, cep in enumerate(ceps):
        formatted_cep = cep
        if '-' not in formatted_cep and len(formatted_cep) == 8:
            formatted_cep = f'{formatted_cep[:5]}-{formatted_cep[5:]}'

        address_provider = AddressProvider_for_offline()
        address_data_list.append(
            {
                'street': address_provider.street_prefix(rng=rng) + ' ' + address_provider.last_name(rng=rng),
                'neighborhood': address_provider.bairro(rng=rng),
                'building_number': address_provider.building_number(rng=rng),
                'cep': formatted_cep,
            }
        )
        if progress_callback and i % max(1, len(ceps) // 10) == 0:
            progress_callback(0, f'Generating address data: {i + 1}/{len(ceps)}')
    return address_data_list


async def get_address_data_batch(
    ceps: list[str],
    make_api_call: bool = False,
    progress_callback: Callable[[int, str], None] | None = None,
    rng: _stdlib_random.Random | None = None,
) -> list[dict]:
    """Get multiple addresses asynchronously when API enrichment is requested."""
    if not make_api_call:
        return _get_offline_address_data_batch(ceps, progress_callback, rng)

    # Use cep_wrapper to get real data for multiple CEPs
    from .utils.cep_wrapper import workers_for_multiple_cep  # noqa: PLC0415 - optional Node-backed CEP integration stays lazy.

    formatted_ceps = [cep.replace('-', '') for cep in ceps]
    if progress_callback:
        progress_callback(0, 'API calls: Connecting to service')
    cep_data_list = await workers_for_multiple_cep(formatted_ceps)
    if progress_callback:
        progress_callback(0, 'API calls: Processing responses')

    address_data_list = []
    for i, cep_data in enumerate(cep_data_list):
        address_data = {
            'street': '',
            'neighborhood': '',
            'building_number': '',
            'cep': cep_data.get('cep', ''),
            'state': cep_data.get('state', ''),
            'city': cep_data.get('city', ''),
        }
        if 'error' not in cep_data:
            address_data['street'] = cep_data.get('street', '')
            address_data['neighborhood'] = cep_data.get('neighborhood', '')
        address_provider = AddressProvider_for_offline()
        if not address_data['neighborhood']:
            address_data['neighborhood'] = address_provider.bairro(rng=rng)
        if not address_data['street']:
            address_data['street'] = address_provider.street_prefix(rng=rng) + ' ' + address_provider.last_name(rng=rng)
        address_data['building_number'] = address_provider.building_number(rng=rng)
        address_data_list.append(address_data)
        if progress_callback and i % max(1, len(cep_data_list) // 10) == 0:
            progress_callback(0, f'API calls: Processed {i + 1}/{len(cep_data_list)} addresses')

    if progress_callback:
        progress_callback(0, 'API calls processing completed')
    return address_data_list


async def get_address_data(cep: str, make_api_call: bool = False, rng: _stdlib_random.Random | None = None) -> dict:
    """
    Get address data for a single CEP, either from API or generated.

    Args:
        cep: The CEP to get address data for
        make_api_call: Whether to make API calls or generate data

    Returns:
        Dictionary with address data (street, neighborhood, building_number)
    """
    result = await get_address_data_batch([cep], make_api_call, rng=rng)
    return result[0] if result else {}


def sample(
    qty: int,
    q: int | None,
    city_only: bool,
    state_abbr_only: bool,
    state_full_only: bool,
    only_cep: bool,
    cep_without_dash: bool,
    make_api_call: bool,
    time_period: TimePeriod | str | None,
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
    cohort: Cohort | str = Cohort.CURRENT,
    uf: str | None = None,
    lru_size: int = 32,
    rng: _stdlib_random.Random | None = None,
    include_address: bool = True,
    location_only: bool = False,
) -> dict | list[dict]:
    """
    Generate randomized Brazilian profiles composed of name, location, and document fields according to the supplied flags.

    Parameters:
        qty (int): Number of samples to generate.
        q (int | None): Alias for `qty`; if provided, takes precedence.
        city_only (bool): If True, use only city name for the location field.
        state_abbr_only (bool): If True, use only state abbreviation for the location field.
        state_full_only (bool): If True, use only full state name for the location field.
        only_cep (bool): If True, return only a CEP for the location field.
        cep_without_dash (bool): If True, format CEP without a dash (e.g., '12345678').
        make_api_call (bool): If True, attempt API-based address enrichment for CEPs; otherwise generate addresses offline.
        time_period (TimePeriod): Time period used when sampling first names.
        return_only_name (bool): If True, produce name-centric results (no full location by default).
        name_raw (bool): If True, return names in raw form (preserves casing as produced by samplers).
        names_path (str | Path): Optional path to first-name data to merge into the name sampler.
        middle_names_path (str | Path): Optional path to middle-name data for the name sampler.
        only_surname (bool): If True, return only surname components instead of full names.
        top_40 (bool): If True, restrict surname selection to top 40 surnames.
        with_only_one_surname (bool): If True, force a single surname instead of multiple.
        always_middle (bool): If True, always include a middle name when sampling full names.
        only_middle (bool): If True, return only middle-name components.
        always_cpf / always_pis / always_cnpj / always_cei / always_rg / always_phone (bool):
            If True, include the respective document/phone in generated profiles.
        only_cpf / only_pis / only_cnpj / only_cei / only_rg / only_fone (bool):
            If True, generate exclusively the specified document(s) or phone.
        include_issuer (bool): When generating RG, include the issuing state if requested.
        only_document (bool): If True, produce document-only results (no name/location unless combined via other flags).
        surnames_path (str | Path): Path to surnames data used by the name sampler.
        json_path (str | Path): Path to bundled city/state JSON used to initialize the location sampler.
        locations_path (str | Path): Optional override JSON with custom `cities`/`states` to update the
            location sampler; failures are logged and ignored.
        save_to_jsonl (str | None): If provided, path to write results as newline-delimited JSON; saved via an async writer.
        all_data (bool): If True, enable all `always_*` outputs and disable mutually exclusive `only_*`/`only_*` output restrictions.
        progress_callback (Callable[[int, str], None] | None): Optional callback receiving (completed_count, message) to report progress.
        append_to_jsonl (bool): If True, append to `save_to_jsonl` file instead of overwriting.
        random (bool): If True, switch to the explicit-random escape hatch:
            uniform location and final name/surname support sampling. The
            corpus-derived 30.99% middle-name incidence remains unchanged.
            The default (False) keeps
            realism-by-default sampling — geography first via population
            weights, then names from the IBGE-derived alias tables. See the
            "Realism vs. random mode" section in the README for details.
        cohort (Cohort | str): current (default), census2022, or newborn2025.
            An explicit period disables blending; only current + period is allowed.
        uf (str | None): Optional fixed UF for location, names, and surnames.
        rng (random.Random | None): Optional injected stream. Every random
            selection, including the private NumPy alias seed, comes from this
            object. ``None`` uses Python's module-global stream as before.
        include_address (bool): Generate street/neighborhood/building fields.
            Scalar adapters disable this to avoid unrelated address work.
        location_only (bool): Skip first-name and surname generation while
            retaining location selection. Intended for scalar location APIs.
        lru_size (int): Per-sampler Parquet alias cache capacity and part of the
            high-level resource-cache key.
        experimental_uf_sex_conditioning (bool): Compatibility flag. If True
            and no sex was selected, use mixed 50/50 sex. UF conditioning is
            always active and no longer depends on this flag.
        sex_conditioning (str | None): Drive first-name sampling from selected
            cohort or historical M/F partitions. Modern data applies the
            national empirical IBGE 2022 sex prior and renormalizes; it does not
            claim observed UF-sex tables. Accepts:
              * ``'M'`` — every row uses the male-conditioned distribution
              * ``'F'`` — every row uses the female-conditioned distribution
              * ``'mixed'`` — choose M/F independently, 50/50 per row
              * ``None`` (default) — retain the unconditioned distribution
            Compatible with ``experimental_uf_sex_conditioning``: when both
            are on, UF still comes from the sampled location and sex from
            this argument. Missing bundled modern partitions raise clearly;
            custom historical fixtures use the resolution chain documented in
            ``BrazilianNameSampler._first_names_table``.

    Returns:
        dict: A single generated sample when a single result was requested.
        list[dict]: A list of generated samples when multiple results were requested.
    """
    # Selector errors are part of the public contract and must not be hidden by
    # the broad RuntimeError compatibility wrapper below.
    selected_cohort = Cohort(cohort)
    selected_period = TimePeriod(time_period) if time_period is not None else None
    if selected_period is not None and selected_cohort is not Cohort.CURRENT:
        raise ValueError('cohort census2022/newborn2025 cannot be combined with an explicit time_period')
    fixed_uf = uf.strip().upper() if isinstance(uf, str) else uf
    if fixed_uf is not None and fixed_uf not in UF_CODES:
        raise ValueError(f'uf must be one of {", ".join(UF_CODES)}; got {uf!r}')

    # Handle q parameter alias (takes precedence over qty)
    actual_qty = q if q is not None else qty

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

    try:
        parquet_root = Path(__file__).resolve().parent / 'data' / 'parquet'
        location_sampler, name_sampler = _get_cached_samplers(
            json_path=json_path,
            locations_path=locations_path,
            surnames_path=surnames_path,
            names_path=names_path,
            middle_names_path=middle_names_path,
            parquet_root=parquet_root if parquet_root.exists() else None,
            lru_size=lru_size,
            fixed_uf=fixed_uf,
        )
        doc_sampler = DocumentSampler()

        # Initialize results list and parallel state/city tracking so the
        # address phase can reuse the same draws without a second batch.
        results: list[tuple[str, NameComponents, dict[str, str]]] = []
        state_city_info: list[tuple[str, str, str]] = []

        # Resolve sex_conditioning once and pre-compute the per-row sex list
        # so every name-generation branch (single-row, batch, or
        # return-only-name) honours the same conditioning.
        sex_conditioning_norm: str | None = None
        if sex_conditioning is not None:
            sc = str(sex_conditioning).strip().upper()
            if sc not in ('M', 'F', 'MIXED'):
                raise ValueError(f"sex_conditioning must be 'M', 'F', 'mixed', or None; got {sex_conditioning!r}")
            sex_conditioning_norm = sc
        per_row_sexes: list[str] | None = None
        samples_first_names = not (
            location_only
            or only_document
            or any([only_cpf, only_pis, only_cnpj, only_cei, only_rg, only_fone])
            or only_surname
            or only_middle
        )
        if samples_first_names and sex_conditioning_norm == 'MIXED':
            per_row_sexes = _coin_flip_sexes(actual_qty, rng=rng)
        elif samples_first_names and sex_conditioning_norm in ('M', 'F'):
            per_row_sexes = [sex_conditioning_norm] * actual_qty

        if only_document:
            # Document-only generation with proper state handling
            for i in range(actual_qty):
                documents = {}

                # Generate location first to get proper state for RG
                state_name, state_abbr, city_name = location_sampler.get_state_and_city(random_mode=random, rng=rng)
                state_city_info.append((state_name, state_abbr, city_name))

                # Generate all requested documents
                if always_cpf or only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf(rng=rng)
                if always_pis or only_pis:
                    documents['pis'] = doc_sampler.generate_pis(rng=rng)
                if always_cnpj or only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj(rng=rng)
                if always_cei or only_cei:
                    documents['cei'] = doc_sampler.generate_cei(rng=rng)
                if always_rg or only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, rng=rng)}'
                if always_phone or only_fone:
                    # Get the DDD from the city data
                    city_data = location_sampler.city_data_by_name.get(city_name, {})
                    ddd = city_data.get('ddd', None)
                    documents['phone'] = generate_phone_number(ddd, rng=rng)

                results.append((None, None, documents))

                # Report progress if callback is provided
                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating documents')

        elif any([only_cpf, only_pis, only_cnpj, only_cei, only_rg, only_fone]):
            # Handle document-only generation with proper state handling
            for i in range(actual_qty):
                documents = {}

                # No need to reload location data - already loaded once at the beginning

                # Generate location first to get proper state for RG
                state_name, state_abbr, city_name = location_sampler.get_state_and_city(random_mode=random, rng=rng)
                state_city_info.append((state_name, state_abbr, city_name))
                if only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf(rng=rng)
                if only_pis:
                    documents['pis'] = doc_sampler.generate_pis(rng=rng)
                if only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj(rng=rng)
                if only_cei:
                    documents['cei'] = doc_sampler.generate_cei(rng=rng)
                if only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, rng=rng)}'
                if only_fone:
                    # Get the DDD from the city data
                    city_data = location_sampler.city_data_by_name.get(city_name, {})
                    ddd = city_data.get('ddd', None)
                    documents['phone'] = generate_phone_number(ddd, rng=rng)

                results.append((None, None, documents))

                # Report progress if callback is provided
                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating specific documents')

        elif return_only_name or only_surname or only_middle:
            # Name-only generation. First names take the same UF / sex
            # conditioning as the full-profile batch path below; the surname
            # and middle-name forks draw no first name, so they flip no coins.
            name_only_sexes = per_row_sexes
            draws_first_names = not (only_surname or only_middle)
            if experimental_uf_sex_conditioning and name_only_sexes is None and draws_first_names:
                name_only_sexes = _coin_flip_sexes(actual_qty, rng=rng)
            for i in range(actual_qty):
                documents = {}
                name_components = None

                # No need to reload location data - already loaded once at the beginning

                # Generate location first to get proper state and DDD
                state_name, state_abbr, city_name = location_sampler.get_state_and_city(random_mode=random, rng=rng)
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
                            uf=state_abbr,
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
                        time_period=selected_period,
                        cohort=selected_cohort,
                        raw=name_raw,
                        include_surname=True,
                        top_40=top_40,
                        with_only_one_surname=with_only_one_surname,
                        always_middle=always_middle,
                        return_components=True,
                        random_mode=random,
                        uf=state_abbr,
                        sex=name_only_sexes[i] if name_only_sexes is not None else None,
                        rng=rng,
                    )

                    # Add documents for full names
                    if always_cpf:
                        documents['cpf'] = doc_sampler.generate_cpf(rng=rng)
                    if always_pis:
                        documents['pis'] = doc_sampler.generate_pis(rng=rng)
                    if always_cnpj:
                        documents['cnpj'] = doc_sampler.generate_cnpj(rng=rng)
                    if always_cei:
                        documents['cei'] = doc_sampler.generate_cei(rng=rng)
                    if always_rg:
                        # Use the generated state for RG
                        documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, rng=rng)}'
                    if always_phone:
                        # Get the DDD from the city data
                        city_data = location_sampler.city_data_by_name.get(city_name, {})
                        ddd = city_data.get('ddd', None)
                        documents['phone'] = generate_phone_number(ddd, rng=rng)

                # Add the location string for name-only results
                location_str = f'{city_name} - , {state_name} ({state_abbr})'
                results.append((location_str, name_components, documents))

                # Report progress if callback is provided
                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating names')
        else:
            # Full sample generation with location, name, and documents.
            # The batch path is now unconditional: ``k=1`` and ``k=N`` go
            # through the same vectorised alias lookup. ``--batch`` is a
            # flush-to-disk cadence (see ``save_to_jsonl`` below), not a
            # sampling-strategy switch.
            batch_locations = location_sampler.batch_sample_locations(actual_qty, random_mode=random, rng=rng)
            # Build per-row UF / sex for mixed conditioning. Name tables use
            # the precomputed conditionals and fail clearly when a selected
            # bundled modern artifact is missing rather than substituting data.
            batch_ufs: list[str] | None = [loc['state_abbr'] for loc in batch_locations]
            batch_sexes: list[str] | None = per_row_sexes
            if not location_only and experimental_uf_sex_conditioning and batch_sexes is None:
                # Compatibility flag now only enables mixed sex when the caller
                # made no explicit choice; UF conditioning is always active.
                batch_sexes = _coin_flip_sexes(actual_qty, rng=rng)
            batch_names = (
                [NameComponents('', None, '') for _ in range(actual_qty)]
                if location_only
                else name_sampler.batch_sample_names(
                    actual_qty,
                    time_period=selected_period,
                    cohort=selected_cohort,
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
            )

            for i in range(actual_qty):
                documents = {}

                loc = batch_locations[i]
                state_name, state_abbr, city_name = loc['state_name'], loc['state_abbr'], loc['city_name']

                state_city_info.append((state_name, state_abbr, city_name))

                # Format location string
                if city_only:
                    location = city_name
                elif state_abbr_only:
                    location = state_abbr
                elif state_full_only:
                    location = state_name
                elif only_cep:
                    location = location_sampler._get_random_cep_for_city(city_name, rng=rng)
                    location = location_sampler._format_cep(location, not cep_without_dash)
                else:
                    location = location_sampler.format_full_location(
                        city_name, state_name, state_abbr, include_cep=True, cep_without_dash=cep_without_dash, rng=rng
                    )

                # Generate documents using the correct state
                if always_cpf or only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf(rng=rng)
                if always_pis or only_pis:
                    documents['pis'] = doc_sampler.generate_pis(rng=rng)
                if always_cnpj or only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj(rng=rng)
                if always_cei or only_cei:
                    documents['cei'] = doc_sampler.generate_cei(rng=rng)
                if always_rg or only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer, rng=rng)}'
                if always_phone or only_fone:
                    city_data = location_sampler.city_data_by_name.get(city_name, {})
                    ddd = city_data.get('ddd', None)
                    documents['phone'] = generate_phone_number(ddd, rng=rng)

                name_components = batch_names[i]

                results.append((location, name_components, documents))

                # Report progress if callback is provided
                if progress_callback and i % max(1, actual_qty // 100) == 0:
                    progress_callback(i + 1, 'Generating complete profiles')

        # Collect all CEPs that will be used
        all_ceps = []
        all_state_city_info = list(state_city_info)

        # Update progress to indicate we're starting address generation
        if progress_callback:
            progress_callback(actual_qty // 2, 'Preparing address data')  # Show approximately half-way progress

        # Reuse state_city_info from the primary generation phase so RG state,
        # phone DDD, and the final output location remain consistent.
        for i in range(actual_qty):
            state_name, state_abbr, city_name = all_state_city_info[i]

            # Get a random CEP for the city
            cep = location_sampler._get_random_cep_for_city(city_name, rng=rng)
            formatted_cep = location_sampler._format_cep(cep, not cep_without_dash)
            all_ceps.append(formatted_cep)

        # Update progress to indicate we're making API calls if applicable
        if progress_callback and make_api_call:
            progress_callback(actual_qty * 3 // 4, 'API calls starting')  # Show approximately 75% progress

        # Offline addresses never need an event loop. API enrichment remains
        # asynchronous; reject sync use in an active loop before constructing
        # a coroutine so callers never receive an unawaited-coroutine leak.
        if not include_address:
            address_data_list = [{} for _ in all_ceps]
        elif make_api_call:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError('make_api_call=True cannot be used from synchronous sample() inside a running event loop')
            address_data_list = asyncio.run(get_address_data_batch(all_ceps, True, progress_callback, rng=rng))
        else:
            address_data_list = _get_offline_address_data_batch(all_ceps, progress_callback, rng)

        # Update progress to indicate API calls are complete
        if progress_callback and make_api_call:
            progress_callback(actual_qty * 4 // 5, 'API calls completed')

        # Update progress to indicate we're finalizing results
        if progress_callback:
            progress_callback(actual_qty * 9 // 10, 'Finalizing results')  # Show approximately 90% progress

        # Modify the results to include state_info and address data
        results_with_state_info = []

        for i in range(actual_qty):
            state_name, state_abbr, city_name = all_state_city_info[i]
            formatted_cep = all_ceps[i]

            # Format the full location string with CEP
            # The parse_result function expects the format: "city - cep, state (abbr)"
            location_str = f'{city_name} - {formatted_cep}, {state_name} ({state_abbr})'

            # Get the corresponding result
            location, name_components, documents = results[i]

            # Update the phone number to use the correct DDD
            if 'phone' in documents:
                # Get the DDD from the city data
                city_data = location_sampler.city_data_by_name.get(city_name, {})
                ddd = city_data.get('ddd', None)
                documents['phone'] = generate_phone_number(ddd, rng=rng)

            # Add to the new results list with state_info
            results_with_state_info.append((location_str, name_components, documents))

        # Convert results to dictionary format
        parsed_results = []
        for i, (location, name_components, documents) in enumerate(results_with_state_info):
            # Get the corresponding address data
            address_data = address_data_list[i] if i < len(address_data_list) else {}

            # Parse the location string to extract city, state, and CEP
            result_dict = parse_result(location, name_components, documents, state_info=None, address_data=address_data)
            parsed_results.append(result_dict)

        # Save to JSONL if requested
        if save_to_jsonl:
            if progress_callback:
                progress_callback(actual_qty * 95 // 100, 'Saving to JSONL file')

            # parsed_results is always assembled as a list above; the type
            # check and else branch are kept for defense-in-depth.
            if isinstance(parsed_results, list):
                asyncio.run(save_to_jsonl_file(parsed_results, save_to_jsonl, append=append_to_jsonl))
            else:  # pragma: no cover - defensive branch; parsed_results is always a list
                asyncio.run(save_to_jsonl_file([parsed_results], save_to_jsonl, append=append_to_jsonl))

        # Final progress update to indicate completion
        if progress_callback:
            progress_callback(actual_qty, 'Complete')

        return parsed_results[0] if actual_qty == 1 else parsed_results
    except Exception as e:
        # Re-raise the exception with more context
        raise RuntimeError(f'Error generating samples: {e}') from e

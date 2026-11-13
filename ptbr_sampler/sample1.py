import json
from pathlib import Path

from .br_location_class import BrazilianLocationSampler
from .br_name_class import BrazilianNameSampler, NameComponents, TimePeriod
from .document_sampler import DocumentSampler


def parse_result(
    location: str, name_components: NameComponents, documents: dict[str, str], state_info: tuple[str, str, str] | None = None
) -> dict:
    """Parse sample results into a standardized dictionary format.

    Args:
        location: Full location string
        name_components: Named tuple with name components
        documents: Dictionary of document numbers
        state_info: Optional tuple of (state_name, state_abbr, city_name)

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
        'cpf': documents.get('cpf', ''),
        'rg': documents.get('rg', ''),
        'pis': documents.get('pis', ''),
        'cnpj': documents.get('cnpj', ''),
        'cei': documents.get('cei', ''),
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

    return result


def save_to_jsonl_file(data: list[dict], filename: str) -> None:
    """Save generated samples to a JSONL file.

    Args:
        data: List of dictionaries containing sample data
        filename: Path to the output JSONL file
    """
    with Path(filename).open('w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def sample(
    qty: int,
    q: int | None,
    city_only: bool,
    state_abbr_only: bool,
    state_full_only: bool,
    only_cep: bool,
    cep_without_dash: bool,
    time_period: TimePeriod,
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
    only_cpf: bool,
    only_pis: bool,
    only_cnpj: bool,
    only_cei: bool,
    only_rg: bool,
    include_issuer: bool,
    only_document: bool,
    surnames_path: str | Path,
    locations_path: str | Path,
    save_to_jsonl: str | None,
    all_data: bool,
) -> dict | list[dict]:
    """
    Generate randomized Brazilian samples containing location, name, and document fields.

    Generates one or more samples combining location (city, state, CEP), name components (given, middle, surnames) and issued documents (CPF, PIS, CNPJ, CEI, RG) according to the provided flags. The `q` parameter, when given, takes precedence over `qty`. If `all_data` is True, the function forces inclusion of all data types and clears mutually exclusive "only" flags. If `save_to_jsonl` is provided, the generated samples are written to that file in JSONL format.

    Parameters:
        qty (int): Default number of samples to generate.
        q (int | None): Alias for `qty` that takes precedence when not None.
        time_period (TimePeriod): Time period constraint used when sampling names.
        name_raw (bool): When True, sample names use raw formatting (e.g., uppercase).
        include_issuer (bool): When True, include RG issuing-state information in generated RG values.
        save_to_jsonl (str | None): Path to write results as JSONL; if None, results are not saved.
        all_data (bool): When True, include all possible fields and disable mutually exclusive "only" flags.

    Returns:
        dict: A single sample when the effective quantity is 1.
        list[dict]: A list of samples when the effective quantity is greater than 1.
    """
    # Handle q parameter alias (takes precedence over qty)
    actual_qty = q if q is not None else qty

    # If all_data is True, override other flags to include everything
    if all_data:
        always_cpf = True
        always_pis = True
        always_cnpj = True
        always_cei = True
        always_rg = True
        always_middle = True
        only_cpf = False
        only_pis = False
        only_cnpj = False
        only_cei = False
        only_rg = False
        only_surname = False
        only_middle = False
        only_cep = False
        city_only = False
        state_abbr_only = False
        state_full_only = False
        return_only_name = False
        only_document = False

    try:
        # Initialize samplers separately
        location_sampler = BrazilianLocationSampler(json_path)
        doc_sampler = DocumentSampler()

        # Load location data if provided
        if locations_path:
            try:
                with Path(locations_path).open(encoding='utf-8') as f:
                    locations_data = json.load(f)
                    # Use locations data if available
                    if 'cities' in locations_data:
                        location_sampler.update_cities(locations_data['cities'])
                    if 'states' in locations_data:
                        location_sampler.update_states(locations_data['states'])
            except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError) as e:
                # Log but continue with default data
                print(f'Warning: Could not use locations_path data: {e}')

        # Load surnames data for name sampler
        with Path(surnames_path).open(encoding='utf-8') as f:
            surnames_data = json.load(f)

        # Create complete data for name sampler
        name_data = {'surnames': surnames_data['surnames']}
        if names_path:
            with Path(names_path).open(encoding='utf-8') as f:
                names_data = json.load(f)
                name_data.update(names_data)

        name_sampler = BrazilianNameSampler(
            None,
            middle_names_path,
            None,  # No need for names_path as we've already loaded it
            preloaded_data=name_data,
        )

        # Initialize results list
        results: list[tuple[str, NameComponents, dict[str, str]]] = []

        if only_document:
            # Document-only generation with proper state handling
            for _ in range(actual_qty):
                documents = {}
                # Generate location first to get proper state for RG
                state_name, state_abbr, city_name = location_sampler.get_state_and_city()

                # Generate all requested documents
                if always_cpf or only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf()
                if always_pis or only_pis:
                    documents['pis'] = doc_sampler.generate_pis()
                if always_cnpj or only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj()
                if always_cei or only_cei:
                    documents['cei'] = doc_sampler.generate_cei()
                if always_rg or only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer)}'

                results.append((None, None, documents))
        elif return_only_name or only_surname or only_middle:
            # Name-only generation
            for _ in range(actual_qty):
                documents = {}
                name_components = None

                if only_surname:
                    name_components = NameComponents(
                        '', None, name_sampler.get_random_surname(top_40=top_40, raw=name_raw, with_only_one_surname=with_only_one_surname)
                    )
                elif only_middle:
                    name_components = name_sampler.get_random_name(raw=name_raw, only_middle=True, return_components=True)
                else:
                    name_components = name_sampler.get_random_name(
                        time_period=time_period,
                        raw=name_raw,
                        include_surname=True,
                        top_40=top_40,
                        with_only_one_surname=with_only_one_surname,
                        always_middle=always_middle,
                        return_components=True,
                    )

                    # Add documents for full names
                    if always_cpf:
                        documents['cpf'] = doc_sampler.generate_cpf()
                    if always_pis:
                        documents['pis'] = doc_sampler.generate_pis()
                    if always_cnpj:
                        documents['cnpj'] = doc_sampler.generate_cnpj()
                    if always_cei:
                        documents['cei'] = doc_sampler.generate_cei()
                    if always_rg:
                        # Use SP as default state for name-only results
                        documents['rg'] = f'{doc_sampler.generate_rg("SP", include_issuer)}'

                results.append((None, name_components, documents))

        elif any([only_cpf, only_pis, only_cnpj, only_cei, only_rg]):
            # Handle document-only generation with proper state handling
            for _ in range(actual_qty):
                documents = {}
                # Generate location first to get proper state for RG
                state_name, state_abbr, city_name = location_sampler.get_state_and_city()

                if only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf()
                if only_pis:
                    documents['pis'] = doc_sampler.generate_pis()
                if only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj()
                if only_cei:
                    documents['cei'] = doc_sampler.generate_cei()
                if only_rg:
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer)}'

                results.append((None, None, documents))

        else:
            # Full sample generation with location, name, and documents
            for _ in range(actual_qty):
                documents = {}

                # Generate location first to ensure proper state handling
                state_name, state_abbr, city_name = location_sampler.get_state_and_city()

                # Format location string
                if city_only:
                    location = city_name
                elif state_abbr_only:
                    location = state_abbr
                elif state_full_only:
                    location = state_name
                elif only_cep:
                    location = location_sampler._get_random_cep_for_city(city_name)
                    location = location_sampler._format_cep(location, not cep_without_dash)
                else:
                    location = location_sampler.format_full_location(
                        city_name, state_name, state_abbr, include_cep=True, cep_without_dash=cep_without_dash
                    )

                # Generate documents using the correct state
                if always_cpf or only_cpf:
                    documents['cpf'] = doc_sampler.generate_cpf()
                if always_pis or only_pis:
                    documents['pis'] = doc_sampler.generate_pis()
                if always_cnpj or only_cnpj:
                    documents['cnpj'] = doc_sampler.generate_cnpj()
                if always_cei or only_cei:
                    documents['cei'] = doc_sampler.generate_cei()
                if always_rg or only_rg:
                    # Always use the state from our location for RG generation
                    documents['rg'] = f'{doc_sampler.generate_rg(state_abbr, include_issuer)}'

                # Generate name components if needed
                name_components = None

                name_components = name_sampler.get_random_name(
                    time_period=time_period,
                    raw=name_raw,
                    include_surname=True,
                    top_40=top_40,
                    with_only_one_surname=with_only_one_surname,
                    always_middle=always_middle,
                    return_components=True,
                )

                results.append((location, name_components, documents))

        # Convert results to dictionary format
        parsed_results = [
            parse_result(
                location, name_components, documents, state_info=(state_name, state_abbr, city_name) if 'state_name' in locals() else None
            )
            for location, name_components, documents in results
        ]

        # Save to JSONL if requested
        if save_to_jsonl:
            if isinstance(parsed_results, list):
                save_to_jsonl_file(parsed_results, save_to_jsonl)
            else:
                save_to_jsonl_file([parsed_results], save_to_jsonl)

        return parsed_results[0] if actual_qty == 1 else parsed_results

    except Exception as e:
        # Re-raise the exception with more context
        raise RuntimeError(f'Error generating samples: {e}') from e

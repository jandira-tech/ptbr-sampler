import json
import sys
from collections import Counter
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

import typer
from loguru import logger
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from ptbr_sampler.br_name_class import NameComponents, TimePeriod
from ptbr_sampler.data_origins import DATA_ORIGINS
from ptbr_sampler.datasets import (
    clear_dataset_cache,
    dataset_cache_status,
    prefetch_datasets,
)
from ptbr_sampler.sampler import sample as sampler_sample

# Default data files ship inside the installed package (or resolve lazily from HF).
# Resolve relative to ``__file__`` so ``ptbr generate`` works from any cwd.
_PACKAGE_DATA = Path(__file__).resolve().parent / 'data'

# Configure logger
logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    colorize=True,
    format='<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{line}</cyan> - <level>{message}</level>',
    filter=lambda record: record['level'].name != 'DEBUG' and not record['extra'].get('quiet', False),
    level='INFO',
    backtrace=True,
    diagnose=True,
)

# Configure Brasilia timezone (UTC-3)
BRASILIA_TZ = timezone(timedelta(hours=-3))

# Configure logger with Brasilia timezone
logger.configure(extra={'timezone': BRASILIA_TZ, 'quiet': False})

console = Console()
app = typer.Typer(help='BR data sampler CLI', add_completion=False)
datasets_app = typer.Typer(help='Inspect, prefetch, or clear cached Hugging Face runtime datasets.', add_completion=False)
app.add_typer(datasets_app, name='datasets')

# Define options at module level organized by panels
# Basic options
DEFAULT_QTY = typer.Option(1, '--qty', '-q', '-n', help='Number of samples to generate', rich_help_panel='Basic Options')
ALL_DATA = typer.Option(False, '--all', '-a', help='Include all possible data in the generated samples', rich_help_panel='Basic Options')
SAVE_TO_JSONL = typer.Option(None, '--save-to-jsonl', '-sj', help='Save generated samples to a JSONL file', rich_help_panel='Basic Options')
APPEND_TO_JSONL = typer.Option(True, '--append', '-ap', help='Append to JSONL file instead of overwriting', rich_help_panel='Basic Options')
OUTPUT_FORMAT = typer.Option(
    'table',
    '--format',
    help="Output format: 'table' (default), 'json', or 'jsonl'.",
    rich_help_panel='Basic Options',
)
QUIET = typer.Option(
    False,
    '--quiet',
    help='Suppress progress bars and status banners.',
    rich_help_panel='Basic Options',
)
# New convenience options
BATCH = typer.Option(
    None,
    '--batch',
    '-b',
    help='Maximum samples per batch before saving (processes large requests in smaller chunks)',
    rich_help_panel='Basic Options',
)
EASY = typer.Option(
    None, '--easy', '-e', help='Easy mode with integer qty (enables API calls, all data, and auto-saves)', rich_help_panel='Basic Options'
)
RANDOM_MODE = typer.Option(
    False,
    '--random',
    help=(
        'Explicit random mode (opt-out of realism): uniform location and name draws, '
        'flat 50% middle-name flag. Default is realism-by-default (population-weighted).'
    ),
    rich_help_panel='Basic Options',
)
CENSUS_YEAR = typer.Option(
    2022,
    '--census-year',
    help='IBGE Census vintage: 2022 (default) or 2010 (historical).',
    rich_help_panel='Basic Options',
)
CONDITIONING_MODE = typer.Option(
    'strict',
    '--conditioning-mode',
    help="Conditioning mode for 2022 multi-dimensional queries: 'strict' (default) or 'estimated'.",
    rich_help_panel='Basic Options',
)
UF_CONDITIONING = typer.Option(
    False,
    '--uf-conditioning',
    help='Condition name and surname draws on the sampled state (UF).',
    rich_help_panel='Basic Options',
)
EXPERIMENTAL_UF_SEX = typer.Option(
    False,
    '--experimental-uf-sex',
    help=(
        'EXPERIMENTAL: condition first-name draws on the sampled UF and a '
        '50/50-drawn sex. On Census 2022, requires --conditioning-mode estimated.'
    ),
    rich_help_panel='Basic Options',
)
SEX_CONDITIONING = typer.Option(
    None,
    '--sex-conditioning',
    help=(
        "Condition first-name draws on sex. Accepts 'M', 'F', 'mixed' (50/50), "
        "or 'population' (observed 2022 national sex share; requires --census-year 2022)."
    ),
    rich_help_panel='Basic Options',
)

# Location options
CITY_ONLY = typer.Option(False, '--city-only', '-c', help='Return only city names', rich_help_panel='Location Options')
STATE_ABBR_ONLY = typer.Option(
    False, '--state-abbr-only', '-sa', help='Return only state abbreviations', rich_help_panel='Location Options'
)
STATE_FULL_ONLY = typer.Option(False, '--state-full-only', '-sf', help='Return only full state names', rich_help_panel='Location Options')
ONLY_CEP = typer.Option(False, '--only-cep', '-oc', help='Return only CEP', rich_help_panel='Location Options')
CEP_WITHOUT_DASH = typer.Option(False, '--cep-without-dash', '-nd', help='Return CEP without dash', rich_help_panel='Location Options')
MAKE_API_CALL = typer.Option(
    False,
    '--make-api-call',
    '-mac',
    help='Make API calls to retrieve real CEP data instead of generating synthetic address data',
    rich_help_panel='Location Options',
)

# Name options
TIME_PERIOD = typer.Option(
    None,
    '--time-period',
    '-t',
    help='Time period for name sampling (defaults to all for 2022, ate2010 for 2010).',
    rich_help_panel='Name Options',
)
RETURN_ONLY_NAME = typer.Option(
    False, '--return-only-name', '-rn', help='Return only the name without location', rich_help_panel='Name Options'
)
NAME_RAW = typer.Option(False, '--name-raw', '-r', help='Return names in raw format (all caps)', rich_help_panel='Name Options')
ONLY_SURNAME = typer.Option(False, '--only-surname', '-s', help='Return only surname', rich_help_panel='Name Options')
TOP_40 = typer.Option(False, '--top-40', '-t40', help='Use only top 40 surnames', rich_help_panel='Name Options')
WITH_ONLY_ONE_SURNAME = typer.Option(
    False, '--one-surname', '-os', help='Return only one surname instead of two', rich_help_panel='Name Options'
)
ALWAYS_MIDDLE = typer.Option(False, '--always-middle', '-am', help='Always include a middle name', rich_help_panel='Name Options')
ONLY_MIDDLE = typer.Option(False, '--only-middle', '-om', help='Return only middle name', rich_help_panel='Name Options')

# Document options
ONLY_DOCUMENT = typer.Option(False, '--only-document', '-od', help='Return only documents', rich_help_panel='Document Options')
ALWAYS_CPF = typer.Option(True, '--always-cpf', '-ac', help='Always include CPF', rich_help_panel='Document Options')
ALWAYS_PIS = typer.Option(False, '--always-pis', '-ap', help='Always include PIS', rich_help_panel='Document Options')
ALWAYS_CNPJ = typer.Option(False, '--always-cnpj', '-acn', help='Always include CNPJ', rich_help_panel='Document Options')
ALWAYS_CEI = typer.Option(False, '--always-cei', '-ace', help='Always include CEI', rich_help_panel='Document Options')
ALWAYS_RG = typer.Option(True, '--always-rg', '-ar', help='Always include RG', rich_help_panel='Document Options')
ALWAYS_PHONE = typer.Option(True, '--always-phone', '-aph', help='Always include phone number', rich_help_panel='Local e Fone')
ONLY_CPF = typer.Option(False, '--only-cpf', '-ocpf', help='Return only CPF', rich_help_panel='Document Options')
ONLY_PIS = typer.Option(False, '--only-pis', '-op', help='Return only PIS', rich_help_panel='Document Options')
ONLY_CNPJ = typer.Option(False, '--only-cnpj', '-ocn', help='Return only CNPJ', rich_help_panel='Document Options')
ONLY_CEI = typer.Option(False, '--only-cei', '-oce', help='Return only CEI', rich_help_panel='Document Options')
ONLY_RG = typer.Option(False, '--only-rg', '-or', help='Return only RG', rich_help_panel='Document Options')
ONLY_FONE = typer.Option(False, '--only-fone', '-of', help='Return only phone number', rich_help_panel='Local e Fone')
INCLUDE_ISSUER = typer.Option(
    True, '--include-issuer', '-ii', help='Include issuer in RG (default: True)', rich_help_panel='Document Options'
)

# Data source options — default to the package-bundled JSON files.
JSON_PATH = typer.Option(
    str(_PACKAGE_DATA / 'cities_with_ceps.json'),
    '--json-path',
    '-j',
    help='Path to the cities and CEPs data JSON file',
    rich_help_panel='Data Source Options',
)
NAMES_PATH = typer.Option(
    str(_PACKAGE_DATA / 'names_data.json'),
    '--names-path',
    '-np',
    help='Path to the first names data JSON file',
    rich_help_panel='Data Source Options',
)
MIDDLE_NAMES_PATH = typer.Option(
    str(_PACKAGE_DATA / 'middle_names.json'),
    '--middle-names-path',
    '-mnp',
    help='Path to the middle names JSON file',
    rich_help_panel='Data Source Options',
)
SURNAMES_PATH = typer.Option(
    str(_PACKAGE_DATA / 'surnames_data.json'),
    '--surnames-path',
    '-sp',
    help='Path to the surnames JSON file',
    rich_help_panel='Data Source Options',
)
LOCATIONS_PATH = typer.Option(
    str(_PACKAGE_DATA / 'locations_data.json'),
    '--locations-path',
    '-lp',
    help='Path to the locations data JSON file',
    rich_help_panel='Data Source Options',
)


def _format_document_lines(doc: dict[str, str]) -> list[str]:
    """Format document information into display lines.

    This function processes document information and formats it into
    a list of strings suitable for display. It handles special
    formatting for RG numbers which include state information.

    Args:
        doc: Dictionary containing document information
             Keys can be: 'cpf', 'pis', 'cnpj', 'cei', 'rg', 'phone'

    Returns:
        List of formatted document strings
    """
    doc_lines = []

    # Handle documents in a specific order
    if 'cpf' in doc:
        doc_lines.append(f'CPF: {doc["cpf"]}')
    if 'rg' in doc:
        if '/' in doc['rg']:  # RG with state information
            rg_num, state = doc['rg'].split('/')
            doc_lines.append(f'RG: {rg_num} ({state})')
        else:
            doc_lines.append(f'RG: {doc["rg"]}')
    if 'pis' in doc:
        doc_lines.append(f'PIS: {doc["pis"]}')
    if 'cnpj' in doc:
        doc_lines.append(f'CNPJ: {doc["cnpj"]}')
    if 'cei' in doc:
        doc_lines.append(f'CEI: {doc["cei"]}')
    if 'phone' in doc:
        doc_lines.append(f'Telefone: {doc["phone"]}')

    return doc_lines


def create_results_table(
    results: list[tuple[str | None, NameComponents, dict[str, Any], dict[str, Any]]],
    title: str,
    return_only_name: bool = False,
    only_location: bool = False,
    only_document: bool = False,
) -> Table:
    """Create a formatted table for displaying Brazilian sample data results.

    This function creates a rich, formatted table that handles complex Brazilian name patterns,
    including compound names, surnames with prefixes, and various document types.

    Args:
        results: List of tuples containing:
                - location string
                - NameComponents object (first_name, middle_name, surname)
                - Dictionary of documents
                - Dictionary of address data (street, neighborhood, building_number)
        title: The title to display at the top of the table
        return_only_name: If True, displays only name information
        only_location: If True, displays only location information
        only_document: If True, displays only document information

    Returns:
        Rich Table object formatted according to specifications

    The table structure adapts based on the content type:
    - Full display: ID, Name, Middle Name, Surname, Location, Documents
    - Name only: ID, Name, Middle Name, Surname
    - Location only: ID, Location
    - Document only: ID, Documents
    """
    table = Table(
        title=title,
        show_lines=True,  # Add horizontal lines between rows
        show_edge=True,  # Show table edges
        padding=(0, 1),  # Add minimal padding for readability
        title_style='bold yellow',
        border_style='blue',
        header_style='bold blue',
        expand=True,
        collapse_padding=True,
    )

    # Add columns based on display mode
    table.add_column('Id', justify='right', style='yellow', no_wrap=True, width=5)

    if only_document:
        table.add_column('Documentos', style='yellow', overflow='fold', max_width=50)
    else:
        if not only_location:
            # Name columns
            table.add_column('Nome', style='yellow', width=21)
            table.add_column('Nome do Meio', style='yellow', width=22)
            table.add_column('Sobrenome', style='yellow', width=23)

        if not return_only_name:
            # Location and documents columns
            table.add_column('Local', style='yellow', width=30)
            table.add_column('Logradouro', style='yellow', width=50)
            table.add_column('Documentos', style='yellow', overflow='fold', width=28)

    # Process and add rows
    for idx, result in enumerate(results, 1):
        if isinstance(result, tuple):
            if len(result) == 4:  # New format with address data
                location, name_components, documents, address_data = result
            else:  # Old format without address data
                location, name_components, documents = result
                address_data = {}

            # Format documents string
            doc_lines = _format_document_lines(documents)
            doc_str = '\n'.join(doc_lines)

            if only_document:
                table.add_row(str(idx), doc_str)
            else:
                row = [str(idx)]

                # Add name components if not location-only
                if not only_location and name_components:
                    row.extend([name_components.first_name, name_components.middle_name or '', name_components.surname])

                # Add location and documents if not name-only
                if not return_only_name:
                    # Combine address data into a single logradouro field
                    street = address_data.get('street', '')
                    neighborhood = address_data.get('neighborhood', '')
                    building_number = address_data.get('building_number', '')

                    # Format the logradouro: street, building_number - neighborhood
                    logradouro = ''
                    if street:
                        logradouro = street
                        if building_number:
                            logradouro += f', {building_number}'
                        if neighborhood:
                            logradouro += f' - {neighborhood}'
                    elif neighborhood:
                        logradouro = neighborhood
                        if building_number:
                            logradouro += f', {building_number}'

                    # Add phone number to logradouro if available
                    phone = address_data.get('phone', '')
                    if phone:
                        if logradouro:
                            logradouro += f'\nTelefone: {phone}'
                        else:
                            logradouro = f'Telefone: {phone}'

                    row.extend([location or '', logradouro, doc_str])

                table.add_row(*row)
        else:
            # Handle plain string results
            table.add_row(str(idx), result)

    return table


@app.command(name='sample')
def sample(
    qty: int = DEFAULT_QTY,
    city_only: bool = CITY_ONLY,
    state_abbr_only: bool = STATE_ABBR_ONLY,
    state_full_only: bool = STATE_FULL_ONLY,
    only_cep: bool = ONLY_CEP,
    cep_without_dash: bool = CEP_WITHOUT_DASH,
    make_api_call: bool = MAKE_API_CALL,
    time_period: TimePeriod | None = TIME_PERIOD,
    return_only_name: bool = RETURN_ONLY_NAME,
    name_raw: bool = NAME_RAW,
    json_path: Path = JSON_PATH,
    names_path: Path = NAMES_PATH,
    middle_names_path: Path = MIDDLE_NAMES_PATH,
    only_surname: bool = ONLY_SURNAME,
    top_40: bool = TOP_40,
    with_only_one_surname: bool = WITH_ONLY_ONE_SURNAME,
    always_middle: bool = ALWAYS_MIDDLE,
    only_middle: bool = ONLY_MIDDLE,
    always_cpf: bool = ALWAYS_CPF,
    always_pis: bool = ALWAYS_PIS,
    always_cnpj: bool = ALWAYS_CNPJ,
    always_cei: bool = ALWAYS_CEI,
    always_rg: bool = ALWAYS_RG,
    always_phone: bool = ALWAYS_PHONE,
    only_cpf: bool = ONLY_CPF,
    only_pis: bool = ONLY_PIS,
    only_cnpj: bool = ONLY_CNPJ,
    only_cei: bool = ONLY_CEI,
    only_rg: bool = ONLY_RG,
    only_fone: bool = ONLY_FONE,
    include_issuer: bool = INCLUDE_ISSUER,
    only_document: bool = ONLY_DOCUMENT,
    surnames_path: Path = SURNAMES_PATH,
    locations_path: Path = LOCATIONS_PATH,
    save_to_jsonl: str = SAVE_TO_JSONL,
    all_data: bool = ALL_DATA,
    batch: int = BATCH,
    easy: int = EASY,
    append_to_jsonl: bool = APPEND_TO_JSONL,
    random: bool = RANDOM_MODE,
    experimental_uf_sex: bool = EXPERIMENTAL_UF_SEX,
    sex_conditioning: str | None = SEX_CONDITIONING,
    census_year: int = CENSUS_YEAR,
    conditioning_mode: str = CONDITIONING_MODE,
    uf_conditioning: bool = UF_CONDITIONING,
    output_format: str = OUTPUT_FORMAT,
    quiet: bool = QUIET,
) -> None:
    """Generate random Brazilian samples with comprehensive information."""
    fmt = output_format.strip().lower()
    if fmt not in {'table', 'json', 'jsonl'}:
        typer.echo(
            f"Error: output_format must be 'table', 'json', or 'jsonl'; got {output_format!r}",
            err=True,
        )
        raise typer.Exit(code=1)

    suppress_ui = quiet or fmt in {'json', 'jsonl'}

    with logger.contextualize(quiet=suppress_ui):
        try:
            # Process easy mode if specified
            if easy is not None:
                if not suppress_ui:
                    console.print('[bold green]Easy mode enabled[/bold green]')
                logger.info(f'Easy mode enabled with quantity: {easy}')
                qty = easy
                make_api_call = True
                all_data = True
                always_phone = True
                save_to_jsonl = 'output/output.jsonl'

                # Ensure output directory exists
                output_dir = Path(save_to_jsonl).parent
                if output_dir != Path() and not output_dir.exists():
                    if not suppress_ui:
                        console.print(f'[yellow]Creating output directory: {output_dir}[/yellow]')
                    logger.info(f'Creating output directory: {output_dir}')
                    output_dir.mkdir(parents=True, exist_ok=True)

            # Set up batch processing if enabled
            use_batches = False
            batch_size = 0

            if batch is not None and batch > 0 and save_to_jsonl:
                batch_size = min(batch, qty)  # Ensure batch size doesn't exceed total quantity
                use_batches = batch_size < qty  # Only use batches if we have multiple batches

                if use_batches:
                    if not suppress_ui:
                        console.print(f'[bold blue]Processing {qty} samples in batches of {batch_size}[/bold blue]')
                    logger.info(f'Batch mode enabled: {qty} samples in batches of {batch_size}')
                else:
                    if not suppress_ui:
                        console.print(f'[bold blue]Batch size ({batch_size}) equals or exceeds total quantity ({qty})[/bold blue]')
                    logger.info(f'Single batch mode: batch size {batch_size} >= quantity {qty}')

            # Show configuration summary for batch or easy modes
            if batch is not None or easy is not None:
                config_summary = [
                    f'Quantity: {qty}',
                    f'Make API call: [{"green" if make_api_call else "red"}]{make_api_call}[/]',
                    f'All data: [{"green" if all_data else "red"}]{all_data}[/]',
                    f'Always phone: [{"green" if always_phone else "red"}]{always_phone}[/]',
                ]
                if save_to_jsonl:
                    save_mode = '[green]append[/]' if append_to_jsonl else '[yellow]overwrite[/]'
                    config_summary.append(f'Save to: [cyan]{save_to_jsonl}[/] ({save_mode})')
                    if use_batches:
                        config_summary.append(f'Batch size: [cyan]{batch_size}[/] samples')

                logger.info(
                    f'Configuration: qty={qty}, api={make_api_call}, all_data={all_data}, file={save_to_jsonl}, append={append_to_jsonl}'
                )
                if not suppress_ui:
                    console.print('[bold]Configuration:[/bold]')
                    for item in config_summary:
                        console.print(f'  [cyan]•[/cyan] {item}')
                    console.print()

            # Process in batches or as a single run
            all_results: Any = []

            if use_batches:
                logger.info(f'Starting batch processing of {qty} samples')
                with Progress(
                    SpinnerColumn(),
                    TextColumn('[bold blue]{task.description}'),
                    BarColumn(complete_style='green', finished_style='green'),
                    TaskProgressColumn(),
                    TextColumn('{task.fields[status]}'),
                    console=console,
                    disable=suppress_ui,
                ) as progress:
                    main_task = progress.add_task('[green]Generating samples...', total=qty, status='')
                    api_task = None
                    if make_api_call:
                        api_task = progress.add_task('[yellow]API calls...', visible=False, total=1.0, status='')
                    batch_task = progress.add_task('[cyan]Batch progress...', total=batch_size, visible=False, status='')

                    samples_completed = 0
                    first_batch = True
                    while samples_completed < qty:
                        current_batch_size = min(batch_size, qty - samples_completed)
                        batch_num = samples_completed // batch_size + 1
                        total_batches = (qty + batch_size - 1) // batch_size

                        logger.info(f'Processing batch {batch_num}/{total_batches} with {current_batch_size} samples')

                        progress.update(
                            batch_task,
                            description=f'[cyan]Batch {batch_num}/{total_batches}...',
                            total=current_batch_size,
                            completed=0,
                            visible=True,
                        )

                        def progress_callback(
                            completed: int,
                            stage: str | None = None,
                            *,
                            _samples_completed: int = samples_completed,
                            _current_batch_size: int = current_batch_size,
                            _batch_num: int = batch_num,
                        ) -> None:
                            total_completed = min(_samples_completed + completed, qty)

                            if stage and completed % max(1, _current_batch_size // 5) == 0:
                                logger.debug(f'Batch {_batch_num}: {completed}/{_current_batch_size} samples - {stage}')

                            progress.update(
                                main_task,
                                completed=total_completed,
                                status=f'[dim cyan]{stage or ""} (Batch {_batch_num})[/]',
                            )
                            progress.update(batch_task, completed=min(completed, _current_batch_size))

                            if api_task and stage and 'API' in stage:
                                progress.update(api_task, visible=True)
                                if 'starting' in stage.lower():
                                    logger.info(f'API calls starting for batch {_batch_num}')
                                    progress.update(api_task, completed=0.2, status='[yellow]Connecting...[/]')
                                elif 'processing' in stage.lower():
                                    logger.info(f'Processing API responses for batch {_batch_num}')
                                    progress.update(api_task, completed=0.6, status='[yellow]Processing...[/]')
                                elif 'completed' in stage.lower():
                                    logger.info(f'API calls completed for batch {_batch_num}')
                                    progress.update(api_task, completed=1.0, status='[green]Done[/]')

                        try:
                            batch_results = sampler_sample(
                                qty=current_batch_size,
                                q=None,
                                city_only=city_only,
                                state_abbr_only=state_abbr_only,
                                state_full_only=state_full_only,
                                only_cep=only_cep,
                                cep_without_dash=cep_without_dash,
                                make_api_call=make_api_call,
                                time_period=time_period,
                                return_only_name=return_only_name,
                                name_raw=name_raw,
                                json_path=json_path,
                                names_path=names_path,
                                middle_names_path=middle_names_path,
                                only_surname=only_surname,
                                top_40=top_40,
                                with_only_one_surname=with_only_one_surname,
                                always_middle=always_middle,
                                only_middle=only_middle,
                                always_cpf=always_cpf,
                                always_pis=always_pis,
                                always_cnpj=always_cnpj,
                                always_cei=always_cei,
                                always_rg=always_rg,
                                always_phone=always_phone,
                                only_cpf=only_cpf,
                                only_pis=only_pis,
                                only_cnpj=only_cnpj,
                                only_cei=only_cei,
                                only_rg=only_rg,
                                only_fone=only_fone,
                                include_issuer=include_issuer,
                                only_document=only_document,
                                surnames_path=surnames_path,
                                locations_path=locations_path,
                                save_to_jsonl=save_to_jsonl,
                                all_data=all_data,
                                progress_callback=progress_callback,
                                append_to_jsonl=(append_to_jsonl or not first_batch),
                                random=random,
                                experimental_uf_sex_conditioning=experimental_uf_sex,
                                sex_conditioning=sex_conditioning,
                                census_year=census_year,
                                conditioning_mode=conditioning_mode,
                                uf_conditioning=uf_conditioning,
                            )
                            logger.info(f'Batch {batch_num} processed successfully')
                        except Exception as e:
                            logger.error(f'Error processing batch {batch_num}: {e}')
                            raise

                        first_batch = False

                        if isinstance(batch_results, list):
                            all_results.extend(batch_results)
                        else:
                            all_results.append(batch_results)

                        samples_completed += current_batch_size
                        progress.update(batch_task, completed=current_batch_size, status=f'[green]Completed - Saved to {save_to_jsonl}[/]')
                        logger.info(f'Batch {batch_num} saved to {save_to_jsonl}')

                    progress.update(main_task, completed=qty, status='[bold green]All batches completed![/]')
                    progress.update(batch_task, visible=False)
                    if api_task:
                        progress.update(api_task, visible=False)

                    total_batches = (qty + batch_size - 1) // batch_size
                    logger.info(f'All {total_batches} batches completed successfully. Total samples: {qty}')
                    if not suppress_ui:
                        console.print(f'\n[bold green]✓[/] {qty} samples generated successfully in {total_batches} batches!')
                        if save_to_jsonl:
                            console.print(f'[bold green]✓[/] All results saved to [cyan]{save_to_jsonl}[/]')

            else:
                logger.info(f'Starting standard (non-batched) processing of {qty} samples')
                with Progress(
                    SpinnerColumn(),
                    TextColumn('[bold blue]{task.description}'),
                    BarColumn(complete_style='green', finished_style='green'),
                    TaskProgressColumn(),
                    TextColumn('{task.fields[status]}'),
                    console=console,
                    disable=suppress_ui,
                ) as progress:
                    main_task = progress.add_task('[green]Generating samples...', total=qty, status='')

                    api_task = None
                    if make_api_call:
                        api_task = progress.add_task('[yellow]API calls...', visible=False, total=1.0, status='')

                    def progress_callback(completed: int, stage: str | None = None) -> None:
                        if stage and completed % max(1, qty // 10) == 0:
                            logger.debug(f'Progress: {completed}/{qty} samples - {stage}')

                        progress.update(main_task, completed=completed, status=f'[dim cyan]{stage or ""}[/]')

                        if api_task and stage and 'API' in stage:
                            progress.update(api_task, visible=True)
                            if 'starting' in stage.lower():
                                logger.info('API calls starting')
                                progress.update(api_task, completed=0.2, status='[yellow]Connecting...[/]')
                            elif 'processing' in stage.lower():
                                logger.info('Processing API responses')
                                progress.update(api_task, completed=0.6, status='[yellow]Processing...[/]')
                            elif 'completed' in stage.lower():
                                logger.info('API calls completed')
                                progress.update(api_task, completed=1.0, status='[green]Done[/]')

                    try:
                        all_results = sampler_sample(
                            qty=qty,
                            q=None,
                            city_only=city_only,
                            state_abbr_only=state_abbr_only,
                            state_full_only=state_full_only,
                            only_cep=only_cep,
                            cep_without_dash=cep_without_dash,
                            make_api_call=make_api_call,
                            time_period=time_period,
                            return_only_name=return_only_name,
                            name_raw=name_raw,
                            json_path=json_path,
                            names_path=names_path,
                            middle_names_path=middle_names_path,
                            only_surname=only_surname,
                            top_40=top_40,
                            with_only_one_surname=with_only_one_surname,
                            always_middle=always_middle,
                            only_middle=only_middle,
                            always_cpf=always_cpf,
                            always_pis=always_pis,
                            always_cnpj=always_cnpj,
                            always_cei=always_cei,
                            always_rg=always_rg,
                            always_phone=always_phone,
                            only_cpf=only_cpf,
                            only_pis=only_pis,
                            only_cnpj=only_cnpj,
                            only_cei=only_cei,
                            only_rg=only_rg,
                            only_fone=only_fone,
                            include_issuer=include_issuer,
                            only_document=only_document,
                            surnames_path=surnames_path,
                            locations_path=locations_path,
                            save_to_jsonl=save_to_jsonl,
                            all_data=all_data,
                            progress_callback=progress_callback,
                            append_to_jsonl=append_to_jsonl,
                            random=random,
                            experimental_uf_sex_conditioning=experimental_uf_sex,
                            sex_conditioning=sex_conditioning,
                            census_year=census_year,
                            conditioning_mode=conditioning_mode,
                            uf_conditioning=uf_conditioning,
                        )
                        logger.info(f'All {qty} samples processed successfully')
                    except Exception as e:
                        logger.error(f'Error processing samples: {e}')
                        raise

                    progress.update(main_task, completed=qty, status='[bold green]Completed![/]')
                    if api_task:
                        progress.update(api_task, visible=False)

                    logger.info(f'Sample generation completed. Total samples: {qty}')
                    if not suppress_ui:
                        console.print('\n[bold green]✓[/] Sample generation completed successfully!')
                        if save_to_jsonl:
                            console.print(f'[bold green]✓[/] Results saved to [cyan]{save_to_jsonl}[/]')
                            logger.info(f'Results saved to {save_to_jsonl}')

            records = all_results if isinstance(all_results, list) else [all_results]
            if fmt == 'json':
                typer.echo(json.dumps(all_results, ensure_ascii=False))
            elif fmt == 'jsonl':
                for record in records:
                    typer.echo(json.dumps(record, ensure_ascii=False))
        except Exception as e:
            logger.error(f'Error in sample generation: {e}')
            typer.echo(f'Error: {e!s}', err=True)
            raise typer.Exit(code=1) from e


# Expose the same command under the friendlier ``generate`` name so that
# ``ptbr generate`` and ``ptbr sample`` both work.
app.command(name='generate', help='Alias for ``sample``: generate Brazilian profiles.')(sample)


@app.command(name='sources', help='Show the origin of each bundled or runtime dataset.')
def sources(
    kind: str | None = typer.Option(None, '--kind', '-k', help='Filter by data kind (substring match).'),
    census_year: int | None = typer.Option(None, '--census-year', help='Filter by Census vintage (2022 or 2010).'),
) -> None:
    """Print the data-origin catalogue defined in ``ptbr_sampler/data_origins.py``.

    Mirrors ``docs/data-origins.md``. Use ``--kind`` or ``--census-year`` to filter.
    """
    console.print('[bold]ptbr-sampler — data origins[/bold]\n', soft_wrap=True)
    for origin in DATA_ORIGINS:
        if kind and kind.casefold() not in origin.kind.casefold():
            continue
        if census_year is not None and census_year not in origin.census_years:
            continue
        console.print(f'[bold cyan]{origin.kind}[/bold cyan]', soft_wrap=True)
        console.print(f'  {origin.summary}', soft_wrap=True)
        if origin.census_years:
            years_str = ', '.join(str(y) for y in origin.census_years)
            console.print(f'  [dim]Census vintages:[/dim] {years_str}', soft_wrap=True)
        if origin.dimensions:
            console.print(f'  [dim]Dimensions:[/dim] {", ".join(origin.dimensions)}', soft_wrap=True)
        if origin.remote_artifacts:
            states = origin.artifact_states()
            state_counts = Counter(state for _, state in states)
            summary_parts = [f'{state}={count}' for state, count in sorted(state_counts.items())]
            console.print(
                f'  [dim]Runtime artifacts ({len(states)}):[/dim] {", ".join(summary_parts)}',
                soft_wrap=True,
            )
            for rel_path, state in states[:5]:
                console.print(f'    [{state}] {rel_path}', soft_wrap=True)
            if len(states) > 5:
                console.print(f'    ... ({len(states) - 5} more)', soft_wrap=True)
        if origin.files:
            console.print('  [dim]Files:[/dim]', soft_wrap=True)
            for path, exists in origin.file_status():
                mark = '[green]✓[/green]' if exists else '[yellow]missing[/yellow]'
                console.print(f'    {mark} {path}', soft_wrap=True)
        if origin.primary_url:
            console.print(f'  [dim]Primary source:[/dim] {origin.primary_url}', soft_wrap=True)
        if origin.notes:
            console.print(f'  [dim]Notes:[/dim] {origin.notes}', soft_wrap=True)
        console.print()

    console.print(
        '[dim]Full write-up: docs/data-origins.md  ·  external bibliography: docs/sources/bibliography.md[/dim]',
        soft_wrap=True,
    )


@datasets_app.command(name='status', help='Inspect runtime dataset cache and resolution state.')
def datasets_status(
    census_year: int | None = typer.Option(None, '--census-year', help='Filter by Census vintage (2022 or 2010).'),
    verify: bool = typer.Option(False, '--verify', help='Recompute SHA-256 checksums for local/cached artifacts.'),
) -> None:
    """Report resolution state and optional SHA-256 validity of runtime datasets."""
    try:
        status = dataset_cache_status(census_year=census_year, verify_sha256=verify)
    except Exception as e:
        typer.echo(f'Error: {e!s}', err=True)
        raise typer.Exit(code=1) from e

    artifacts: list[dict[str, Any]] = status['artifacts']
    state_counts = Counter(str(row['state']) for row in artifacts)
    invalid = [row for row in artifacts if row['valid'] is False]

    typer.echo(f'HF repo: {status["hf_repo_id"]}')
    typer.echo(f'HF revision: {status["hf_revision"]}')
    typer.echo(f'Cache dir: {status["cache_dir"]}')
    typer.echo(f'Artifacts: {len(artifacts)}')
    for state, count in sorted(state_counts.items()):
        typer.echo(f'  {state}: {count}')

    if invalid:
        for row in invalid:
            typer.echo(f'INVALID: {row["relative_path"]} ({row["resolved_path"]})', err=True)
        raise typer.Exit(code=1)


@datasets_app.command(name='prefetch', help='Download and verify runtime datasets into the local cache.')
def datasets_prefetch(
    census_year: int = typer.Option(2022, '--census-year', help='Census vintage to prefetch (default: 2022).'),
    all_vintages: bool = typer.Option(False, '--all-vintages', help='Prefetch both 2022 and 2010 vintages.'),
) -> None:
    """Eagerly resolve and verify runtime dataset files."""
    try:
        target_year = None if all_vintages else census_year
        resolved = prefetch_datasets(census_year=target_year, verify_sha256=True)
    except Exception as e:
        typer.echo(f'Error: {e!s}', err=True)
        raise typer.Exit(code=1) from e

    typer.echo(f'Prefetched {len(resolved)} verified dataset artifact(s).')


@datasets_app.command(name='clear-cache', help='Delete cached runtime dataset files downloaded from Hugging Face.')
def datasets_clear_cache(
    all_revisions: bool = typer.Option(
        False,
        '--all-revisions',
        help='Clear all cached dataset revisions instead of only the pinned revision.',
    ),
) -> None:
    """Remove cached runtime dataset artifacts from the user cache directory."""
    try:
        removed = clear_dataset_cache(all_revisions=all_revisions)
    except Exception as e:
        typer.echo(f'Error: {e!s}', err=True)
        raise typer.Exit(code=1) from e

    typer.echo(f'Removed {removed} cached file(s).')


def main() -> None:
    """Entry point for the CLI application.

    This function serves as the main entry point for the command-line interface.
    It initializes and runs the Typer application with all configured commands
    and options.
    """
    app()


if __name__ == '__main__':
    main()

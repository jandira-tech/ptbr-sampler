"""The reusable ``ptbr-data`` acquisition and runtime dataset build CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

from ptbr_sampler.data_pipeline.archive import extract_verified_sqlite
from ptbr_sampler.data_pipeline.arpen import fetch_arpen2025
from ptbr_sampler.data_pipeline.build import build_all
from ptbr_sampler.data_pipeline.http import HttpClient, HttpError
from ptbr_sampler.data_pipeline.ibge import OfficialIBGEClient
from ptbr_sampler.data_pipeline.io import file_metadata, write_json
from ptbr_sampler.data_pipeline.registry import SOURCE_REGISTRY, SOURCES, default_cache_dir
from ptbr_sampler.data_pipeline.validate import validate_runtime_data

app = typer.Typer(help='Fetch, verify, and build the PT-BR sampler datasets.', no_args_is_help=True)
console = Console()
DEFAULT_DATA = Path(__file__).resolve().parents[1] / 'data'

CacheOption = Path
DataOption = Path


@app.command()
def status(cache_dir: CacheOption = typer.Option(default_factory=default_cache_dir), data_dir: DataOption = DEFAULT_DATA) -> None:  # noqa: B008
    table = Table(title='Dataset source and artifact status')
    for column in ('source', 'kind', 'cached', 'bytes', 'upstream revision'):
        table.add_column(column)
    for source in SOURCE_REGISTRY:
        path = cache_dir / source.filename if source.kind != 'derived' else data_dir / source.filename
        table.add_row(
            source.key,
            source.kind,
            'yes' if path.exists() else 'no',
            str(path.stat().st_size) if path.is_file() else '-',
            source.upstream_revision,
        )
    console.print(table)


@app.command()
def fetch(
    cache_dir: CacheOption = typer.Option(default_factory=default_cache_dir),  # noqa: B008
    source: Annotated[list[str] | None, typer.Option(help='Source key; defaults to all raw data.')] = None,
    official: Annotated[bool, typer.Option(help='Also attempt lazy official IBGE v3 probes; failures are explicit.')] = False,
    refresh: Annotated[bool, typer.Option('--refresh', help='Redownload instead of resuming verified cache entries.')] = False,
) -> None:
    client = HttpClient()
    selected = source or ['ibge2022', 'pop2026', 'estimativa_dou_2026', 'arpen2025']
    for key in tqdm(selected, desc='sources'):
        if key not in SOURCES or SOURCES[key].kind == 'derived':
            raise typer.BadParameter(f'unknown downloadable source: {key}')
        item = SOURCES[key]
        try:
            if key == 'arpen2025':
                output = cache_dir / item.filename
                result = fetch_arpen2025(client, cache_dir, refresh=refresh)
                metadata = file_metadata(output, url=item.url, revision=item.upstream_revision, rows=result['responses'])
                write_json(output.with_suffix(output.suffix + '.meta.json'), metadata)
                console.print(f'{key}: {result["responses"]} responses sha256={metadata["sha256"]}')
                continue
            metadata = client.download(item, cache_dir / item.filename, timeout=90, refresh=refresh)
            console.print(f'{key}: {metadata["bytes"]:,} bytes sha256={metadata["sha256"]}')
            if key == 'ibge2022':
                output = cache_dir / SOURCES['ibge2022_sqlite'].filename
                extract_verified_sqlite(
                    cache_dir / item.filename,
                    output,
                    sha256=item.sha256,
                    zip_bytes=item.expected_bytes or 0,
                    sqlite_bytes=SOURCES['ibge2022_sqlite'].expected_bytes or 0,
                    sqlite_sha256=SOURCES['ibge2022_sqlite'].sha256,
                )
                write_meta = output.with_suffix(output.suffix + '.meta.json')
                write_json(write_meta, file_metadata(output, url=item.url, revision=item.upstream_revision))
        except (HttpError, ValueError, OSError) as error:
            console.print(f'[red]{key}: acquisition failed: {error}[/red]')
            raise typer.Exit(1) from error
    if official:
        official_client = OfficialIBGEClient(cache_dir=cache_dir / 'official_v3')
        try:
            rows = official_client.ranking(33, 'nome')
            console.print(f'official_v3: RJ first-name probe returned {len(rows)} rows')
        except (HttpError, ValueError) as error:
            console.print(f'[red]official_v3 unreachable or invalid: {error}[/red]')
            raise typer.Exit(2) from error


@app.command()
def build(
    data_dir: DataOption = DEFAULT_DATA,
    cache_dir: CacheOption = typer.Option(default_factory=default_cache_dir),  # noqa: B008
    refresh_arpen: bool = False,
) -> None:
    try:
        manifest = build_all(data_dir, cache_dir, refresh_arpen=refresh_arpen)
    except (HttpError, ValueError, OSError) as error:
        console.print(f'[red]build failed: {error}[/red]')
        raise typer.Exit(1) from error
    console.print(json.dumps(manifest['coverage'], ensure_ascii=False, indent=2))


@app.command()
def validate(data_dir: DataOption = DEFAULT_DATA) -> None:
    manifest_path = data_dir / 'manifest.json'
    if not manifest_path.is_file():
        console.print('[red]manifest.json missing; run fetch and build first[/red]')
        raise typer.Exit(1)
    try:
        result = validate_runtime_data(data_dir)
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as error:
        console.print(f'[red]validation failed: {error}[/red]')
        raise typer.Exit(1) from error
    console.print(
        f'[green]Validated {result["artifacts_verified"]} artifacts, Parquet totals/weights, geography, and Arpen births.[/green]'
    )


def main() -> None:
    app()


if __name__ == '__main__':
    main()

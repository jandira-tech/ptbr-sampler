"""Deterministic, staged build of committed runtime datasets."""

from __future__ import annotations

import gzip
import json
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ptbr_sampler.data_pipeline.arpen import arpen_url, fetch_arpen2025
from ptbr_sampler.data_pipeline.geography import rebuild_geography_files
from ptbr_sampler.data_pipeline.http import HttpClient
from ptbr_sampler.data_pipeline.ibge import derive_historical_bins, read_ibge_mirror, validate_mirror
from ptbr_sampler.data_pipeline.io import atomic_write, sha256_file, utc_now, write_json
from ptbr_sampler.data_pipeline.registry import SOURCES, UF_CODES

NAME_SCHEMA = pa.schema([('name', pa.large_string()), ('count', pa.uint64()), ('weight', pa.float64())])


def normalise_counts(rows: Iterable[tuple[str, int]]) -> list[dict[str, Any]]:
    clean = [(str(name), int(count)) for name, count in rows if int(count) >= 0]
    total = sum(count for _, count in clean)
    if not clean or total <= 0:
        raise ValueError('a derived distribution needs finite positive total counts')
    return [{'name': name, 'count': count, 'weight': count / total} for name, count in clean]


def write_name_partition(
    directory: Path,
    rows: Iterable[tuple[str, int]],
    *,
    source: str,
    transformation: str,
    coverage: str,
    limitations: list[str],
    source_url: str | None = None,
) -> int:
    values = normalise_counts(rows)
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(values, schema=NAME_SCHEMA), directory / 'part.parquet', compression='zstd')
    write_json(
        directory / 'data_origin.json',
        {
            'source': source,
            'source_url': source_url or SOURCES[source].url,
            'upstream_revision': SOURCES[source].upstream_revision,
            'acquired_at_utc': utc_now(),
            'rows': len(values),
            'observed_count_sum': sum(row['count'] for row in values),
            'coverage': coverage,
            'transformation': transformation,
            'provenance': 'ptbr_sampler.data_pipeline deterministic build; normalized count weights',
            'suppression': 'No small-cell suppression added by this project; upstream availability is retained.',
            'limitations': limitations,
        },
    )
    return len(values)


def _publish(staged: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + '.previous')
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        staged.replace(destination)
    except Exception:
        if backup.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build_ibge(sqlite_path: Path, output: Path, sanitized_root: Path) -> dict[str, Any]:
    # The caller checks both archive and SQLite hashes before this function opens it.
    connection = read_ibge_mirror(sqlite_path)
    try:
        coverage = validate_mirror(connection)
        with tempfile.TemporaryDirectory(prefix='.ibge2022-', dir=output.parent) as temporary:
            staged = Path(temporary) / 'ibge2022'
            for kind, directory_name in [('nome', 'first_names'), ('sobrenome', 'surnames')]:
                base = staged / directory_name
                rows = connection.execute(
                    'select nome,frequencia from frequencias where id_local=0 and ano=2022 and tipo_nome=? order by frequencia desc,nome',
                    (kind,),
                ).fetchall()
                write_name_partition(
                    base / 'scope=national',
                    rows,
                    source='ibge2022',
                    transformation='Direct 2022 observed national frequency; weight=count/sum(count)',
                    coverage='Brazil, all nationally reported names',
                    limitations=['IBGE source terms apply; mirror repository MIT license covers code, not the dataset.'],
                )
                for uf, code in UF_CODES.items():
                    rows = connection.execute(
                        'select nome,frequencia from frequencias where id_local=? and ano=2022 '
                        'and tipo_nome=? order by frequencia desc,nome',
                        (int(code), kind),
                    ).fetchall()
                    if not rows:
                        raise ValueError(f'IBGE 2022 missing {uf}/{kind}')
                    write_name_partition(
                        base / f'uf={uf}',
                        rows,
                        source='ibge2022',
                        transformation='Direct 2022 observed UF frequency; weight=count/sum(count)',
                        coverage=f'{uf}, all reported {kind} frequencies',
                        limitations=['No UF-period or UF-sex observations are inferred.'],
                    )
            stock_rows = connection.execute(
                "select nome,ano,frequencia from frequencias where id_local=0 and tipo_nome='nome' and ano<2022 order by nome,ano"
            ).fetchall()
            stocks: dict[str, dict[int, int]] = {}
            for name, year, count in stock_rows:
                stocks.setdefault(name, {})[year] = count
            bins = derive_historical_bins(stocks)
            for period in [*range(1930, 2021, 10), 'after2010', 'until2020']:
                rows = [(name, values[period]) for name, values in bins.items()]
                write_name_partition(
                    staged / 'historical' / f'period={period}',
                    rows,
                    source='ibge2022',
                    transformation='stock1930; stockY-stock(Y-10) for decade bins; after2010=stock2020-stock2010; until2020=stock2020',
                    coverage='National only; all names present in the historical stock table',
                    limitations=[
                        'Historical stocks are not disjoint census2022 rows.',
                        'after2010 covers 2011-2020, not 2021-2022.',
                        'Not observed UF-period-sex data.',
                    ],
                )
            sanitized_root.mkdir(parents=True, exist_ok=True)
            packed = json.dumps(stocks, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()
            atomic_write(sanitized_root / 'historical_stocks.json.gz', gzip.compress(packed, mtime=0))
            sex_rows = connection.execute("select nome,homens,mulheres from generos where id_local=0 and tipo_nome='nome'").fetchall()
            empirical = [(name, male or 0, female or 0) for name, male, female in sex_rows if male is not None or female is not None]
            sex_directory = staged / 'sex_prior' / 'scope=national'
            sex_directory.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pylist(
                [
                    {
                        'name': name,
                        'count_male': male,
                        'count_female': female,
                        'count_total': male + female,
                        'p_male': male / (male + female) if male + female else 0.0,
                        'p_female': female / (male + female) if male + female else 0.0,
                    }
                    for name, male, female in empirical
                ],
                schema=pa.schema(
                    [
                        ('name', pa.large_string()),
                        ('count_male', pa.uint64()),
                        ('count_female', pa.uint64()),
                        ('count_total', pa.uint64()),
                        ('p_male', pa.float64()),
                        ('p_female', pa.float64()),
                    ]
                ),
            )
            pq.write_table(table, sex_directory / 'part.parquet', compression='zstd')
            write_json(
                sex_directory / 'data_origin.json',
                {
                    'source': 'ibge2022',
                    'source_url': SOURCES['ibge2022'].url,
                    'upstream_revision': SOURCES['ibge2022'].upstream_revision,
                    'acquired_at_utc': utc_now(),
                    'rows': len(empirical),
                    'coverage': '123,733 national names with empirical sex counts',
                    'transformation': 'Direct national homens/mulheres; null-sex rows omitted only from sex conditionals',
                    'provenance': 'IBGE 2022 pinned mirror',
                    'suppression': '4,725 null-sex names excluded only here',
                    'limitations': [
                        'National empirical sex only; no UF-sex claim.',
                        'Does not remove null-sex names from unconditioned distributions.',
                    ],
                },
            )
            _publish(staged, output / 'ibge2022')
        coverage.update(
            {
                'ibge_ufs': 27,
                'ibge_uf_first_rows': coverage.pop('uf_nome_rows'),
                'ibge_uf_surname_rows': coverage.pop('uf_sobrenome_rows'),
                'ibge_sex_names': coverage.pop('sex_names'),
                'ibge_sex_null': coverage.pop('sex_null'),
            }
        )
        return coverage
    finally:
        connection.close()


def build_arpen(client: HttpClient, cache: Path, output: Path, sanitized_root: Path, *, refresh: bool = False) -> dict[str, Any]:
    data = fetch_arpen2025(client, cache, refresh=refresh)
    with tempfile.TemporaryDirectory(prefix='.arpen2025-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'arpen2025'
        for key, item in data['rankings'].items():
            kind, uf = key.split(':')
            directory = staged / kind / ('scope=national' if uf == 'BR' else f'uf={uf}')
            write_name_partition(
                directory,
                item['rows'],
                source='arpen2025',
                source_url=item['url'],
                transformation='Direct Arpen top-50 rows; weights normalized within this ranking only',
                coverage=f'2025 {kind} names, {uf}, up to 50 rows',
                limitations=[
                    'Top-50 ranking is not a complete name distribution.',
                    'top50_total is not births and must not be used as population.',
                ],
            )
        births = data['births']
        directory = staged / 'births'
        directory.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.Table.from_pylist([{'uf': uf, 'count': count} for uf, count in sorted(births.items())]),
            directory / 'part.parquet',
            compression='zstd',
        )
        write_json(
            directory / 'data_origin.json',
            {
                'source': 'arpen2025',
                'source_url': arpen_url('birth'),
                'upstream_revision': '2025',
                'acquired_at_utc': utc_now(),
                'rows': len(births),
                'coverage': 'National and 27 UF registered births',
                'transformation': 'Direct totals; UF sum reconciled to national',
                'provenance': 'Arpen Transparência record/birth',
                'suppression': 'None added',
                'limitations': ['Civil registrations for 2025, not Census population stock.'],
            },
        )
        _publish(staged, output / 'arpen2025')
    sanitized_root.mkdir(parents=True, exist_ok=True)
    source_raw = cache / 'arpen2025' / 'responses.jsonl.gz'
    atomic_write(sanitized_root / 'arpen2025_responses.jsonl.gz', source_raw.read_bytes())
    return {'arpen_births': births['BR'], 'arpen_ufs': 27, 'arpen_rankings': len(data['rankings'])}


def build_all(data_dir: Path, cache: Path, *, client: HttpClient | None = None, refresh_arpen: bool = False) -> dict[str, Any]:
    parquet = data_dir / 'parquet'
    parquet.mkdir(parents=True, exist_ok=True)
    sqlite_path = cache / 'ibge2022' / 'nomes.sqlite'
    if sha256_file(sqlite_path) != SOURCES['ibge2022_sqlite'].sha256:
        raise ValueError('refusing to open IBGE SQLite: checksum mismatch')
    coverage = build_ibge(sqlite_path, parquet, data_dir / 'sanitized' / 'ibge2022')
    coverage.update(build_arpen(client or HttpClient(), cache, parquet, data_dir / 'sanitized' / 'arpen2025', refresh=refresh_arpen))
    geography_totals = rebuild_geography_files(
        data_dir / 'cities_with_ceps.json',
        cache / 'geography' / 'POP2026_20261029.xlsx',
        data_dir / 'cities_with_ceps.json',
        data_dir / 'locations_data.json',
    )
    coverage.update(
        {
            'cities': geography_totals['cities'],
            'states': geography_totals['states'],
            'national_population': geography_totals['national_population'],
            'geography_population_sum': geography_totals['municipal_population_sum'],
        }
    )
    geography_sidecar = {
        'source': 'geography_runtime',
        'source_url': SOURCES['pop2026'].url,
        'upstream_revision': SOURCES['pop2026'].upstream_revision,
        'acquired_at_utc': utc_now(),
        'rows': geography_totals['cities'],
        'coverage': '5,570 municipalities and 27 UFs',
        'transformation': 'Exact seven-digit IBGE-code join over CEP base; percentages raw_count*100/reconciled_total',
        'provenance': 'POP2026 TCU-corrected XLSX; estimativa_dou_2026.xlsx retained for comparison',
        'suppression': 'No municipality suppression',
        'limitations': [
            (
                'POP2026 source-only codes '
                f'{geography_totals["unmatched_source_codes"]} are retained in table totals '
                'but excluded from the legacy CEP runtime base.'
            ),
            'No fuzzy municipality-name joins.',
        ],
    }
    write_json(data_dir / 'cities_with_ceps.data_origin.json', geography_sidecar)
    write_json(
        data_dir / 'locations_data.data_origin.json', geography_sidecar | {'rows': geography_totals['cities'] + geography_totals['states']}
    )
    new_artifacts = [
        path
        for path in data_dir.rglob('*')
        if path.is_file()
        and (
            any(part in {'ibge2022', 'arpen2025'} for part in path.parts)
            or path.parent.name == 'sanitized'
            or 'sanitized' in path.parts
            or path.name.endswith('.data_origin.json')
        )
    ]
    artifacts = sorted(f'ptbr_sampler/data/{path.relative_to(data_dir)}' for path in new_artifacts)
    source_metadata = {
        key: {
            'url': source.url,
            'kind': source.kind,
            'upstream_revision': source.upstream_revision,
            'sha256': source.sha256,
            'bytes': source.expected_bytes,
        }
        for key, source in SOURCES.items()
    }
    arpen_raw = cache / 'arpen2025' / 'responses.jsonl.gz'
    source_metadata['arpen2025'].update({'sha256': sha256_file(arpen_raw), 'bytes': arpen_raw.stat().st_size, 'rows': 85})
    manifest = {
        'schema_version': 1,
        'built_at_utc': utc_now(),
        'sources': source_metadata,
        'coverage': coverage,
        'artifacts': artifacts,
        'artifact_sha256': {artifact: sha256_file(data_dir / artifact.removeprefix('ptbr_sampler/data/')) for artifact in artifacts},
        'geography_table_totals': geography_totals,
        'limitations': [
            'Official IBGE v3 live rebuild is separate and may be unavailable; mirror anchors were checked against known official figures.',
            'Arpen rankings are top-50 samples, not complete distributions.',
            'Old Brasil.IO/Gemini artifacts remain historical provenance only for this build.',
        ],
    }
    write_json(data_dir / 'manifest.json', manifest)
    return manifest

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
from ptbr_sampler.data_pipeline.derived import (
    _write_distribution,
    apply_national_sex_prior,
    build_cohorts,
    combine_empirical_sex_rows,
    combine_sex_priors,
)
from ptbr_sampler.data_pipeline.geography import read_pop2026, read_population_workbook, rebuild_geography_files
from ptbr_sampler.data_pipeline.http import HttpClient
from ptbr_sampler.data_pipeline.ibge import (
    HISTORICAL_BIN_PERIODS,
    OFFICIAL_UF_ANCHOR_EVIDENCE,
    OFFICIAL_UF_ANCHORS,
    derive_historical_bins,
    read_ibge_mirror,
    validate_mirror,
)
from ptbr_sampler.data_pipeline.io import atomic_write, sha256_file, utc_now, write_json
from ptbr_sampler.data_pipeline.registry import SOURCES, UF_CODES
from ptbr_sampler.data_pipeline.validate import validate_runtime_data

NAME_SCHEMA = pa.schema([('name', pa.large_string()), ('count', pa.uint64()), ('weight', pa.float64())])


def normalise_counts(rows: Iterable[tuple[str, int]]) -> list[dict[str, Any]]:
    clean = [(str(name).strip(), int(count)) for name, count in rows]
    if any(not name for name, _ in clean):
        raise ValueError('a derived distribution cannot contain an empty name')
    if any(count < 0 for _, count in clean):
        raise ValueError('a derived distribution cannot contain negative counts')
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
    acquired_at_utc: str | None = None,
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
            'acquired_at_utc': acquired_at_utc or utc_now(),
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


def build_ibge(sqlite_path: Path, output: Path, sanitized_root: Path, *, acquired_at_utc: str | None = None) -> dict[str, Any]:
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
                    acquired_at_utc=acquired_at_utc,
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
                        acquired_at_utc=acquired_at_utc,
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
            for period in HISTORICAL_BIN_PERIODS:
                rows = [(name, values[period]) for name, values in bins.items()]
                write_name_partition(
                    staged / 'historical' / f'period={period}',
                    rows,
                    source='ibge2022',
                    acquired_at_utc=acquired_at_utc,
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
            empirical = combine_empirical_sex_rows(empirical)
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
                    'acquired_at_utc': acquired_at_utc or utc_now(),
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
            sex_priors = combine_sex_priors(empirical)
            for period in HISTORICAL_BIN_PERIODS:
                if period == 1930:
                    period_definition = 'stock1930 (births through 1930)'
                elif period == 'after2010':
                    period_definition = 'stock2020-stock2010 (births 2011-2020)'
                elif period == 'until2020':
                    period_definition = 'stock2020 (cumulative births through 2020)'
                else:
                    period_definition = f'stock{period}-stock{period - 10} (births {period - 9}-{period})'
                historical = {name: float(values[period]) for name, values in bins.items()}
                for sex in ('M', 'F'):
                    conditioned = apply_national_sex_prior(historical, sex_priors, sex)
                    _write_distribution(
                        staged / 'historical' / f'period={period}' / f'sex={sex}',
                        conditioned,
                        {
                            'source': 'ibge2022',
                            'source_url': SOURCES['ibge2022'].url,
                            'upstream_revision': SOURCES['ibge2022'].upstream_revision,
                            'acquired_at_utc': acquired_at_utc or utc_now(),
                            'period': period,
                            'period_definition': period_definition,
                            'sex': sex,
                            'derived': True,
                            'source_rows': len(historical),
                            'coverage': f'National {period} historical bin conditioned by national empirical sex prior',
                            'formula': f'p_{sex}[i] ∝ historical_{period}[i] * national_IBGE_p_{sex}[i]; null-sex omitted; renormalized',
                            'transformation': (
                                'IBGE historical normalized bin multiplied by IBGE national empirical sex prior, then renormalized'
                            ),
                            'sex_prior_scope': 'national',
                            'provenance': 'Derived from IBGE historical stock differences and IBGE 2022 national homens/mulheres.',
                            'suppression': (
                                'Only names absent from national empirical sex rows are dropped; '
                                'known zero-probability labels remain support.'
                            ),
                            'limitations': [
                                'National historical bin multiplied by a national empirical sex prior; no UF derivation.',
                                'Not observed historical period-by-sex or UF-sex joint frequencies.',
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
                'ibge_historical_periods': len(HISTORICAL_BIN_PERIODS),
                'ibge_historical_sex_partitions': len(HISTORICAL_BIN_PERIODS) * 2,
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
                acquired_at_utc=item['acquired_at_utc'],
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
                'acquired_at_utc': data['births_acquired_at_utc'],
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


def _build_managed_generation(
    data_dir: Path,
    cache: Path,
    acquisition_times: dict[str, str],
    *,
    client: HttpClient | None = None,
    refresh_arpen: bool = False,
) -> dict[str, Any]:
    parquet = data_dir / 'parquet'
    parquet.mkdir(parents=True, exist_ok=True)
    sqlite_path = cache / 'ibge2022' / 'nomes.sqlite'
    if sha256_file(sqlite_path) != SOURCES['ibge2022_sqlite'].sha256:
        raise ValueError('refusing to open IBGE SQLite: checksum mismatch')
    coverage = build_ibge(sqlite_path, parquet, data_dir / 'sanitized' / 'ibge2022', acquired_at_utc=acquisition_times['ibge2022'])
    coverage.update(build_arpen(client or HttpClient(), cache, parquet, data_dir / 'sanitized' / 'arpen2025', refresh=refresh_arpen))
    acquisition_times['arpen2025'] = _arpen_acquisition_time(cache)
    geography_totals = rebuild_geography_files(
        data_dir / 'cities_with_ceps.json',
        cache / 'geography' / 'POP2026_20261029.xlsx',
        data_dir / 'cities_with_ceps.json',
        data_dir / 'locations_data.json',
        comparison_workbook_path=cache / 'geography' / 'estimativa_dou_2026.xlsx',
    )
    coverage.update(
        {
            'cities': geography_totals['cities'],
            'states': geography_totals['states'],
            'national_population': geography_totals['national_population'],
            'geography_population_sum': geography_totals['municipal_population_sum'],
        }
    )
    coverage.update(
        build_cohorts(
            parquet,
            data_dir / 'locations_data.json',
            acquired_at_utc=max(acquisition_times.values()),
        )
    )
    geography_sidecar = {
        'source': 'geography_runtime',
        'source_url': SOURCES['pop2026'].url,
        'upstream_revision': SOURCES['pop2026'].upstream_revision,
        'acquired_at_utc': acquisition_times['pop2026'],
        'rows': geography_totals['cities'],
        'coverage': '5,570 municipalities and 27 UFs',
        'transformation': 'Exact seven-digit IBGE-code join over CEP base; percentages raw_count*100/reconciled_total',
        'provenance': 'POP2026 TCU-corrected XLSX; keyed comparison against estimativa_dou_2026.xlsx',
        'dou_comparison': {
            'url': geography_totals['comparison']['source_url'],
            'sha256': geography_totals['comparison']['sha256'],
            'summary': geography_totals['comparison']['summary'],
            'national_population_delta': geography_totals['comparison']['national_population_delta'],
            'artifact': geography_totals['comparison_path'],
        },
        'official_uf_reconciliation': geography_totals['reconciliation'],
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
            any(part in {'ibge2022', 'arpen2025', 'cohorts'} for part in path.parts)
            or path.parent.name == 'sanitized'
            or 'sanitized' in path.parts
            or path.name.endswith('.data_origin.json')
            or path.name in {'cities_with_ceps.json', 'locations_data.json'}
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
            'acquired_at_utc': acquisition_times.get(key),
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
        'geography_comparison': geography_totals['comparison'],
        'geography_reconciliation': geography_totals['reconciliation'],
        'official_uf_anchors': [
            {
                'uf': uf,
                'kind': kind,
                'name': name,
                'count': count,
                'evidence_url': OFFICIAL_UF_ANCHOR_EVIDENCE[(uf, kind, name)],
                'ibge_url': f'https://censo2022.ibge.gov.br/nomes/nome/{name}?tipo={kind}&localidade={UF_CODES[uf]}',
            }
            for (uf, kind, name), count in sorted(OFFICIAL_UF_ANCHORS.items())
        ],
        'limitations': [
            'Official IBGE v3 live rebuild is separate and may be unavailable; mirror anchors were checked against known official figures.',
            'Arpen rankings are top-50 samples, not complete distributions.',
            'Old Brasil.IO/Gemini artifacts remain historical provenance only for this build.',
        ],
    }
    write_json(data_dir / 'manifest.json', manifest)
    return manifest


def _source_acquisition_time(cache: Path, key: str) -> str:
    path = cache / SOURCES[key].filename
    metadata_path = path.with_suffix(path.suffix + '.meta.json')
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    acquired_at = metadata.get('acquired_at_utc')
    if not isinstance(acquired_at, str) or not acquired_at:
        raise ValueError(f'missing acquisition timestamp for {key}: {metadata_path}')
    return acquired_at


def _arpen_acquisition_time(cache: Path) -> str:
    with gzip.open(cache / 'arpen2025' / 'responses.jsonl.gz', 'rt', encoding='utf-8') as stream:
        return max(json.loads(line)['acquired_at_utc'] for line in stream)


def build_all(data_dir: Path, cache: Path, *, client: HttpClient | None = None, refresh_arpen: bool = False) -> dict[str, Any]:
    # No target path is opened or written until every managed artifact and its
    # manifest have passed deep validation in a sibling staged generation.
    sqlite_path = cache / 'ibge2022' / 'nomes.sqlite'
    if sha256_file(sqlite_path) != SOURCES['ibge2022_sqlite'].sha256:
        raise ValueError('refusing to open IBGE SQLite: checksum mismatch')
    acquisition_times = {
        key: _source_acquisition_time(cache, key) for key in ('ibge2022', 'ibge2022_sqlite', 'pop2026', 'estimativa_dou_2026')
    }
    acquisition_times['arpen2025'] = _arpen_acquisition_time(cache)
    read_pop2026(cache / SOURCES['pop2026'].filename)
    read_population_workbook(cache / SOURCES['estimativa_dou_2026'].filename, source_key='estimativa_dou_2026')
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{data_dir.name}.staging-', dir=data_dir.parent))
    staged = temporary / data_dir.name
    rollback_root = data_dir.parent / f'.{data_dir.name}.rollback-{temporary.name.rsplit("-", 1)[-1]}'
    previous = rollback_root / data_dir.name
    published = False
    try:
        if data_dir.exists():
            shutil.copytree(data_dir, staged)
        else:
            staged.mkdir()
        manifest = _build_managed_generation(staged, cache, acquisition_times, client=client, refresh_arpen=refresh_arpen)
        validate_runtime_data(staged)
        rollback_root.mkdir()
        if data_dir.exists():
            data_dir.replace(previous)
        try:
            staged.replace(data_dir)
            published = True
        except Exception:
            if previous.exists() and not data_dir.exists():
                previous.replace(data_dir)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        rollback_root.rmdir()
        return manifest
    finally:
        if not published and previous.exists() and not data_dir.exists():
            previous.replace(data_dir)
        shutil.rmtree(temporary, ignore_errors=True)
        if rollback_root.exists() and not previous.exists():
            rollback_root.rmdir()

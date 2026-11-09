"""Deep, deterministic validation of hashes, inventory, Parquet, and totals."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow.parquet as pq

from ptbr_sampler.data_pipeline.ibge import NATIONAL_COUNTS, UF_COUNTS
from ptbr_sampler.data_pipeline.io import sha256_file
from ptbr_sampler.data_pipeline.registry import UF_CODES

_PREFIX = 'ptbr_sampler/data/'
_GEOGRAPHY_FILES = {
    'cities_with_ceps.json',
    'locations_data.json',
    'cities_with_ceps.data_origin.json',
    'locations_data.data_origin.json',
}


def _managed_inventory(data_dir: Path) -> set[str]:
    files = {
        path.relative_to(data_dir).as_posix()
        for root in ('parquet/ibge2022', 'parquet/arpen2025', 'sanitized')
        for path in (data_dir / root).rglob('*')
        if path.is_file()
    }
    files |= {name for name in _GEOGRAPHY_FILES if (data_dir / name).is_file()}
    return files


def _check_name_parquet(path: Path) -> tuple[int, int]:
    rows = 0
    counts = 0
    weights = 0.0
    parquet = pq.ParquetFile(path)
    if parquet.schema_arrow.names != ['name', 'count', 'weight']:
        raise ValueError(f'Parquet schema mismatch: {path}')
    try:
        for batch in parquet.iter_batches(batch_size=65_536, columns=['name', 'count', 'weight']):
            for name, count, weight in zip(
                batch.column('name').to_pylist(), batch.column('count').to_pylist(), batch.column('weight').to_pylist(), strict=True
            ):
                if not isinstance(name, str) or not name or not isinstance(count, int) or count < 0:
                    raise ValueError(f'invalid name/count row in {path}')
                if not isinstance(weight, float) or not math.isfinite(weight) or weight < 0:
                    raise ValueError(f'invalid weight in {path}')
                rows += 1
                counts += count
                weights += weight
    except Exception as error:
        raise ValueError(f'unreadable Parquet {path}: {error}') from error
    if rows == 0 or abs(weights - 1.0) > 1e-9:
        raise ValueError(f'unnormalized distribution {path}: rows={rows}, weights={weights}')
    return rows, counts


def _check_geography(data_dir: Path, manifest: dict[str, Any]) -> int:
    cities_payload = json.loads((data_dir / 'cities_with_ceps.json').read_text(encoding='utf-8'))
    locations = json.loads((data_dir / 'locations_data.json').read_text(encoding='utf-8'))
    cities = cities_payload.get('cities', {})
    states = locations.get('states', {})
    if len(cities) != 5_570 or len(locations.get('cities', {})) != 5_570 or len(states) != 27:
        raise ValueError('geography inventory must contain 5,570 cities and 27 UFs')
    reconciliation = manifest.get('geography_reconciliation', {})
    if set(reconciliation) != set(UF_CODES):
        raise ValueError('official UF reconciliation is incomplete')
    if sum(state['state_population'] for state in states.values()) != 214_211_951:
        raise ValueError('geography official UF populations do not reconcile to national population')
    by_uf = dict.fromkeys(UF_CODES, 0)
    for item in cities.values():
        code = item.get('ibge_code', '')
        if len(code) != 7 or not code.isdigit() or item['city_population'] < 0:
            raise ValueError('geography contains an invalid IBGE code or population')
        by_uf[item['city_uf']] += item['city_population']
        if not (0 <= item['population_percentage_total'] <= 100 and 0 <= item['population_percentage_state'] <= 100):
            raise ValueError('geography percentages must be in [0,100]')
    for state in states.values():
        uf = state['state_abbr']
        expected = reconciliation[uf]
        if state['state_population'] != expected['official_population'] or by_uf[uf] != expected['joined_population']:
            raise ValueError(f'geography official UF/joined city mismatch for {uf}')
        if by_uf[uf] - state['state_population'] != -expected['unmatched_source_population']:
            raise ValueError(f'geography documented unmatched-source delta mismatch for {uf}')
    return len(cities)


def validate_runtime_data(data_dir: Path) -> dict[str, int]:
    manifest_path = data_dir / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('manifest.json missing')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    artifacts = manifest.get('artifacts', [])
    hashes = manifest.get('artifact_sha256', {})
    if len(artifacts) != len(set(artifacts)) or set(artifacts) != set(hashes):
        raise ValueError('manifest artifact list and hashes differ')
    expected = set()
    for artifact in artifacts:
        if not artifact.startswith(_PREFIX):
            raise ValueError(f'artifact outside data directory: {artifact}')
        relative = PurePosixPath(artifact.removeprefix(_PREFIX))
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'unsafe artifact path: {artifact}')
        expected.add(relative.as_posix())
        path = data_dir / relative
        if not path.is_file():
            raise ValueError(f'missing artifact: {relative}')
        if sha256_file(path) != hashes[artifact]:
            raise ValueError(f'artifact hash mismatch: {relative}')
    unexpected = _managed_inventory(data_dir) - expected
    if unexpected:
        raise ValueError(f'unexpected artifact(s): {sorted(unexpected)[:5]}')

    uf_partitions = {f'uf={uf}' for uf in UF_CODES}
    totals: dict[str, dict[str, int]] = {}
    for kind, directory in [('nome', 'first_names'), ('sobrenome', 'surnames')]:
        root = data_dir / 'parquet' / 'ibge2022' / directory
        actual = {path.parent.name for path in root.rglob('part.parquet')}
        if actual != uf_partitions | {'scope=national'}:
            raise ValueError(f'{kind} national/UF partition set mismatch')
        uf_rows = 0
        uf_counts = 0
        for partition in sorted(actual):
            rows, counts = _check_name_parquet(root / partition / 'part.parquet')
            if partition == 'scope=national':
                if (rows, counts) != NATIONAL_COUNTS[kind]:
                    raise ValueError(f'national {kind} totals mismatch: {(rows, counts)}')
            else:
                uf_rows += rows
                uf_counts += counts
        if uf_rows != UF_COUNTS[kind][0] or uf_counts <= 0:
            raise ValueError(f'UF {kind} totals mismatch')
        totals[kind] = {'uf_rows': uf_rows, 'uf_counts': uf_counts}

    # Read every other new name ranking as well, including historical and Arpen.
    for root in (data_dir / 'parquet' / 'ibge2022' / 'historical', data_dir / 'parquet' / 'arpen2025'):
        for path in root.rglob('part.parquet'):
            if path.parent.name == 'births':
                continue
            _check_name_parquet(path)
    sex = pq.read_table(data_dir / 'parquet' / 'ibge2022' / 'sex_prior' / 'scope=national' / 'part.parquet')
    if sex.num_rows != 123_733:
        raise ValueError('empirical sex-prior row count mismatch')
    births = pq.read_table(data_dir / 'parquet' / 'arpen2025' / 'births' / 'part.parquet').to_pylist()
    by_uf = {row['uf']: row['count'] for row in births}
    if set(by_uf) != set(UF_CODES) | {'BR'} or sum(by_uf[uf] for uf in UF_CODES) != 2_537_697 or by_uf['BR'] != 2_537_697:
        raise ValueError('Arpen births do not reconcile across 27 UFs and Brazil')
    cities = _check_geography(data_dir, manifest)
    return {
        'artifacts_verified': len(artifacts),
        'first_name_ufs': 27,
        'surname_ufs': 27,
        'arpen_births': by_uf['BR'],
        'cities': cities,
        'national_first_rows': NATIONAL_COUNTS['nome'][0],
        'national_surname_rows': NATIONAL_COUNTS['sobrenome'][0],
    }

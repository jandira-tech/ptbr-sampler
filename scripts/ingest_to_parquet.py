"""Convert the legacy JSON data files under ``ptbr_sampler/data/`` into the
partitioned Parquet layout described in ``docs/architecture.md``.

Running the script writes::

    ptbr_sampler/data/parquet/
    ├── first_names/period=<period>/part.parquet
    ├── surnames/scope=national/part.parquet
    ├── middle_names/part.parquet
    └── states/part.parquet

The layout intentionally carries partition keys even when the current JSON
files only supply a single slice (e.g. national surnames and sex-mixed first
names). This makes it trivial to drop-in IBGE 2022 data conditioned on
``(uf × decade × sex)`` without changing the code reading the partitions.

Usage::

    python -m scripts.ingest_to_parquet --out ptbr_sampler/data/parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from ptbr_sampler.sampling.vocabulary import GivenNameVocabulary


_SCHEMA = pa.schema(
    [
        pa.field('name', pa.dictionary(pa.int32(), pa.large_string())),
        pa.field('count', pa.uint64()),
        pa.field('weight', pa.float32()),
    ]
)


def _write_partition(out_dir: Path, names: list[str], counts: list[int], weights: list[float]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            'name': pa.array(names).dictionary_encode(),
            'count': pa.array(counts, type=pa.uint64()),
            'weight': pa.array(weights, type=pa.float32()),
        },
        schema=_SCHEMA,
    )
    pq.write_table(table, out_dir / 'part.parquet', compression='zstd')


def _normalise(pcts: Iterable[float]) -> list[float]:
    total = sum(p for p in pcts if p > 0)
    if total <= 0:
        return [0.0 for _ in pcts]
    return [float(p) / total for p in pcts]


def ingest_first_names(src: Path, out_root: Path) -> dict[str, int]:
    """Write one partition per period under ``first_names/period=<period>``.

    Returns a dict ``{period: row_count}`` so callers can print a summary.
    """
    with src.open(encoding='utf-8') as f:
        data = json.load(f)
    periods = data.get('common_names_percentage', {})
    stats: dict[str, int] = {}
    for period, payload in periods.items():
        names_map = payload.get('names', {})
        labels = []
        counts = []
        pcts = []
        for name, info in names_map.items():
            pct = float(info.get('percentage', 0.0) or 0.0)
            if pct <= 0.0:
                continue
            labels.append(str(name))
            pcts.append(pct)
            counts.append(int(info.get('count', 0) or 0))
        if not labels:
            continue
        weights = _normalise(pcts)
        partition_dir = out_root / 'first_names' / f'period={period}'
        _write_partition(partition_dir, labels, counts, weights)
        stats[period] = len(labels)
    return stats


def ingest_surnames(src: Path, out_root: Path) -> int:
    with src.open(encoding='utf-8') as f:
        data = json.load(f)
    surnames = data.get('surnames', {})
    labels = []
    counts = []
    pcts = []
    for name, info in surnames.items():
        if name == 'top_40':
            continue
        if not isinstance(info, dict):
            continue
        pct = float(info.get('percentage', 0.0) or 0.0)
        if pct <= 0.0:
            continue
        labels.append(str(name))
        pcts.append(pct)
        counts.append(int(info.get('count', 0) or 0))
    weights = _normalise(pcts)
    partition_dir = out_root / 'surnames' / 'scope=national'
    _write_partition(partition_dir, labels, counts, weights)
    return len(labels)


def ingest_middle_names(
    src: Path, out_root: Path, vocabulary: GivenNameVocabulary | None
) -> tuple[int, int]:
    """Write the cleaned second-names table.

    Returns ``(kept_rows, dropped_rows)``.
    """
    with src.open(encoding='utf-8') as f:
        data = json.load(f)
    raw = data.get('second_names', {})
    kept_names: list[str] = []
    kept_counts: list[int] = []
    kept_pcts: list[float] = []
    dropped = 0
    for name, info in raw.items():
        if not isinstance(info, dict):
            dropped += 1
            continue
        if vocabulary is not None and not vocabulary.is_given_name(name):
            dropped += 1
            continue
        pct = float(info.get('percentage', 0.0) or 0.0)
        if pct <= 0.0:
            dropped += 1
            continue
        kept_names.append(str(name))
        kept_counts.append(int(info.get('count', 0) or 0))
        kept_pcts.append(pct)
    weights = _normalise(kept_pcts)
    partition_dir = out_root / 'middle_names'
    _write_partition(partition_dir, kept_names, kept_counts, weights)
    return len(kept_names), dropped


def ingest_states(src: Path, out_root: Path) -> int:
    with src.open(encoding='utf-8') as f:
        data = json.load(f)
    states = data.get('states', {})
    labels = []
    counts = []
    pcts = []
    for state_name, info in states.items():
        if not isinstance(info, dict):
            continue
        pop = int(info.get('state_population', 0) or 0)
        pct = float(info.get('population_percentage', 0.0) or 0.0)
        if pct <= 0.0 and pop <= 0:
            continue
        labels.append(str(state_name))
        counts.append(pop)
        pcts.append(pct if pct > 0 else float(pop))
    weights = _normalise(pcts)
    partition_dir = out_root / 'states'
    _write_partition(partition_dir, labels, counts, weights)
    return len(labels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='ptbr_sampler/data', type=Path)
    parser.add_argument('--out', default='ptbr_sampler/data/parquet', type=Path)
    parser.add_argument(
        '--skip-middle-names-filter',
        action='store_true',
        help='Ingest middle_names.json without the given-name whitelist filter.',
    )
    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir
    out_root: Path = args.out
    out_root.mkdir(parents=True, exist_ok=True)

    vocab: GivenNameVocabulary | None = None
    if not args.skip_middle_names_filter:
        vocab = GivenNameVocabulary.from_names_data(
            data_dir / 'names_data.json',
            data_dir / 'surnames_data.json',
        )

    print('Ingesting first names (per period)...')
    first_name_stats = ingest_first_names(data_dir / 'names_data.json', out_root)
    for period, count in sorted(first_name_stats.items()):
        print(f'  {period}: {count} rows')

    print('Ingesting national surnames...')
    n_surnames = ingest_surnames(data_dir / 'surnames_data.json', out_root)
    print(f'  rows: {n_surnames}')

    print('Ingesting cleaned middle names...')
    kept, dropped = ingest_middle_names(data_dir / 'middle_names.json', out_root, vocab)
    print(f'  kept: {kept}, dropped: {dropped}')

    print('Ingesting state population weights...')
    n_states = ingest_states(data_dir / 'locations_data.json', out_root)
    print(f'  rows: {n_states}')

    print(f'\nParquet layout written under: {out_root}')
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())

"""Convert the legacy JSON data files under ``ptbr_sampler/data/`` into the
partitioned Parquet layout described in ``docs/architecture.md``.

Running the script writes::

    ptbr_sampler/data/parquet/
    ├── first_names/period=<period>/part.parquet
    ├── first_names/uf=<UF>/period=<period>/sex=<M|F>/part.parquet  (if raw IBGE v2 data is present)
    ├── surnames/scope=national/part.parquet
    ├── middle_names/part.parquet
    └── states/part.parquet

The layout intentionally carries partition keys even when the current JSON
files only supply a single slice (e.g. national surnames and sex-mixed first
names). This makes it trivial to drop-in IBGE 2022 data conditioned on
``(uf x decade x sex)`` without changing the code reading the partitions.

The UF x period x sex first-name partitions are written when raw rankings
fetched by ``scripts.download_datasets --fetch-ibge-nomes`` are present
under ``ptbr_sampler/data/raw/ibge_nomes_v2/``. Their absence is not an
error — the sampler falls back to the period-only partitions when no
UF/sex partition matches the requested condition.

Usage::

    python -m scripts.ingest_to_parquet --out ptbr_sampler/data/parquet
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

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
    values = [float(p) for p in pcts]
    total = sum(p for p in values if p > 0)
    if total <= 0:
        return [0.0 for _ in values]
    return [p / total for p in values]


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


def ingest_middle_names(src: Path, out_root: Path, vocabulary: GivenNameVocabulary | None) -> tuple[int, int]:
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


def ingest_first_names_uf_sex(raw_root: Path, out_root: Path) -> dict[tuple[str, str, str], int]:
    """Read IBGE Nomes v2 raw JSON and write UF x period x sex partitions.

    Expects the on-disk layout produced by
    :func:`scripts.download_datasets.fetch_ibge_first_names_v2`::

        raw_root/uf=<UF>/period=ate<YYYY>/sex=<M|F>.json

    For each file with non-empty ``res``, writes::

        out_root/first_names/uf=<UF>/period=<P>/sex=<S>/part.parquet

    Returns a dict ``{(uf, period, sex): row_count}``. Empty result when
    ``raw_root`` doesn't exist (no fetch yet) — that's deliberate: the
    sampler keeps using the period-only partitions in that case.
    """
    stats: dict[tuple[str, str, str], int] = {}
    if not raw_root.exists():
        return stats
    for uf_dir in sorted(raw_root.glob('uf=*')):
        uf = uf_dir.name.split('=', 1)[1]
        for period_dir in sorted(uf_dir.glob('period=*')):
            period = period_dir.name.split('=', 1)[1]
            for sex_file in sorted(period_dir.glob('sex=*.json')):
                sex = sex_file.stem.split('=', 1)[1]
                with sex_file.open(encoding='utf-8') as f:
                    payload = json.load(f)
                rows = payload.get('res') or []
                labels: list[str] = []
                counts: list[int] = []
                pcts: list[float] = []
                for row in rows:
                    name = row.get('nome')
                    freq = row.get('frequencia')
                    if not name or freq is None:
                        continue
                    try:
                        cnt = int(freq)
                    except (TypeError, ValueError):
                        continue
                    if cnt <= 0:
                        continue
                    labels.append(str(name))
                    counts.append(cnt)
                    pcts.append(float(cnt))
                if not labels:
                    continue
                weights = _normalise(pcts)
                partition_dir = out_root / 'first_names' / f'uf={uf}' / f'period={period}' / f'sex={sex}'
                _write_partition(partition_dir, labels, counts, weights)
                stats[uf, period, sex] = len(labels)
    return stats


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
    default_data_dir = Path(__file__).resolve().parents[1] / 'ptbr_sampler' / 'data'
    parser.add_argument('--data-dir', default=default_data_dir, type=Path)
    parser.add_argument('--out', default=default_data_dir / 'parquet', type=Path)
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

    raw_v2 = data_dir / 'raw' / 'ibge_nomes_v2'
    print(f'Ingesting first names (UF x period x sex) from {raw_v2}...')
    uf_stats = ingest_first_names_uf_sex(raw_v2, out_root)
    if not uf_stats:
        print('  (no raw IBGE Nomes v2 data found — run "python -m scripts.download_datasets --fetch-ibge-nomes" first)')
    else:
        print(f'  partitions written: {len(uf_stats)}')

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

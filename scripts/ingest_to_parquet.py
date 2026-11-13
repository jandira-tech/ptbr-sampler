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
import csv
import datetime
import json
import math
import shutil
import sys
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ptbr_sampler.sampling.vocabulary import GivenNameVocabulary

_REPO_ROOT = Path(__file__).resolve().parents[1]

CENSUS_2022_DECADE_TO_PERIOD: dict[int, str] = {
    1930: 'ate1940',
    1940: 'ate1950',
    1950: 'ate1960',
    1960: 'ate1970',
    1970: 'ate1980',
    1980: 'ate1990',
    1990: 'ate2000',
    2000: 'ate2010',
    2010: 'ate2020',
    2020: '2020_2022',
}

_SCHEMA = pa.schema(
    [
        ('name', pa.string()),
        ('count', pa.int64()),
        ('weight', pa.float64()),
    ]
)

_SEX_PRIOR_SCHEMA = pa.schema(
    [
        pa.field('name', pa.dictionary(pa.int32(), pa.large_string())),
        pa.field('count_male', pa.uint64()),
        pa.field('count_female', pa.uint64()),
        pa.field('count_total', pa.uint64()),
        pa.field('p_male', pa.float64()),
        pa.field('p_female', pa.float64()),
        pa.field('classification', pa.large_string()),
        pa.field('group_name', pa.large_string()),
        # Provenance label so reviewers can audit which rows are empirical
        # ('brasil.io/genero-nomes') vs LLM-tagged ('gemini-...').
        pa.field('source', pa.large_string()),
    ]
)

_SEX_PRIOR_2022_SCHEMA = pa.schema(
    [
        ('name', pa.string()),
        ('canonical_key', pa.string()),
        ('count_total', pa.int64()),
        ('count_male', pa.int64()),  # nullable: None when IBGE suppressed (<20)
        ('count_female', pa.int64()),  # nullable: None when IBGE suppressed (<20)
        ('residual_unassigned', pa.int64()),
        ('p_male', pa.float64()),  # NaN when male cell suppressed with positive residual
        ('p_female', pa.float64()),  # NaN when female cell suppressed with positive residual
        ('censoring_regime', pa.string()),
    ]
)

_GENERO_NOMES_URL = 'https://data.brasil.io/dataset/genero-nomes/nomes.csv.gz'
_IBGE_NOMES_V2_URL = 'https://servicodados.ibge.gov.br/api/v2/censos/nomes/ranking'
_GENERO_NOMES_PROVENANCE = (
    'brasil.io/genero-nomes (Álvaro Justen / @turicas), built from the public IBGE Nomes API. Mirrored at ' + _GENERO_NOMES_URL
)
_GENERO_NOMES_SOURCE_LABEL = 'brasil.io/genero-nomes'


def _write_origin_sidecar(out_dir: Path, *, source: str, url: str, rows: int, extra: dict | None = None) -> None:
    """Write a tiny ``data_origin.json`` next to a parquet partition.

    Reviewers reading the bundled data should be able to trace any partition
    back to the upstream source without grepping the ingester. Keep the
    payload small and machine-readable.
    """
    now_iso = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
    payload: dict[str, object] = {
        'source': source,
        'url': url,
        'rows': rows,
        'built_at_utc': now_iso,
        'fetched_at_utc': now_iso,
        'ingester': 'scripts/ingest_to_parquet.py',
    }
    if extra:
        payload.update(extra)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'data_origin.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def _write_partition(out_dir: Path, names: list[str], counts: list[int], weights: list[float]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            'name': pa.array(names, type=pa.string()),
            'count': pa.array(counts, type=pa.int64()),
            'weight': pa.array(weights, type=pa.float64()),
        },
        schema=_SCHEMA,
    )
    pq.write_table(table, out_dir / 'part.parquet', compression='zstd', compression_level=9)


def _normalise(pcts: Iterable[float]) -> list[float]:
    values = [float(p) for p in pcts]
    total = math.fsum(p for p in values if p > 0 and math.isfinite(p))
    if total <= 0:
        return [0.0 for _ in values]
    return [p / total if (p > 0 and math.isfinite(p)) else 0.0 for p in values]


def _normalise_entries(entries: list[tuple[str, int, float]]) -> tuple[list[str], list[int], list[float]]:
    filtered = [(name, c, w) for name, c, w in entries if w > 0 and math.isfinite(w)]
    if not filtered:
        raise ValueError('partition has no positive-weight entries')
    total = math.fsum(w for _, _, w in filtered)
    names = [name for name, _, _ in filtered]
    counts = [int(c) for _, c, _ in filtered]
    weights = [float(w) / total for _, _, w in filtered]
    return names, counts, weights


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
                    if not isinstance(row, dict):
                        continue
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
                partition = f'first_names/uf={uf}/period={period}/sex={sex}'
                partition_dir = out_root / partition
                _write_partition(partition_dir, labels, counts, weights)
                _write_origin_sidecar(
                    partition_dir,
                    source='IBGE Nomes API v2 ranking endpoint (top 20 names per UF, sex and decade)',
                    url=_IBGE_NOMES_V2_URL,
                    rows=len(labels),
                    extra={'partition': partition},
                )
                stats[uf, period, sex] = len(labels)
    return stats


def _read_genero_nomes(csv_path: Path) -> dict[str, dict[str, float | int | str]]:
    """Parse ``brasil.io/genero-nomes`` ``nomes.csv`` into a name-keyed dict.

    Empty cells in ``frequency_male`` / ``frequency_female`` mean "not seen
    for that sex" — they're zero, not unknown. ``classification`` is the M/F
    label brasil.io assigns (the dataset has only F and M classes; no
    Unisex/Indeterminate row in the published dump). Names are uppercase to
    match the canonical first-name partitions. Each row carries
    ``source = 'brasil.io/genero-nomes'`` so the ingester can stamp the
    provenance through to the parquet ``source`` column.
    """
    by_name: dict[str, dict[str, float | int | str]] = {}
    if not csv_path.exists():
        return by_name
    with csv_path.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get('first_name') or '').strip().upper()
            if not name:
                continue
            try:
                cm = int(row.get('frequency_male') or 0)
            except (TypeError, ValueError):
                cm = 0
            try:
                cf = int(row.get('frequency_female') or 0)
            except (TypeError, ValueError):
                cf = 0
            try:
                ct = int(row.get('frequency_total') or 0)
            except (TypeError, ValueError):
                ct = 0
            if ct <= 0:
                ct = cm + cf
            if ct <= 0:
                continue
            denom = cm + cf
            if denom > 0:
                p_male = cm / denom
                p_female = cf / denom
            else:
                p_male = 0.0
                p_female = 0.0
            by_name[name] = {
                'count_male': cm,
                'count_female': cf,
                'count_total': ct,
                'p_male': p_male,
                'p_female': p_female,
                'classification': (row.get('classification') or '').strip(),
                'group_name': (row.get('group_name') or '').strip(),
                'source': _GENERO_NOMES_SOURCE_LABEL,
            }
    return by_name


def _read_gemini_classifications(jsonl_path: Path) -> dict[str, dict[str, str]]:
    """Read the Gemini gap-fill output produced by
    ``scripts.classify_unmatched_names_gemini``.

    Each line is ``{"name": "...", "gender": "M|F|U", "model": "...", ...}``.
    Returns ``{name (uppercase): {'gender', 'model'}}``. ``U`` rows are
    retained — the caller decides whether to drop them.
    """
    out: dict[str, dict[str, str]] = {}
    if not jsonl_path.exists():
        return out
    with jsonl_path.open(encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            n, g, m = row.get('name'), row.get('gender'), row.get('model')
            if not isinstance(n, str) or not isinstance(g, str):
                continue
            n, g = n.strip().upper(), g.strip().upper()
            m = m.strip() if isinstance(m, str) else ''
            if not n or g not in ('M', 'F', 'U'):
                continue
            out[n] = {'gender': g, 'model': m}
    return out


def _merge_sex_prior(
    genero_csv: Path,
    gemini_jsonl: Path,
) -> tuple[dict[str, dict[str, float | int | str]], dict[str, int]]:
    """Combine the genero-nomes empirical prior with the Gemini gap-fill.

    Genero-nomes is the source of truth where it has a row. Gemini results
    are layered in **only** for names that are absent from genero-nomes.
    Gemini ``U`` (unknown) names are kept in the sex-prior table (with
    ``p_male = p_female = 0``) for transparency, but they're filtered out
    of the period x sex partitions because there's no defensible sex
    weight to apply.

    Returns ``(merged_dict, source_counts)`` where ``source_counts`` is
    ``{'genero': N, 'gemini_M': N, 'gemini_F': N, 'gemini_U': N}`` — used
    by the sidecar so reviewers can see how the row count breaks down.
    """
    merged = _read_genero_nomes(genero_csv)
    gemini = _read_gemini_classifications(gemini_jsonl)
    source_counts = {
        'genero': len(merged),
        'gemini_M': 0,
        'gemini_F': 0,
        'gemini_U': 0,
    }
    for name, info in gemini.items():
        if name in merged:
            continue  # genero-nomes wins
        gender = info['gender']
        model = info['model'] or 'gemini'
        if gender == 'M':
            merged[name] = {
                'count_male': 0,
                'count_female': 0,
                'count_total': 0,
                'p_male': 1.0,
                'p_female': 0.0,
                'classification': 'M',
                'group_name': '',
                'source': model,
            }
            source_counts['gemini_M'] += 1
        elif gender == 'F':
            merged[name] = {
                'count_male': 0,
                'count_female': 0,
                'count_total': 0,
                'p_male': 0.0,
                'p_female': 1.0,
                'classification': 'F',
                'group_name': '',
                'source': model,
            }
            source_counts['gemini_F'] += 1
        else:  # 'U'
            merged[name] = {
                'count_male': 0,
                'count_female': 0,
                'count_total': 0,
                'p_male': 0.0,
                'p_female': 0.0,
                'classification': 'U',
                'group_name': '',
                'source': model,
            }
            source_counts['gemini_U'] += 1
    return merged, source_counts


def ingest_sex_prior(csv_path: Path, out_root: Path, gemini_jsonl: Path | None = None) -> tuple[int, dict[str, int]]:
    """Write ``parquet/sex_prior/scope=national/part.parquet`` from
    genero-nomes, merged with the optional Gemini gap-fill.

    Sources:
      * brasil.io/genero-nomes (Álvaro Justen / @turicas; built from the
        public IBGE Nomes API). Empirical, used wherever it has a row.
      * Gemini ``classifications.jsonl`` (produced by
        ``scripts.classify_unmatched_names_gemini``). Layered in only
        for names absent from genero-nomes. Each row's ``source`` column
        carries the originating label so consumers can audit.

    Returns ``(row_count, source_counts)``.
    """
    by_name, source_counts = _merge_sex_prior(csv_path, gemini_jsonl or Path('/__nonexistent__'))
    if not by_name:
        return 0, source_counts
    names: list[str] = []
    cm: list[int] = []
    cf: list[int] = []
    ct: list[int] = []
    pm: list[float] = []
    pf: list[float] = []
    cls: list[str] = []
    grp: list[str] = []
    src: list[str] = []
    for name, info in by_name.items():
        names.append(name)
        cm.append(int(info['count_male']))
        cf.append(int(info['count_female']))
        ct.append(int(info['count_total']))
        pm.append(float(info['p_male']))
        pf.append(float(info['p_female']))
        cls.append(str(info['classification']))
        grp.append(str(info['group_name']))
        src.append(str(info['source']))
    table = pa.table(
        {
            'name': pa.array(names).dictionary_encode(),
            'count_male': pa.array(cm, type=pa.uint64()),
            'count_female': pa.array(cf, type=pa.uint64()),
            'count_total': pa.array(ct, type=pa.uint64()),
            'p_male': pa.array(pm, type=pa.float64()),
            'p_female': pa.array(pf, type=pa.float64()),
            'classification': pa.array(cls, type=pa.large_string()),
            'group_name': pa.array(grp, type=pa.large_string()),
            'source': pa.array(src, type=pa.large_string()),
        },
        schema=_SEX_PRIOR_SCHEMA,
    )
    partition_dir = out_root / 'sex_prior' / 'scope=national'
    partition_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, partition_dir / 'part.parquet', compression='zstd', compression_level=9)
    sidecar_source = _GENERO_NOMES_PROVENANCE
    if any(source_counts[k] for k in ('gemini_M', 'gemini_F', 'gemini_U')):
        sidecar_source = (
            sidecar_source + ' + Gemini gap-fill for names absent from genero-nomes '
            "(see docs/sources/gemini-gender-classifications.md; row's "
            "'source' column carries the originating label per row)."
        )
    _write_origin_sidecar(
        partition_dir,
        source=sidecar_source,
        url=_GENERO_NOMES_URL,
        rows=len(names),
        extra={
            'partition': 'sex_prior/scope=national',
            'source_counts': source_counts,
        },
    )
    return len(names), source_counts


def ingest_first_names_period_sex(
    src: Path,
    csv_path: Path,
    out_root: Path,
    gemini_jsonl: Path | None = None,
) -> dict[tuple[str, str], int]:
    """Write ``parquet/first_names/period=<P>/sex=<S>/`` partitions.

    Combines the period-only long tail from ``names_data.json`` (IBGE Nomes
    API decade percentages — same data as ``datasets-br/prenomes``,
    row-for-row; see docs/data-origins.md) with a per-name sex prior built
    from:

      * ``brasil.io/genero-nomes`` for the empirical 91.9 % of names, AND
      * a Gemini ``M``/``F`` classification (model
        ``gemini-3.1-flash-lite-preview``) for the remaining ~8 %.
        ``U`` (unknown) Gemini classifications are skipped here — they're
        kept in ``sex_prior`` for transparency but excluded from the
        period x sex partitions because there's no defensible sex weight.

    ``names_data.json`` ships ``percentage`` per (name, period) but no raw
    counts, so we re-weight in probability space::

        weight(name, period, sex=M) ∝ percentage(name, period) * p_male(name)
        weight(name, period, sex=F) ∝ percentage(name, period) * p_female(name)

    Then we normalise within each ``(period, sex)`` slice. Returns
    ``{(period, sex): row_count}``. The full long tail is preserved.

    Each partition's ``data_origin.json`` sidecar reports a
    ``source_counts`` breakdown (genero / gemini_M / gemini_F) so reviewers
    can see how many rows are LLM-tagged.
    """
    if not src.exists():
        return {}
    sex_prior, _ = _merge_sex_prior(csv_path, gemini_jsonl or Path('/__nonexistent__'))
    if not sex_prior:
        return {}
    with src.open(encoding='utf-8') as f:
        data = json.load(f)
    periods = data.get('common_names_percentage', {})
    stats: dict[tuple[str, str], int] = {}
    matched_total = 0
    unmatched_total = 0
    gemini_used: dict[tuple[str, str], int] = {}
    for period, payload in periods.items():
        names_map = payload.get('names', {})
        rows_m: list[tuple[str, float, str]] = []  # name, weight, source
        rows_f: list[tuple[str, float, str]] = []
        for name, info in names_map.items():
            pct = float(info.get('percentage', 0.0) or 0.0)
            if pct <= 0.0:
                continue
            key = str(name).upper()
            prior = sex_prior.get(key)
            if prior is None:
                unmatched_total += 1
                continue
            matched_total += 1
            row_source = str(prior['source'])
            w_m = pct * float(prior['p_male'])
            w_f = pct * float(prior['p_female'])
            if w_m > 0.0:
                rows_m.append((str(name), w_m, row_source))
            if w_f > 0.0:
                rows_f.append((str(name), w_f, row_source))
        for sex, rows in (('M', rows_m), ('F', rows_f)):
            if not rows:
                continue
            labels = [n for n, _, _ in rows]
            raw_weights = [w for _, w, _ in rows]
            weights = _normalise(raw_weights)
            counts = [0] * len(labels)  # match the existing per-period parquet pattern
            n_gemini_rows = sum(1 for _, _, s in rows if s != _GENERO_NOMES_SOURCE_LABEL)
            partition_dir = out_root / 'first_names' / f'period={period}' / f'sex={sex}'
            _write_partition(partition_dir, labels, counts, weights)
            _write_origin_sidecar(
                partition_dir,
                source=(
                    'period weights: IBGE Nomes API v2 decade percentages '
                    '(via ptbr_sampler/data/names_data.json); sex prior: '
                    + _GENERO_NOMES_PROVENANCE
                    + (
                        f' + Gemini gap-fill ({n_gemini_rows} rows in this partition; see docs/sources/gemini-gender-classifications.md)'
                        if n_gemini_rows
                        else ''
                    )
                ),
                url=_GENERO_NOMES_URL,
                rows=len(labels),
                extra={
                    'partition': f'first_names/period={period}/sex={sex}',
                    'derivation': 'weight(name, period, sex) ∝ percentage(name, period) * p_sex(name); '
                    'normalised within each (period, sex).',
                    'rows_from_genero_nomes': len(labels) - n_gemini_rows,
                    'rows_from_gemini': n_gemini_rows,
                },
            )
            stats[period, sex] = len(labels)
            if n_gemini_rows:
                gemini_used[period, sex] = n_gemini_rows
    if matched_total or unmatched_total:
        coverage = matched_total / (matched_total + unmatched_total) if (matched_total + unmatched_total) else 0.0
        print(
            f'  sex-prior coverage across all (name, period) cells: {coverage:.1%} '
            f'({matched_total:,} matched / {unmatched_total:,} unmatched)'
        )
    if gemini_used:
        total_gemini = sum(gemini_used.values())
        print(f'  Gemini gap-fill rows folded in across all partitions: {total_gemini:,}')
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


def _write_count_partition_2022(
    rows: list[tuple[str, int]],
    dest_dir: Path,
    *,
    origin_meta: dict[str, Any],
) -> None:
    """Write a sorted, float64-normalized Zstandard Parquet partition for Census 2022."""
    ordered = sorted(rows, key=lambda kv: (-kv[1], kv[0]))
    names, counts, weights = _normalise_entries([(n, c, float(c)) for n, c in ordered])
    dest_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({'name': names, 'count': counts, 'weight': weights}, schema=_SCHEMA),
        dest_dir / 'part.parquet',
        compression='zstd',
        compression_level=9,
    )
    sidecar = {
        **origin_meta,
        'rows': len(names),
        'count_sum': int(sum(counts)),
        'weight_sum': math.fsum(weights),
        'built_at_utc': datetime.datetime.now(datetime.UTC).isoformat(),
    }
    (dest_dir / 'data_origin.json').write_text(json.dumps(sidecar, indent=2) + '\n', encoding='utf-8')


def ingest_ibge_2022(raw_dir: Path, out_root: Path) -> dict[str, Any]:
    """Ingest pinned IBGE Census 2022 tables into ``out_root / 'census_year=2022'`` atomically."""
    from scripts._cli_paths import resolve_cli_path  # noqa: PLC0415
    from scripts.audit_datasets import (  # noqa: PLC0415
        audit_ibge_2022_tables,
        classify_sex_censoring,
        format_census_2022_display_name,
    )

    raw_dir = resolve_cli_path(raw_dir)
    out_root = resolve_cli_path(out_root)
    audit = audit_ibge_2022_tables(raw_dir)
    manifest_path = raw_dir / 'source_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}

    out_root.mkdir(parents=True, exist_ok=True)
    staging = out_root / '.tmp_census_year=2022'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        ranking = pq.read_table(raw_dir / 'name_ranking.parquet')
        detail = pq.read_table(raw_dir / 'name_detail.parquet')
        by_decade = pq.read_table(raw_dir / 'name_by_decade.parquet')
        by_state = pq.read_table(raw_dir / 'name_by_state.parquet')
        states = pq.read_table(raw_dir / 'state.parquet')

        base_meta = {
            'census_year': 2022,
            'reference_date': '2022-08-01',
            'dataset': manifest.get('dataset', 'olob0/ibge-nomes-no-brasil-2022'),
            'revision': manifest.get('revision', '05efb85c92af43da2ed4ed088d1e0c9f17160e65'),
            'ingester': 'scripts/ingest_to_parquet.py',
        }

        given_nat: list[tuple[str, int]] = []
        surname_nat: list[tuple[str, int]] = []
        given_total_by_key: dict[str, int] = {}
        for name_text, name_type, freq in zip(
            ranking['name_text'].to_pylist(),
            ranking['name_type'].to_pylist(),
            ranking['frequency'].to_pylist(),
            strict=True,
        ):
            disp = format_census_2022_display_name(str(name_text))
            cnt = int(freq)
            if name_type == 'given':
                given_nat.append((disp, cnt))
                given_total_by_key[str(name_text)] = cnt
            elif name_type == 'surname':
                surname_nat.append((disp, cnt))

        _write_count_partition_2022(
            given_nat,
            staging / 'first_names' / 'scope=national',
            origin_meta={**base_meta, 'grain': 'national_given', 'disclosure_threshold': 20},
        )
        _write_count_partition_2022(
            surname_nat,
            staging / 'surnames' / 'scope=national',
            origin_meta={**base_meta, 'grain': 'national_surname_token_slots', 'disclosure_threshold': 20},
        )

        sex_m_rows: list[tuple[str, int]] = []
        sex_f_rows: list[tuple[str, int]] = []
        prior_cols: dict[str, list[Any]] = {k: [] for k in _SEX_PRIOR_2022_SCHEMA.names}

        for name_text, name_type, male, female in zip(
            detail['name_text'].to_pylist(),
            detail['name_type'].to_pylist(),
            detail['male_count'].to_pylist(),
            detail['female_count'].to_pylist(),
            strict=True,
        ):
            if name_type != 'given':
                continue
            key = str(name_text)
            disp = format_census_2022_display_name(key)
            total = given_total_by_key[key]
            m_val = None if male is None else int(male)
            f_val = None if female is None else int(female)
            regime = classify_sex_censoring(total=total, male=m_val, female=f_val)

            if m_val is not None:
                sex_m_rows.append((disp, m_val))
            if f_val is not None:
                sex_f_rows.append((disp, f_val))

            if regime == 'both_observed':
                if m_val is None or f_val is None:
                    raise RuntimeError(f'both_observed requires non-null male/female counts for {key!r}')
                p_m, p_f, residual = m_val / total, f_val / total, 0
            elif regime == 'one_null_exact_zero':
                residual = 0
                p_m = 1.0 if m_val is not None else 0.0
                p_f = 1.0 if f_val is not None else 0.0
            elif regime == 'one_null_suppressed_positive':
                obs_val = m_val if m_val is not None else (f_val or 0)
                residual = total - obs_val
                p_m = (m_val / total) if m_val is not None else math.nan
                p_f = (f_val / total) if f_val is not None else math.nan
            else:
                residual = total
                p_m, p_f = math.nan, math.nan

            prior_cols['name'].append(disp)
            prior_cols['canonical_key'].append(key)
            prior_cols['count_total'].append(total)
            prior_cols['count_male'].append(m_val)
            prior_cols['count_female'].append(f_val)
            prior_cols['residual_unassigned'].append(residual)
            prior_cols['p_male'].append(p_m)
            prior_cols['p_female'].append(p_f)
            prior_cols['censoring_regime'].append(regime)

        _write_count_partition_2022(
            sex_m_rows,
            staging / 'first_names' / 'sex=M',
            origin_meta={
                **base_meta,
                'grain': 'national_given_sex_observed',
                'sex': 'M',
                'observed_male_mass': audit['censoring'].observed_male_mass,
                'observed_female_mass': audit['censoring'].observed_female_mass,
                'disclosure_threshold': 20,
            },
        )
        _write_count_partition_2022(
            sex_f_rows,
            staging / 'first_names' / 'sex=F',
            origin_meta={
                **base_meta,
                'grain': 'national_given_sex_observed',
                'sex': 'F',
                'observed_male_mass': audit['censoring'].observed_male_mass,
                'observed_female_mass': audit['censoring'].observed_female_mass,
                'disclosure_threshold': 20,
            },
        )

        sex_prior_dir = staging / 'sex_prior' / 'scope=national'
        sex_prior_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table(prior_cols, schema=_SEX_PRIOR_2022_SCHEMA),
            sex_prior_dir / 'part.parquet',
            compression='zstd',
            compression_level=9,
        )
        (sex_prior_dir / 'data_origin.json').write_text(
            json.dumps(
                {
                    **base_meta,
                    'grain': 'national_sex_prior_nullable',
                    'rows': len(prior_cols['name']),
                    'disclosure_threshold': 20,
                    'built_at_utc': datetime.datetime.now(datetime.UTC).isoformat(),
                },
                indent=2,
            )
            + '\n',
            encoding='utf-8',
        )

        decade_buckets: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for name_text, name_type, dec, freq in zip(
            by_decade['name_text'].to_pylist(),
            by_decade['name_type'].to_pylist(),
            by_decade['decade'].to_pylist(),
            by_decade['frequency'].to_pylist(),
            strict=True,
        ):
            if name_type == 'given':
                decade_buckets[int(dec)].append((format_census_2022_display_name(str(name_text)), int(freq)))

        for dec, period_key in CENSUS_2022_DECADE_TO_PERIOD.items():
            if not decade_buckets[dec]:
                continue
            _write_count_partition_2022(
                decade_buckets[dec],
                staging / 'first_names' / f'period={period_key}',
                origin_meta={
                    **base_meta,
                    'grain': 'national_birth_cohort_survivors',
                    'olob0_decade': dec,
                    'period': period_key,
                    'disclosure_threshold': 20,
                },
            )

        code_to_uf = dict(zip(states['code'].to_pylist(), states['abbreviation'].to_pylist(), strict=True))
        code_to_pop = dict(zip(states['code'].to_pylist(), states['population'].to_pylist(), strict=True))
        uf_given: dict[str, list[tuple[str, int]]] = defaultdict(list)
        uf_surname: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for name_text, name_type, scode, freq in zip(
            by_state['name_text'].to_pylist(),
            by_state['name_type'].to_pylist(),
            by_state['state_code'].to_pylist(),
            by_state['frequency'].to_pylist(),
            strict=True,
        ):
            uf = str(code_to_uf[int(scode)])
            disp = format_census_2022_display_name(str(name_text))
            if name_type == 'given':
                uf_given[uf].append((disp, int(freq)))
            elif name_type == 'surname':
                uf_surname[uf].append((disp, int(freq)))

        uf_to_pop = {str(code_to_uf[c]): int(p) for c, p in code_to_pop.items()}
        for uf, pop_u in sorted(uf_to_pop.items()):
            if uf_given[uf]:
                _write_count_partition_2022(
                    uf_given[uf],
                    staging / 'first_names' / f'uf={uf}',
                    origin_meta={
                        **base_meta,
                        'grain': 'uf_given',
                        'uf': uf,
                        'uf_population_2022': pop_u,
                        'disclosure_threshold': 15,
                    },
                )
            if uf_surname[uf]:
                _write_count_partition_2022(
                    uf_surname[uf],
                    staging / 'surnames' / f'uf={uf}',
                    origin_meta={
                        **base_meta,
                        'grain': 'uf_surname_token_slots',
                        'uf': uf,
                        'uf_population_2022': pop_u,
                        'disclosure_threshold': 15,
                    },
                )

        states_dir = staging / 'states'
        states_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(states, states_dir / 'part.parquet', compression='zstd', compression_level=9)
        (states_dir / 'data_origin.json').write_text(
            json.dumps(
                {
                    **base_meta,
                    'grain': 'uf_resident_population_2022',
                    'rows': states.num_rows,
                    'built_at_utc': datetime.datetime.now(datetime.UTC).isoformat(),
                },
                indent=2,
            )
            + '\n',
            encoding='utf-8',
        )

        final_dest = out_root / 'census_year=2022'
        backup_dest = out_root / '.bak_census_year=2022'
        if backup_dest.exists():
            shutil.rmtree(backup_dest)
        if final_dest.exists():
            final_dest.replace(backup_dest)
        staging.replace(final_dest)
        if backup_dest.exists():
            shutil.rmtree(backup_dest)
        return audit
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


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

    from scripts._cli_paths import resolve_cli_path  # noqa: PLC0415

    data_dir: Path = resolve_cli_path(args.data_dir)
    out_root: Path = resolve_cli_path(args.out)
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

    genero_csv = data_dir / 'raw' / 'genero_nomes' / 'nomes.csv'
    gemini_jsonl = data_dir / 'raw' / 'gemini_gender' / 'classifications.jsonl'
    print(f'Ingesting national sex prior from {genero_csv}...')
    print(f'  source: {_GENERO_NOMES_URL}')
    if gemini_jsonl.exists():
        print(f'  + Gemini gap-fill: {gemini_jsonl.relative_to(_REPO_ROOT)}')
    sex_prior_rows, source_counts = ingest_sex_prior(genero_csv, out_root, gemini_jsonl)
    if sex_prior_rows == 0:
        print('  (no genero-nomes data found — run "python -m scripts.download_datasets --fetch-genero-nomes" first)')
    else:
        breakdown = (
            f'genero={source_counts["genero"]:,}, '
            f'gemini_M={source_counts["gemini_M"]:,}, '
            f'gemini_F={source_counts["gemini_F"]:,}, '
            f'gemini_U={source_counts["gemini_U"]:,}'
        )
        print(f'  rows: {sex_prior_rows:,} ({breakdown})')

    print('Ingesting first names (period x sex national) from period counts + sex prior...')
    period_sex_stats = ingest_first_names_period_sex(data_dir / 'names_data.json', genero_csv, out_root, gemini_jsonl)
    if not period_sex_stats:
        print('  (sex prior unavailable — period x sex partitions skipped)')
    else:
        print(f'  partitions written: {len(period_sex_stats)} (periods: {len({p for p, _ in period_sex_stats})})')

    print('Ingesting national surnames...')
    n_surnames = ingest_surnames(data_dir / 'surnames_data.json', out_root)
    print(f'  rows: {n_surnames}')

    print('Ingesting cleaned middle names...')
    kept, dropped = ingest_middle_names(data_dir / 'middle_names.json', out_root, vocab)
    print(f'  kept: {kept}, dropped: {dropped}')

    print('Ingesting state population weights...')
    n_states = ingest_states(data_dir / 'locations_data.json', out_root)
    print(f'  rows: {n_states}')

    raw_2022 = data_dir / 'raw' / 'ibge_nomes_2022'
    if (raw_2022 / 'name_ranking.parquet').exists():
        print(f'Ingesting IBGE Census 2022 tables from {raw_2022}...')
        audit_2022 = ingest_ibge_2022(raw_2022, out_root)
        print(
            f'  census_year=2022 written: given={audit_2022["given_rows"]:,}, '
            f'surnames={audit_2022["surname_rows"]:,}, '
            f'pop={audit_2022["national_population"]:,}'
        )
    else:
        print('  (no raw IBGE Census 2022 data found — run "python -m scripts.download_datasets --fetch-ibge-2022" first)')

    print(f'\nParquet layout written under: {out_root}')
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())

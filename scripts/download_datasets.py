"""Walkthrough for fetching the raw datasets that feed ``scripts.ingest_to_parquet``.

This module is the single explicit first-step workflow asked for in
``todo.md`` task 1. It does **not** attempt to silently scrape IBGE or
Arpen — those sources have terms-of-use, large file sizes, and rate
limits that the user should encounter consciously. Instead, it:

1. lists every dataset that the bundled JSON / Parquet artefacts derive
   from,
2. prints the canonical source URL plus the local raw path the project
   expects,
3. validates the presence and basic shape of the JSON files already
   shipped with the repo so the contributor knows whether they need to
   download anything at all,
4. invokes :mod:`scripts.ingest_to_parquet` (or prints the command) so a
   contributor can rebuild the partitioned Parquet layout end-to-end.

Run::

    python -m scripts.download_datasets             # status report only
    python -m scripts.download_datasets --rebuild   # also runs ingestion

The tool intentionally stays short and read-only by default. The full
download-and-rebuild walkthrough lives in ``docs/data-origins.md`` and
``docs/architecture.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / 'ptbr_sampler' / 'data'


@dataclass(frozen=True)
class DatasetTarget:
    """One raw dataset feeding the bundled Parquet layout."""

    label: str
    description: str
    source_url: str
    raw_local_path: Path
    powers: str


TARGETS: tuple[DatasetTarget, ...] = (
    DatasetTarget(
        label='IBGE Nomes API v2 (first names by period)',
        description=(
            'Decade-of-birth frequencies for given names (2010 Census). '
            'Existing payload in names_data.json was extracted from this API.'
        ),
        source_url='https://servicodados.ibge.gov.br/api/docs/nomes?versao=2',
        raw_local_path=_DATA_DIR / 'names_data.json',
        powers='ptbr_sampler/data/parquet/first_names/period=<period>/part.parquet',
    ),
    DatasetTarget(
        label='IBGE Nomes no Brasil 2022 (first names + surnames by UF, sex)',
        description=(
            'Second edition of Nomes no Brasil. Adds UF- and sex-conditioned '
            'rankings. Not bundled today — drop CSV/Parquet exports under '
            'ptbr_sampler/data/raw/ibge_nomes_2022/ before rebuilding.'
        ),
        source_url='https://www.ibge.gov.br/apps/nomes/',
        raw_local_path=_DATA_DIR / 'raw' / 'ibge_nomes_2022',
        powers='Future surnames/uf=<UF>/period=<period> and first_names/uf=<UF>/sex=<M|F> partitions.',
    ),
    DatasetTarget(
        label='IBGE Estimativas da População 2024',
        description=(
            'Resident-population estimates per UF and municipality, 1 July '
            '2024 reference. Already consumed by locations_data.json / '
            'cities_with_ceps.json.'
        ),
        source_url='https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.pdf',
        raw_local_path=_DATA_DIR / 'locations_data.json',
        powers='ptbr_sampler/data/parquet/states/part.parquet',
    ),
    DatasetTarget(
        label='Arpen-Brasil 2024 newborn ranking',
        description=(
            'Civil-registry newborn ranking. Used as a benchmark for recent '
            'cohorts, not as a stock-population replacement.'
        ),
        source_url='https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/',
        raw_local_path=_DATA_DIR / 'raw' / 'arpen_2024',
        powers='Validation only (docs/sources/arpen-2024-rankings.md).',
    ),
    DatasetTarget(
        label='Surnames national (legacy 2010-era extract)',
        description=(
            'Pooled national surname distribution consistent with IBGE 2022 '
            "headline figures. Currently bundled as surnames_data.json."
        ),
        source_url='https://www.ibge.gov.br/apps/nomes/',
        raw_local_path=_DATA_DIR / 'surnames_data.json',
        powers='ptbr_sampler/data/parquet/surnames/scope=national/part.parquet',
    ),
    DatasetTarget(
        label='Middle names raw extract',
        description=(
            'Civil-registry second-given-names extraction. Filtered against '
            'the given-name whitelist in ptbr_sampler/sampling/vocabulary.py '
            'during ingestion. See docs/data-origins.md for provenance.'
        ),
        source_url='see docs/data-origins.md (extraction was authorial)',
        raw_local_path=_DATA_DIR / 'middle_names.json',
        powers='ptbr_sampler/data/parquet/middle_names/part.parquet',
    ),
    DatasetTarget(
        label='Cities + CEP ranges + DDD',
        description=(
            'Municipal population shares (IBGE 2024), Correios CEP prefix '
            'bands, and Anatel DDD allocation. Bundled today.'
        ),
        source_url='https://buscacepinter.correios.com.br/',
        raw_local_path=_DATA_DIR / 'cities_with_ceps.json',
        powers='ptbr_sampler/data/parquet/states + city draws (no Parquet partition for cities yet).',
    ),
)


def _file_status(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, 'missing'
    if path.is_dir():
        return True, f'directory ({sum(1 for _ in path.iterdir())} entries)'
    size_kib = path.stat().st_size / 1024
    return True, f'{size_kib:,.1f} KiB'


def _validate_json_shape(path: Path) -> str | None:
    """Return a one-line shape summary if ``path`` is a JSON file we know."""
    if not path.is_file() or path.suffix != '.json':
        return None
    try:
        with path.open(encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as err:
        return f'parse error: {err}'

    if 'common_names_percentage' in data:
        periods = list(data['common_names_percentage'].keys())
        return f'first-name periods: {len(periods)} ({", ".join(periods[:3])}...)'
    if 'surnames' in data:
        keys = list(data['surnames'].keys())
        return f'surname rows: {len(keys)} (incl. {"top_40 " if "top_40" in keys else ""}entries)'
    if 'second_names' in data:
        n_second = len(data.get('second_names', {}))
        pct = data.get('percentage_with_second')
        return f'second_names: {n_second} rows; percentage_with_second={pct:.4f}%'
    if 'states' in data and 'cities' in data:
        return f"states: {len(data['states'])}; cities: {len(data['cities'])}"
    if 'cities' in data:
        return f"cities: {len(data['cities'])}"
    return f'top-level keys: {list(data)[:5]}'


def report() -> int:
    print('ptbr-sampler — dataset download / rebuild walkthrough')
    print('-' * 72)
    missing = 0
    for target in TARGETS:
        present, summary = _file_status(target.raw_local_path)
        marker = 'OK ' if present else 'MISS'
        print(f'[{marker}] {target.label}')
        print(f'      source : {target.source_url}')
        print(f'      local  : {target.raw_local_path}  ({summary})')
        print(f'      powers : {target.powers}')
        shape = _validate_json_shape(target.raw_local_path) if present else None
        if shape:
            print(f'      shape  : {shape}')
        if not present:
            missing += 1
        print(f'      notes  : {target.description}')
        print()
    print('-' * 72)
    if missing:
        print(f'{missing} dataset(s) not present locally — see source URLs above.')
    print('Once raw datasets are in place, rebuild Parquet with:')
    print('    python -m scripts.ingest_to_parquet')
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='After the report, run scripts.ingest_to_parquet to rebuild the Parquet layout.',
    )
    args = parser.parse_args(argv)

    missing = report()

    if args.rebuild:
        from scripts.ingest_to_parquet import main as ingest_main  # noqa: PLC0415 - keep ingest import lazy
        print('\nRebuilding Parquet layout...')
        rc = ingest_main([])
        if rc != 0:
            return rc

    return 0 if missing == 0 else 0  # missing raw files is informational, not a failure


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())

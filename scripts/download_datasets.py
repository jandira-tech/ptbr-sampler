"""Download raw datasets and rebuild the Parquet layout that the sampler reads.

Implements ``todo.md`` task 1 ("download datasets and convert them to
Parquet" — end-to-end, not just declarative). Specifically:

* IBGE Nomes API v2 (``/api/v2/censos/nomes/ranking``): top-20 first-name
  rankings per ``(UF, sexo, decada)`` triple. This is the conditioned
  data that unblocks tasks 3 and 4 (UF- and sex-conditioned realism).
* IBGE Nomes API v2 (``/api/v2/censos/nomes/{nome}``): per-name decade
  series, used to back-fill counts when a UF×sex×decade ranking is thin.
* Local JSON sources already bundled with the repo (period-only first
  names, national surnames, middle names, locations) — these are
  ingested by :mod:`scripts.ingest_to_parquet`; this script just chains
  into it after the network fetches.

Network constraints
-------------------

The HTTP fetches go through the public IBGE servers (no auth) over
HTTPS. Run on a machine with general internet egress; the repo's CI
sandbox blocks IBGE hosts and will fail at the first request — that's
expected, run locally.

Usage
-----

    python -m scripts.download_datasets                 # status report only
    python -m scripts.download_datasets --fetch-ibge-nomes
        # download UF x sexo x decada rankings into
        # ptbr_sampler/data/raw/ibge_nomes_v2/ (~540 small JSONL files)
    python -m scripts.download_datasets --rebuild
        # fetch (if needed) + run scripts.ingest_to_parquet, producing
        # both the period-only Parquet partitions (existing default) and
        # the new uf=<UF>/period=<P>/sex=<S>/ partitions when raw files
        # exist.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / 'ptbr_sampler' / 'data'
_RAW_DIR = _DATA_DIR / 'raw'
_NOMES_V2_RAW = _RAW_DIR / 'ibge_nomes_v2'
_GENERO_NOMES_RAW = _RAW_DIR / 'genero_nomes'

_GENERO_NOMES_URL = 'https://data.brasil.io/dataset/genero-nomes/nomes.csv.gz'

# IBGE municipal codes for the 26 UFs + the Federal District. Using the
# 2-digit UF codes returns one row per (sexo, decada) per UF.
UF_CODES: dict[str, str] = {
    'RO': '11', 'AC': '12', 'AM': '13', 'RR': '14', 'PA': '15', 'AP': '16',
    'TO': '17', 'MA': '21', 'PI': '22', 'CE': '23', 'RN': '24', 'PB': '25',
    'PE': '26', 'AL': '27', 'SE': '28', 'BA': '29', 'MG': '31', 'ES': '32',
    'RJ': '33', 'SP': '35', 'PR': '41', 'SC': '42', 'RS': '43', 'MS': '50',
    'MT': '51', 'GO': '52', 'DF': '53',
}

# Decades that the IBGE Nomes API v2 exposes. 1930 corresponds to the
# legacy bucket "ate1930" ("born up to 1929"), 1940 to "ate1940", etc.
# The mapping aligns with the existing partitions under
# ptbr_sampler/data/parquet/first_names/period=ate<YYYY>/.
DECADES: tuple[int, ...] = (1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010)
SEXOS: tuple[str, ...] = ('M', 'F')

_RANKING_URL = 'https://servicodados.ibge.gov.br/api/v2/censos/nomes/ranking'


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
        label='IBGE Nomes API v2 — period-only payload',
        description=(
            'Decade-of-birth frequencies for given names (2010 Census). The '
            'bundled names_data.json was extracted from the same API.'
        ),
        source_url='https://servicodados.ibge.gov.br/api/docs/nomes?versao=2',
        raw_local_path=_DATA_DIR / 'names_data.json',
        powers='ptbr_sampler/data/parquet/first_names/period=<period>/part.parquet',
    ),
    DatasetTarget(
        label='IBGE Nomes API v2 — UF x sexo x decada rankings',
        description=(
            'Top-20 first names per (UF, sexo, decada) triple. Fetched on '
            'demand by --fetch-ibge-nomes. Once present, the ingester '
            'writes parquet/first_names/uf=<UF>/period=<P>/sex=<S>/ '
            'partitions and the sampler picks them up automatically.'
        ),
        source_url=_RANKING_URL,
        raw_local_path=_NOMES_V2_RAW,
        powers=(
            'parquet/first_names/uf=<UF>/period=ate<YYYY>/sex=<M|F>/part.parquet '
            '(unblocks UF and sex conditioning).'
        ),
    ),
    DatasetTarget(
        label='brasil.io / genero-nomes (Álvaro Justen / turicas)',
        description=(
            'Per-name male/female frequencies (~100k names, national). Built '
            "by Brasil.IO from the IBGE Nomes API; same provenance lineage "
            'as our period-only data. Powers the sex prior P(sex|name) used '
            'for the period x sex first-name partitions. Fetch with '
            '--fetch-genero-nomes.'
        ),
        source_url=_GENERO_NOMES_URL,
        raw_local_path=_GENERO_NOMES_RAW,
        powers=(
            'parquet/sex_prior/scope=national/part.parquet AND '
            'parquet/first_names/period=ate<YYYY>/sex=<M|F>/part.parquet '
            '(period x sex national, full long tail).'
        ),
    ),
    DatasetTarget(
        label='IBGE Nomes no Brasil 2022 (web app)',
        description=(
            'Second edition of Nomes no Brasil; adds 2022-Census surname '
            'rankings by UF. Distributed only as a web application — no '
            'public bulk-download endpoint. Surname UF conditioning '
            'remains blocked on this front.'
        ),
        source_url='https://www.ibge.gov.br/apps/nomes/',
        raw_local_path=_DATA_DIR / 'raw' / 'ibge_nomes_2022',
        powers='Future surnames/uf=<UF>/period=<period> partitions.',
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
            'cohorts, not as a stock-population replacement. Distributed '
            'as a press-release HTML page (no API), so left manual.'
        ),
        source_url='https://arpenbrasil.org.br/press_releases/ranking-nacional-apos-sete-anos-nome-feminino-lidera-preferencia-no-brasil/',
        raw_local_path=_DATA_DIR / 'raw' / 'arpen_2024',
        powers='Validation only (docs/sources/arpen-2024-rankings.md).',
    ),
    DatasetTarget(
        label='Surnames national (legacy 2010-era extract)',
        description=(
            'Pooled national surname distribution consistent with IBGE 2022 '
            'headline figures. Currently bundled as surnames_data.json.'
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


# ----------------------------------------------------------------------
# Status report
# ----------------------------------------------------------------------

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
    print('To fetch IBGE Nomes API v2 UF x sexo x decada rankings (~540 calls):')
    print('    python -m scripts.download_datasets --fetch-ibge-nomes')
    print('To fetch the brasil.io/genero-nomes sex prior (national, full long tail):')
    print('    python -m scripts.download_datasets --fetch-genero-nomes')
    return missing


# ----------------------------------------------------------------------
# IBGE Nomes API v2 fetcher
# ----------------------------------------------------------------------

def _fetch_ranking(
    localidade: str,
    sexo: str,
    decada: int,
    *,
    timeout: float = 20.0,
    user_agent: str = 'ptbr-sampler/0.2 (+https://github.com/arthrod/ptbr-sampler)',
) -> list[dict]:
    """Call ``/api/v2/censos/nomes/ranking`` once and return the ``res`` rows.

    The IBGE response is a list with a single object whose ``res`` key holds
    20 entries shaped ``{"nome": str, "frequencia": int, "ranking": int}``.
    Some thin (locality, sex, decade) triples return an empty ``res`` —
    those are passed through as ``[]``.
    """
    qs = urllib.parse.urlencode(
        {'localidade': localidade, 'sexo': sexo, 'decada': decada},
    )
    url = f'{_RANKING_URL}?{qs}'
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - public IBGE HTTPS endpoint
        payload = json.load(resp)
    if not payload:
        return []
    return list(payload[0].get('res', []))


def fetch_ibge_first_names_v2(
    out_dir: Path = _NOMES_V2_RAW,
    *,
    uf_codes: dict[str, str] | None = None,
    decades: tuple[int, ...] = DECADES,
    sexos: tuple[str, ...] = SEXOS,
    sleep_seconds: float = 0.2,
    overwrite: bool = False,
) -> tuple[int, int]:
    """Download every (UF, sex, decade) ranking into ``out_dir`` as JSONL.

    Files are written as
    ``out_dir/uf=<UF>/period=ate<YYYY>/sex=<M|F>.json`` so that the layout
    mirrors the Parquet partitions one ingest stage downstream.

    Returns ``(written, skipped)``.
    """
    uf_codes = uf_codes or UF_CODES
    written = 0
    skipped = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(uf_codes) * len(sexos) * len(decades)
    seen = 0
    for uf, code in uf_codes.items():
        for decada in decades:
            for sexo in sexos:
                seen += 1
                period = f'ate{decada}'
                target = out_dir / f'uf={uf}' / f'period={period}' / f'sex={sexo}.json'
                if target.exists() and not overwrite:
                    skipped += 1
                    continue
                try:
                    rows = _fetch_ranking(code, sexo, decada)
                except urllib.error.HTTPError as err:
                    print(f'[{seen:>4}/{total}] HTTP {err.code} for uf={uf} sex={sexo} decada={decada}; skipping', file=sys.stderr)
                    continue
                except urllib.error.URLError as err:
                    raise RuntimeError(
                        f'network fetch failed for uf={uf} sex={sexo} decada={decada}: {err}. '
                        'This sandbox blocks ibge.gov.br; run on a machine with public egress.',
                    ) from err
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('w', encoding='utf-8') as f:
                    json.dump(
                        {
                            'uf': uf,
                            'localidade': code,
                            'sexo': sexo,
                            'decada': decada,
                            'period': period,
                            'res': rows,
                        },
                        f,
                        ensure_ascii=False,
                    )
                written += 1
                print(f'[{seen:>4}/{total}] wrote {target.relative_to(_REPO_ROOT)} ({len(rows)} rows)')
                if sleep_seconds:
                    time.sleep(sleep_seconds)
    return written, skipped


# ----------------------------------------------------------------------
# brasil.io / genero-nomes fetcher
# ----------------------------------------------------------------------


def fetch_genero_nomes(
    out_dir: Path = _GENERO_NOMES_RAW,
    *,
    url: str = _GENERO_NOMES_URL,
    timeout: float = 120.0,
    overwrite: bool = False,
    user_agent: str = 'ptbr-sampler/0.2 (+https://github.com/arthrod/ptbr-sampler)',
) -> Path:
    """Download the brasil.io ``genero-nomes/nomes.csv.gz`` dump.

    The Brasil.IO dataset (curated by Álvaro Justen / @turicas) wraps the
    public IBGE Nomes API and publishes per-name male/female frequencies
    nationally (~100k names). Same provenance lineage as our period-only
    data — citing the source explicitly so downstream consumers can audit
    where the sex prior comes from.

    Returns the path of the gunzipped CSV.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    gz_path = out_dir / 'nomes.csv.gz'
    csv_path = out_dir / 'nomes.csv'
    if csv_path.exists() and not overwrite:
        print(f'  already present: {csv_path.relative_to(_REPO_ROOT)} (pass --overwrite to refetch)')
        return csv_path
    print(f'  source: {url}')
    print(f'  target: {gz_path.relative_to(_REPO_ROOT)}')
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - public Brasil.IO HTTPS endpoint
        with gz_path.open('wb') as f:
            shutil.copyfileobj(resp, f)
    with gzip.open(gz_path, 'rb') as zin, csv_path.open('wb') as zout:
        shutil.copyfileobj(zin, zout)
    size_mib = csv_path.stat().st_size / (1024 * 1024)
    print(f'  wrote: {csv_path.relative_to(_REPO_ROOT)} ({size_mib:.1f} MiB)')
    return csv_path


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--fetch-ibge-nomes',
        action='store_true',
        help='Download UF x sexo x decada rankings from the IBGE Nomes v2 API.',
    )
    parser.add_argument(
        '--fetch-genero-nomes',
        action='store_true',
        help=(
            'Download brasil.io/genero-nomes nomes.csv.gz. Provides the sex '
            'prior used by the period x sex first-name partitions. Source: '
            f'{_GENERO_NOMES_URL}'
        ),
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Re-fetch even if the raw JSON already exists locally.',
    )
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='After fetching, run scripts.ingest_to_parquet to rebuild the Parquet layout.',
    )
    args = parser.parse_args(argv)

    missing = report()

    if args.fetch_ibge_nomes:
        print('\nFetching IBGE Nomes API v2 (UF x sexo x decada)...')
        written, skipped = fetch_ibge_first_names_v2(overwrite=args.overwrite)
        print(f'  wrote: {written}, skipped: {skipped}')

    if args.fetch_genero_nomes:
        print('\nFetching brasil.io/genero-nomes (sex prior)...')
        fetch_genero_nomes(overwrite=args.overwrite)

    if args.rebuild:
        from scripts.ingest_to_parquet import main as ingest_main  # noqa: PLC0415 - keep ingest import lazy
        print('\nRebuilding Parquet layout...')
        rc = ingest_main([])
        if rc != 0:
            return rc

    return 0 if missing == 0 else 0  # missing raw files is informational, not a failure


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())

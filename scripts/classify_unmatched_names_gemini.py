"""Classify the first names that genero-nomes doesn't cover, using Gemini.

About 8 % of the (name, period) cells in ``names_data.json`` are absent
from ``brasil.io/genero-nomes`` — typically very rare or
spelling-variant names (``Aadriana``, ``Edileuza``, ``Mariazinha``…).
Without a sex prior they're dropped from the
``parquet/first_names/period=<P>/sex=<S>/`` partitions, which slightly
narrows the long tail of the sex-conditioned sampler.

This script fills the gap with **Gemini** (model
``gemini-3.1-flash-lite-preview`` by default) running 100 concurrent
workers. Each name is classified as ``M``, ``F``, or ``U`` (genuinely
ambiguous unisex). The prompt explicitly instructs the model to use ``U``
**only exceptionally**, since assigning a sex to a genuinely common-gender
name in Brazil is the exception, not the norm.

The classifications are LLM-derived, **not** empirical IBGE data. The
ingester treats them as a separate ``source`` and persists that label
through to the sex-prior parquet, so reviewers can always tell which rows
came from genero-nomes (empirical) and which from Gemini (model-tagged).

Usage::

    export GEMINI_API_KEY=...    # required; the script fails fast otherwise
    uv pip install google-genai  # one-off; the SDK is not a runtime dep
    python -m scripts.classify_unmatched_names_gemini
        # default: classify every unmatched name with 100 workers, append
        # to ptbr_sampler/data/raw/gemini_gender/classifications.jsonl

    python -m scripts.classify_unmatched_names_gemini --limit 50 --dry-run
        # preview the first 50 unmatched names without calling the API

    python -m scripts.classify_unmatched_names_gemini --workers 50 --limit 200
        # smaller batch with fewer concurrent workers (e.g. for QPS-limited keys)

The script is idempotent: it reads the existing JSONL on each run and only
classifies names that aren't there yet. Re-run after every refresh of
``names_data.json`` or ``genero-nomes`` to fill any new gaps.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DATA_DIR = _REPO_ROOT / 'ptbr_sampler' / 'data'
_NAMES_DATA_JSON = _DATA_DIR / 'names_data.json'
_GENERO_NOMES_CSV = _DATA_DIR / 'raw' / 'genero_nomes' / 'nomes.csv'
_GEMINI_DIR = _DATA_DIR / 'raw' / 'gemini_gender'
_GEMINI_JSONL = _GEMINI_DIR / 'classifications.jsonl'

_DEFAULT_MODEL = 'gemini-3.1-flash-lite-preview'
_DEFAULT_WORKERS = 100

_PROMPT_TEMPLATE = (
    'You are classifying Brazilian Portuguese first names by gender. The '
    'name is "{name}". Reply with EXACTLY one character — and nothing '
    'else:\n'
    '  M  -> commonly given to males in Brazil\n'
    '  F  -> commonly given to females in Brazil\n'
    '  U  -> truly ambiguous unisex in Brazil; use this only exceptionally, '
    'because most Portuguese-language given names are gendered. If a name '
    'has a clear majority sex even with rare crossover use, return that '
    'majority sex (M or F), not U.\n'
    'Output exactly one character: M, F, or U.'
)


# ---------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------

def _load_names_data_unique(path: Path) -> set[str]:
    """Return every distinct first name that appears in ``names_data.json``.

    Names are uppercased so they match the genero-nomes / parquet layout.
    """
    with path.open(encoding='utf-8') as f:
        data = json.load(f)
    names: set[str] = set()
    for payload in data.get('common_names_percentage', {}).values():
        for name in payload.get('names', {}):
            if not name:
                continue
            names.add(str(name).strip().upper())
    return names


def _load_genero_nomes_keys(path: Path) -> set[str]:
    """Return every name (uppercased) covered by genero-nomes."""
    if not path.exists():
        return set()
    keys: set[str] = set()
    with path.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            n = (row.get('first_name') or '').strip().upper()
            if n:
                keys.add(n)
    return keys


def _load_existing_classifications(path: Path) -> dict[str, str]:
    """Return name (uppercased) -> 'M'|'F'|'U' from the existing JSONL."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding='utf-8') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue  # skip corrupted lines; will be re-classified on next run
            n = (row.get('name') or '').strip().upper()
            g = (row.get('gender') or '').strip().upper()
            if n and g in ('M', 'F', 'U'):
                out[n] = g
    return out


def compute_unmatched_names(limit: int | None = None) -> list[str]:
    """Cross-reference and return the names that still need classification."""
    all_names = _load_names_data_unique(_NAMES_DATA_JSON)
    covered = _load_genero_nomes_keys(_GENERO_NOMES_CSV)
    already = set(_load_existing_classifications(_GEMINI_JSONL))
    pending = sorted(n for n in all_names if n not in covered and n not in already)
    if limit is not None:
        pending = pending[:limit]
    return pending


# ---------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------

def _build_client(api_key: str):
    """Return a google-genai client; fail fast with an actionable message."""
    try:
        from google import genai  # noqa: PLC0415 - import lazily so --dry-run works without the SDK
    except ImportError as err:  # pragma: no cover - import guard
        raise SystemExit(
            'google-genai is not installed. Run "uv pip install google-genai" '
            '(or "pip install google-genai") and re-run this script.'
        ) from err
    return genai.Client(api_key=api_key)


def _parse_gender(text: str) -> str:
    """Coerce a Gemini response into 'M', 'F', or 'U'.

    The prompt asks for exactly one character but real models occasionally
    add whitespace, quotes, or short justifications. We're lenient.
    """
    if not text:
        return 'U'
    s = text.strip().strip('"\'').strip().upper()
    if not s:
        return 'U'
    first = s[0]
    if first in ('M', 'F', 'U'):
        return first
    # Fallbacks for verbose responses ("Male", "Feminino", etc.)
    if 'FEMAL' in s or 'FEMIN' in s:
        return 'F'
    if 'MALE' in s or 'MASCUL' in s:
        return 'M'
    return 'U'


_RETRY_DELAY_RE = re.compile(r"'?retryDelay'?\s*:\s*'?(\d+(?:\.\d+)?)s?'?", re.IGNORECASE)


def _retry_seconds_from_error(err: Exception) -> float | None:
    """Extract a server-suggested retry delay from a Gemini ClientError, if any.

    The SDK's ClientError stringifies a JSON payload that contains
    ``"retryDelay": "27s"`` for 429s. Honouring that delay is the only
    polite way to ride out a quota window.
    """
    text = str(err)
    if '429' not in text and 'RESOURCE_EXHAUSTED' not in text:
        return None
    m = _RETRY_DELAY_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def classify_one(client, name: str, *, model: str, max_retries: int = 6, retry_base: float = 2.0) -> dict:
    """Classify a single name via Gemini, with quota-aware retry/backoff.

    On 429 (RESOURCE_EXHAUSTED) we honour the server-suggested retryDelay
    (typically ~30s for the per-minute quota window). For other errors we
    fall back to exponential backoff. Total max wait ≈ 6 × ~30s = 3 min
    per name — slow but predictable.
    """
    prompt = _PROMPT_TEMPLATE.format(name=name)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            text = getattr(response, 'text', None) or ''
            gender = _parse_gender(text)
            return {
                'name': name,
                'gender': gender,
                'model': model,
                'classified_at_utc': datetime.now(UTC).isoformat(timespec='seconds'),
                'raw_response': text.strip()[:64],  # short snapshot for audit; truncated to keep the JSONL tidy
            }
        except Exception as err:  # noqa: BLE001 - the SDK raises a heterogeneous tree of errors
            last_err = err
            quota_delay = _retry_seconds_from_error(err)
            if quota_delay is not None:
                # Add a small jitter so 100 workers don't all wake at the same instant.
                time.sleep(quota_delay + 1.0 + (attempt * 0.5))
            else:
                time.sleep(retry_base ** attempt)
    return {
        'name': name,
        'gender': 'U',
        'model': model,
        'classified_at_utc': datetime.now(UTC).isoformat(timespec='seconds'),
        'error': f'{type(last_err).__name__}: {last_err}' if last_err else 'unknown',
    }


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------

def _append_jsonl(path: Path, row: dict, lock: threading.Lock) -> None:
    """Thread-safe append of a single JSONL row."""
    line = json.dumps(row, ensure_ascii=False) + '\n'
    with lock:
        with path.open('a', encoding='utf-8') as f:
            f.write(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=_DEFAULT_MODEL, help=f'Gemini model id (default: {_DEFAULT_MODEL})')
    parser.add_argument('--workers', type=int, default=_DEFAULT_WORKERS, help='Concurrent workers (default: 100)')
    parser.add_argument('--limit', type=int, default=None, help='Classify only the first N unmatched names')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print the unmatched names but do not call the API',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=_GEMINI_JSONL,
        help=f'JSONL output (default: {_GEMINI_JSONL.relative_to(_REPO_ROOT)})',
    )
    args = parser.parse_args(argv)

    pending = compute_unmatched_names(limit=args.limit)
    print(f'Total unique names in names_data.json: '
          f'{len(_load_names_data_unique(_NAMES_DATA_JSON)):,}')
    print(f'Already covered by genero-nomes: '
          f'{len(_load_genero_nomes_keys(_GENERO_NOMES_CSV)):,}')
    print(f'Already classified by Gemini (existing JSONL): '
          f'{len(_load_existing_classifications(_GEMINI_JSONL)):,}')
    print(f'Pending classification: {len(pending):,}')
    print(f'Model: {args.model}')
    print(f'Workers: {args.workers}')
    print(f'Output: {args.output.relative_to(_REPO_ROOT)}')

    if not pending:
        print('Nothing to do.')
        return 0

    if args.dry_run:
        print('\n--dry-run: showing first 25 pending names')
        for name in pending[:25]:
            print(f'  {name}')
        if len(pending) > 25:
            print(f'  ... and {len(pending) - 25:,} more')
        return 0

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print(
            'ERROR: GEMINI_API_KEY environment variable is not set.\n'
            'Get one at https://aistudio.google.com/apikey and re-run, e.g.\n'
            '  GEMINI_API_KEY=... python -m scripts.classify_unmatched_names_gemini',
            file=sys.stderr,
        )
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    client = _build_client(api_key)
    write_lock = threading.Lock()

    # Counters are touched from worker threads; the lock protects both the
    # JSONL append and the running tallies.
    counters = {'M': 0, 'F': 0, 'U': 0, 'errors': 0}
    started = time.time()

    def _do(name: str) -> dict:
        row = classify_one(client, name, model=args.model)
        _append_jsonl(args.output, row, write_lock)
        with write_lock:
            counters[row['gender']] = counters.get(row['gender'], 0) + 1
            if 'error' in row:
                counters['errors'] += 1
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(_do, n) for n in pending]
        completed = 0
        report_every = max(1, len(pending) // 50)
        for fut in as_completed(futures):
            try:
                row = fut.result()
            except Exception as err:  # noqa: BLE001 - log + keep going
                print(f'unexpected worker failure: {err}', file=sys.stderr)
                counters['errors'] += 1
                continue
            completed += 1
            if completed % report_every == 0 or completed == len(pending):
                elapsed = time.time() - started
                rate = completed / elapsed if elapsed > 0 else 0.0
                print(
                    f'  [{completed:>5}/{len(pending)}] '
                    f'M={counters["M"]:,} F={counters["F"]:,} U={counters["U"]:,} '
                    f'err={counters["errors"]:,}  '
                    f'rate={rate:.1f} req/s  last={row["name"]}->{row["gender"]}'
                )

    elapsed = time.time() - started
    print('\nDone.')
    print(f'  classified: {sum(counters[k] for k in ("M", "F", "U")):,}')
    print(f'  M: {counters["M"]:,}')
    print(f'  F: {counters["F"]:,}')
    print(f'  U (unknown): {counters["U"]:,}')
    print(f'  errors:     {counters["errors"]:,}')
    print(f'  elapsed:    {elapsed:.1f}s')
    print(f'  output:     {args.output.relative_to(_REPO_ROOT)}')
    print('\nNext step: re-run "python -m scripts.ingest_to_parquet" to fold '
          'the new classifications into parquet/sex_prior/scope=national/ '
          'and the period x sex partitions. The ingester tracks the source '
          '(brasil.io/genero-nomes vs gemini-3.1-flash-lite-preview) in a '
          '"source" column so reviewers can audit which rows are LLM-derived.')
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())

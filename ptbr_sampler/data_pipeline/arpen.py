"""Arpen Transparência 2025 top-50 and birth-count acquisition."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from ptbr_sampler.data_pipeline.http import HttpClient
from ptbr_sampler.data_pipeline.io import atomic_write
from ptbr_sampler.data_pipeline.registry import ARPEN_BASE_URL, STATE_NAMES


def normalise_arpen(payload: dict[str, Any]) -> tuple[list[tuple[str, int]], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('malformed Arpen ranking response')  # noqa: TRY004 - malformed payload is a value error
    rows: list[tuple[str, int]] = []
    for item in payload['data']:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('malformed Arpen ranking row')  # noqa: TRY004
        try:
            count = int(item['total'])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('malformed Arpen ranking total') from error
        if count < 0:
            raise ValueError('negative Arpen count')
        rows.append((item['name'].upper(), count))
    if not rows:
        raise ValueError('empty Arpen ranking')
    return rows, sum(count for _, count in rows)


def validate_births(payload: dict[str, Any], *, expected_ufs: set[str] | None = None) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('malformed Arpen birth response')  # noqa: TRY004
    births: dict[str, int] = {}
    national = 0
    for item in payload['data']:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('malformed Arpen birth row')  # noqa: TRY004
        name = item['name'].upper()
        count = int(item['total'])
        if name in {'BR', 'BRASIL', 'TOTAL'}:
            national = count
        else:
            births[name] = count
    expected = expected_ufs if expected_ufs is not None else set(STATE_NAMES)
    missing = expected - births.keys()
    if missing:
        raise ValueError(f'Arpen birth response missing UFs: {sorted(missing)}')
    if set(births) - expected:
        raise ValueError(f'Arpen birth response has unknown UFs: {sorted(set(births) - expected)}')
    if national and national != sum(births.values()):
        raise ValueError('Arpen national birth total does not reconcile with UFs')
    if payload.get('total') is not None and int(payload['total']) != sum(births.values()):
        raise ValueError('Arpen top-level national birth total does not reconcile with UFs')
    births['BR'] = national or sum(births.values())
    return births


def arpen_url(endpoint: str, uf: str | None = None) -> str:
    url = f'{ARPEN_BASE_URL}/{endpoint}?start_date=2025-01-01&end_date=2025-12-31'
    if endpoint != 'birth':
        url += '&translate=1'
    if uf:
        # This is the filter emitted by the portal's handleStateCityFilter.
        url += f'&state={uf}'
    return url


def fetch_arpen2025(client: HttpClient, cache_dir: Path, *, refresh: bool = False) -> dict[str, Any]:
    """Acquire all national/UF top-50 slices and births, retaining raw JSON responses."""
    raw_path = cache_dir / 'arpen2025' / 'responses.jsonl.gz'
    if raw_path.exists() and not refresh:
        with gzip.open(raw_path, 'rt', encoding='utf-8') as stream:
            records = [json.loads(line) for line in stream]
    else:
        records = []
        requests = [('birth', None)] + [(f'{kind}-name', uf) for kind in ('simple', 'compound', 'all') for uf in [None, *STATE_NAMES]]
        for endpoint, uf in requests:
            response = client.get(arpen_url(endpoint, uf), timeout=45)
            payload = response.json()
            if endpoint == 'birth':
                validate_births(payload)
            else:
                normalise_arpen(payload)
            response_bytes = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
            records.append(
                {
                    'url': response.url,
                    'acquired_at_utc': response.acquired_at_utc,
                    'endpoint': endpoint,
                    'uf': uf or 'BR',
                    'response_sha256': hashlib.sha256(response_bytes).hexdigest(),
                    'response_bytes': len(response_bytes),
                    'payload': payload,
                }
            )
        packed = ('\n'.join(json.dumps(record, ensure_ascii=False, separators=(',', ':')) for record in records) + '\n').encode()
        atomic_write(raw_path, gzip.compress(packed, mtime=0))
    for record in records:
        response_bytes = json.dumps(record['payload'], ensure_ascii=False, separators=(',', ':')).encode()
        record.setdefault('response_sha256', hashlib.sha256(response_bytes).hexdigest())
        record.setdefault('response_bytes', len(response_bytes))
    packed = ('\n'.join(json.dumps(record, ensure_ascii=False, separators=(',', ':')) for record in records) + '\n').encode()
    atomic_write(raw_path, gzip.compress(packed, mtime=0))
    output: dict[str, Any] = {'rankings': {}, 'births': {}, 'responses': len(records)}
    for record in records:
        if record['endpoint'] == 'birth':
            output['births'] = validate_births(record['payload'])
        else:
            rows, total = normalise_arpen(record['payload'])
            kind = record['endpoint'].removesuffix('-name')
            output['rankings'][f'{kind}:{record["uf"]}'] = {
                'rows': rows,
                'top50_total': total,
                'url': record['url'],
                'acquired_at_utc': record['acquired_at_utc'],
            }
    if len(output['rankings']) != 84:
        raise ValueError(f'Arpen ranking coverage mismatch: {len(output["rankings"])} != 84')
    # Detect the previous silent failure mode where a UF query parameter was ignored.
    signatures = {uf: output['rankings'][f'all:{uf}']['rows'] for uf in STATE_NAMES}
    if len({json.dumps(rows) for rows in signatures.values()}) < 2:
        raise ValueError('Arpen UF filter appears to have been ignored: all UF responses are identical')
    return output

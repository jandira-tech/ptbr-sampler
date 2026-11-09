"""Small, atomic and auditable file-writing primitives."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec='seconds')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n').encode())


def file_metadata(
    path: Path, *, url: str, acquired_at_utc: str | None = None, revision: str | None = None, rows: int | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'path': path.name,
        'url': url,
        'acquired_at_utc': acquired_at_utc or utc_now(),
        'bytes': path.stat().st_size,
        'sha256': sha256_file(path),
    }
    if revision:
        result['upstream_revision'] = revision
    if rows is not None:
        result['rows'] = rows
    return result

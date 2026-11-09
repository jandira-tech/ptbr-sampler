"""Synchronous HTTPS transport with bounded retries and resumable atomic writes."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ptbr_sampler.data_pipeline.io import atomic_write, file_metadata, sha256_file, utc_now, write_json
from ptbr_sampler.data_pipeline.registry import Source

USER_AGENT = 'ptbr-sampler-data/0.3 (+https://github.com/jandira-tech/ptbr-sampler)'


class HttpError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HttpResponse:
    url: str
    status: int
    body: bytes
    headers: dict[str, str]
    acquired_at_utc: str

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f'malformed JSON from {self.url}') from error


Transport = Callable[[urllib.request.Request, float], dict[str, Any]]


def urllib_transport(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked by get()
        return {'status': response.status, 'body': response.read(), 'headers': dict(response.headers)}


class HttpClient:
    def __init__(
        self, *, transport: Transport | None = None, retries: int = 3, backoff: float = 0.5, sleeper: Callable[[float], None] = time.sleep
    ):
        self.transport = transport or urllib_transport
        self.retries = retries
        self.backoff = backoff
        self.sleeper = sleeper

    def get(self, url: str, *, timeout: float = 30) -> HttpResponse:
        if not url.startswith('https://'):
            raise ValueError('only HTTPS sources are allowed')
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'})  # noqa: S310
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.transport(request, timeout)
                status = int(response.get('status', 200))
                if status != 200:
                    raise HttpError(f'HTTP {status} from {url}')
                return HttpResponse(url, status, bytes(response['body']), dict(response.get('headers', {})), utc_now())
            except (TimeoutError, OSError, urllib.error.URLError, HttpError) as error:
                last_error = error
                if attempt < self.retries:
                    self.sleeper(self.backoff * (2**attempt))
        raise HttpError(f'{url} failed after {self.retries + 1} attempts: {last_error}') from last_error

    def download(self, source: Source, destination: Path, *, timeout: float = 60, refresh: bool = False) -> dict[str, Any]:
        metadata_path = destination.with_suffix(destination.suffix + '.meta.json')
        if destination.exists() and metadata_path.exists() and not refresh:
            if source.expected_bytes is not None and destination.stat().st_size != source.expected_bytes:
                raise ValueError(f'{source.key}: cached byte count mismatch')
            if source.sha256 and sha256_file(destination) != source.sha256:
                raise ValueError(f'{source.key}: cached checksum mismatch')
            return json.loads(metadata_path.read_text())
        response = self.get(source.url, timeout=timeout)
        if source.expected_bytes is not None and len(response.body) != source.expected_bytes:
            raise ValueError(f'{source.key}: expected {source.expected_bytes} bytes, got {len(response.body)}')
        atomic_write(destination, response.body)
        if source.sha256 and sha256_file(destination) != source.sha256:
            destination.unlink(missing_ok=True)
            raise ValueError(f'{source.key}: checksum mismatch')
        metadata = file_metadata(destination, url=source.url, acquired_at_utc=response.acquired_at_utc, revision=source.upstream_revision)
        metadata.update({'status': response.status, 'response_headers': response.headers})
        write_json(metadata_path, metadata)
        return metadata

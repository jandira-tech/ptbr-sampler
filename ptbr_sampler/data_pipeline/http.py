"""Synchronous HTTPS transport with bounded retries and resumable atomic writes."""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ptbr_sampler.data_pipeline.io import file_metadata, sha256_file, utc_now, write_json
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


def urllib_stream_transport(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - HTTPS checked by caller
    return {'status': response.status, 'headers': dict(response.headers), 'stream': response}


def urllib_transport(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme checked by get()
        return {'status': response.status, 'body': response.read(), 'headers': dict(response.headers)}


class HttpClient:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        stream_transport: Transport | None = None,
        retries: int = 3,
        backoff: float = 0.5,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.transport = transport or urllib_transport
        self.stream_transport = stream_transport or urllib_stream_transport
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
        if not source.url.startswith('https://'):
            raise ValueError('only HTTPS sources are allowed')
        metadata_path = destination.with_suffix(destination.suffix + '.meta.json')
        if destination.exists() and metadata_path.exists() and not refresh:
            if source.expected_bytes is not None and destination.stat().st_size != source.expected_bytes:
                raise ValueError(f'{source.key}: cached byte count mismatch')
            if source.sha256 and sha256_file(destination) != source.sha256:
                raise ValueError(f'{source.key}: cached checksum mismatch')
            return json.loads(metadata_path.read_text())
        part = destination.with_name(destination.name + '.part')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if refresh:
            part.unlink(missing_ok=True)
        resumed_from = part.stat().st_size if part.exists() else 0
        acquired_at = utc_now()
        status = 0
        response_headers: dict[str, str] = {}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            offset = part.stat().st_size if part.exists() else 0
            headers = {'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
            request = urllib.request.Request(source.url, headers=headers)  # noqa: S310 - HTTPS enforced by Source registry
            stream = None
            try:
                response = self.stream_transport(request, timeout)
                status = int(response.get('status', 200))
                response_headers = dict(response.get('headers', {}))
                if status not in {200, 206}:
                    raise HttpError(f'HTTP {status} from {source.url}')
                if offset and status == 206:
                    content_range = response_headers.get('Content-Range', response_headers.get('content-range', ''))
                    if not content_range.startswith(f'bytes {offset}-'):
                        raise HttpError(f'invalid Content-Range for resumed download: {content_range!r}')
                # A 200 response to a Range request means the server ignored it;
                # restart from zero rather than appending a duplicate prefix.
                mode = 'ab' if offset and status == 206 else 'wb'
                stream = response.get('stream', io.BytesIO(bytes(response.get('body', b''))))
                with part.open(mode) as output:
                    while chunk := stream.read(1024 * 1024):
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                acquired_at = utc_now()
                break
            except (TimeoutError, OSError, urllib.error.URLError, HttpError) as error:
                last_error = error
                if attempt < self.retries:
                    self.sleeper(self.backoff * (2**attempt))
            finally:
                if stream is not None:
                    stream.close()
        else:
            raise HttpError(f'{source.url} download failed after {self.retries + 1} attempts: {last_error}') from last_error
        if source.expected_bytes is not None and part.stat().st_size != source.expected_bytes:
            raise ValueError(f'{source.key}: expected {source.expected_bytes} bytes, got {part.stat().st_size}')
        if source.sha256 and sha256_file(part) != source.sha256:
            part.unlink(missing_ok=True)
            raise ValueError(f'{source.key}: checksum mismatch')
        part.replace(destination)
        metadata = file_metadata(destination, url=source.url, acquired_at_utc=acquired_at, revision=source.upstream_revision)
        metadata.update({'status': status, 'response_headers': response_headers, 'resumed_from_bytes': resumed_from})
        write_json(metadata_path, metadata)
        return metadata

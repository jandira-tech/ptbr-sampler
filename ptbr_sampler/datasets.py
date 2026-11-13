"""Runtime Hugging Face dataset resolver, SHA-256 verifier, and revision-addressed cache."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

PACKAGE_DATA_DIR: Path = Path(__file__).resolve().parent / 'data'
MANIFEST_PATH: Path = PACKAGE_DATA_DIR / 'dataset_manifest.json'
DEFAULT_HF_REPO_ID: str = 'arthrod/ptbr-sampler-data'
DEFAULT_HF_BASE_URL: str = 'https://huggingface.co'
USER_AGENT: str = 'ptbr-sampler/0.3.0 (+https://github.com/jandira-tech/ptbr-sampler)'
_ALLOWED_HF_HOST_SUFFIXES: tuple[str, ...] = ('huggingface.co', '.huggingface.co', '.hf.co')
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.Lock] = {}


@dataclass(slots=True, frozen=True)
class ArtifactEntry:
    relpath: str
    sha256: str
    size_bytes: int
    census_years: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class DatasetManifest:
    schema_version: int
    package_version: str
    hf_repo_id: str
    hf_revision: str
    artifacts: dict[str, ArtifactEntry]


def _normalize_relpath(relpath: str | Path) -> str:
    raw = str(relpath).replace('\\', '/').strip()
    while raw.startswith('./'):
        raw = raw[2:]
    if not raw or raw.startswith('/'):
        raise ValueError(f'Invalid dataset relative path: {relpath!r}')
    posix = PurePosixPath(raw)
    if '..' in posix.parts:
        raise ValueError(f'Path traversal rejected in dataset path: {relpath!r}')
    return posix.as_posix()


@lru_cache(maxsize=1)
def load_dataset_manifest() -> DatasetManifest:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            f'Packaged dataset manifest missing at {MANIFEST_PATH}. '
            'Run `python -m scripts.publish_hf_dataset --manifest-only` in a source checkout.'
        )
    raw = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    artifacts: dict[str, ArtifactEntry] = {}
    for rel, meta in raw.get('artifacts', {}).items():
        norm = _normalize_relpath(rel)
        artifacts[norm] = ArtifactEntry(
            relpath=norm,
            sha256=str(meta['sha256']),
            size_bytes=int(meta['size_bytes']),
            census_years=tuple(int(y) for y in meta.get('census_years', (2010, 2022))),
        )
    return DatasetManifest(
        schema_version=int(raw.get('schema_version', 1)),
        package_version=str(raw.get('package_version', '0.3.0')),
        hf_repo_id=os.environ.get('PTBR_SAMPLER_HF_REPO') or str(raw['hf_repo_id']),
        hf_revision=os.environ.get('PTBR_SAMPLER_HF_REVISION') or str(raw['hf_revision']),
        artifacts=artifacts,
    )


def get_cache_root() -> Path:
    override = os.environ.get('PTBR_SAMPLER_CACHE_DIR')
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get('XDG_CACHE_HOME')
    base = Path(xdg).expanduser() if xdg else (Path.home() / '.cache')
    return (base / 'ptbr-sampler').resolve()


def get_revision_cache_dir(manifest: DatasetManifest | None = None) -> Path:
    mf = manifest or load_dataset_manifest()
    safe_rev = ''.join(ch for ch in mf.hf_revision if ch.isalnum() or ch in ('-', '_', '.'))
    if not safe_rev:
        raise ValueError(f'Invalid hf_revision: {mf.hf_revision!r}')
    return get_cache_root() / safe_rev


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def _artifact_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCKS_GUARD:
        tlock = _THREAD_LOCKS.setdefault(lock_path, threading.Lock())
    with tlock:
        if fcntl is None:
            yield
            return
        with lock_path.open('a+b') as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class _CrossOriginSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, allow_loopback_http: bool = False) -> None:
        super().__init__()
        self._allow_loopback_http = allow_loopback_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        parsed_new = urllib.parse.urlsplit(newurl)
        host = (parsed_new.hostname or '').lower()
        if parsed_new.scheme == 'https':
            if not any(host == s.lstrip('.') or (s.startswith('.') and host.endswith(s)) for s in _ALLOWED_HF_HOST_SUFFIXES):
                raise urllib.error.URLError(f'Disallowed redirect host: {host!r}')
        elif self._allow_loopback_http and parsed_new.scheme == 'http' and host in {'127.0.0.1', 'localhost'}:
            pass
        else:
            raise urllib.error.URLError(f'Disallowed redirect URL scheme/host: {newurl!r}')

        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            parsed_orig = urllib.parse.urlsplit(req.full_url)
            if (parsed_orig.scheme, parsed_orig.netloc.lower()) != (parsed_new.scheme, parsed_new.netloc.lower()):
                for hdr_dict in (new_req.headers, new_req.unredirected_hdrs):
                    for key in [k for k in hdr_dict if k.lower() == 'authorization']:
                        del hdr_dict[key]
        return new_req


def _download_url_to_part(
    url: str,
    part_path: Path,
    *,
    allow_loopback_http: bool = False,
    timeout: float = 60.0,
) -> tuple[str, int]:
    headers = {'User-Agent': USER_AGENT}
    token = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
    parsed = urllib.parse.urlsplit(url)
    if token and (parsed.hostname or '').lower() == 'huggingface.co':
        headers['Authorization'] = f'Bearer {token}'

    opener = urllib.request.build_opener(_CrossOriginSafeRedirectHandler(allow_loopback_http=allow_loopback_http))
    req = urllib.request.Request(url, headers=headers)  # noqa: S310 - scheme and host validated by caller & redirect handler
    h = hashlib.sha256()
    total = 0
    part_path.parent.mkdir(parents=True, exist_ok=True)
    with opener.open(req, timeout=timeout) as resp, part_path.open('wb') as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            total += len(chunk)
        out.flush()
        os.fsync(out.fileno())
    return h.hexdigest(), total


def _download_with_retries(
    url: str,
    part_path: Path,
    *,
    allow_loopback_http: bool = False,
    max_attempts: int = 4,
    base_sleep: float = 1.0,
) -> tuple[str, int]:
    for attempt in range(1, max_attempts + 1):
        part_path.unlink(missing_ok=True)
        try:
            return _download_url_to_part(url, part_path, allow_loopback_http=allow_loopback_http)
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_HTTP_CODES or attempt == max_attempts:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_attempts:
                raise
        if base_sleep > 0:
            time.sleep(base_sleep * (2 ** (attempt - 1)))
    raise RuntimeError('unreachable')  # pragma: no cover


def ensure_data_file(relpath: str | Path, *, verify_sha256: bool = False) -> Path:
    """Resolve a runtime dataset file from override dir, local checkout, or verified HF cache."""
    rel = _normalize_relpath(relpath)

    env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
    if env_data_dir:
        override_file = (Path(env_data_dir).expanduser() / rel).resolve()
        if override_file.is_file():
            return override_file

    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1':
        local_file = PACKAGE_DATA_DIR / rel
        if local_file.is_file():
            return local_file

    manifest = load_dataset_manifest()
    if rel not in manifest.artifacts:
        raise FileNotFoundError(f'Dataset artifact {rel!r} is not registered in dataset_manifest.json')
    entry = manifest.artifacts[rel]
    rev_dir = get_revision_cache_dir(manifest)
    cache_file = rev_dir / rel

    if (
        cache_file.is_file()
        and cache_file.stat().st_size == entry.size_bytes
        and (not verify_sha256 or _sha256_file(cache_file) == entry.sha256)
    ):
        return cache_file

    if os.environ.get('PTBR_SAMPLER_OFFLINE') == '1':
        raise RuntimeError(
            f'Dataset artifact {rel!r} is not cached at {cache_file} and PTBR_SAMPLER_OFFLINE=1. '
            'Pre-warm the cache with `ptbr datasets prefetch`.'
        )

    lock_name = rel.replace('/', '__') + '.lock'
    with _artifact_lock(rev_dir / '.locks' / lock_name):
        if cache_file.is_file() and cache_file.stat().st_size == entry.size_bytes and _sha256_file(cache_file) == entry.sha256:
            return cache_file

        base_url = (os.environ.get('PTBR_SAMPLER_HF_BASE_URL') or DEFAULT_HF_BASE_URL).rstrip('/')
        parsed_base = urllib.parse.urlsplit(base_url)
        allow_loopback = parsed_base.scheme == 'http' and (parsed_base.hostname or '') in {'127.0.0.1', 'localhost'}
        if parsed_base.scheme != 'https' and not allow_loopback:
            raise ValueError(f'PTBR_SAMPLER_HF_BASE_URL must use https:// (got {base_url!r})')

        url = f'{base_url}/datasets/{manifest.hf_repo_id}/resolve/{manifest.hf_revision}/{rel}'
        part_path = cache_file.with_name(f'{cache_file.name}.{os.getpid()}.{threading.get_ident()}.part')
        try:
            digest, nbytes = _download_with_retries(url, part_path, allow_loopback_http=allow_loopback)
            if nbytes != entry.size_bytes:
                raise RuntimeError(f'Byte-length mismatch for {rel}: expected {entry.size_bytes}, got {nbytes}')
            if digest != entry.sha256:
                raise RuntimeError(f'SHA-256 mismatch for {rel}: expected {entry.sha256}, got {digest}')
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            part_path.replace(cache_file)
        finally:
            part_path.unlink(missing_ok=True)

    return cache_file


def resolve_bundled_or_custom_path(path: str | Path | None, default_relpath: str) -> Path:
    """Resolve None or default PACKAGE_DATA_DIR paths via ensure_data_file; leave custom user paths untouched."""
    if path is None:
        return ensure_data_file(default_relpath)
    candidate = Path(path)
    if candidate.resolve() == (PACKAGE_DATA_DIR / default_relpath).resolve():
        return ensure_data_file(default_relpath)
    return candidate


def ensure_parquet_root(census_year: int = 2022) -> Path:
    """Return an existing directory root for PartitionSpec construction (local checkout or revision cache)."""
    if census_year not in (2010, 2022):
        raise ValueError(f'census_year must be 2010 or 2022; got {census_year!r}')
    rel_root = 'parquet/census_year=2022' if census_year == 2022 else 'parquet'

    env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
    if env_data_dir:
        candidate = (Path(env_data_dir).expanduser() / rel_root).resolve()
        if (candidate / 'first_names').is_dir():
            return candidate

    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1':
        local_root = PACKAGE_DATA_DIR / rel_root
        if (local_root / 'first_names').is_dir():
            return local_root

    cache_root = get_revision_cache_dir() / rel_root
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def resolve_partition_path(path: Path) -> Path:
    """Lazy PartitionStore resolver: maps logical cache/package paths to ensure_data_file on demand."""
    resolved = path.resolve()
    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and resolved.is_file():
        return resolved

    roots: list[Path] = [PACKAGE_DATA_DIR.resolve(), get_revision_cache_dir().resolve()]
    env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
    if env_data_dir:
        roots.insert(0, Path(env_data_dir).expanduser().resolve())

    for root in roots:
        try:
            rel = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        return ensure_data_file(rel)

    return path


def has_runtime_data_available(*, census_year: int = 2022) -> bool:
    probe = 'parquet/census_year=2022/first_names/scope=national/part.parquet' if census_year == 2022 else 'names_data.json'
    if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and (PACKAGE_DATA_DIR / probe).is_file():
        return True
    if not MANIFEST_PATH.is_file():
        return False
    manifest = load_dataset_manifest()
    if probe in manifest.artifacts and (get_revision_cache_dir(manifest) / probe).is_file():
        return True
    return os.environ.get('PTBR_SAMPLER_OFFLINE') != '1'


def prefetch_datasets(*, census_year: int | None = 2022, verify_sha256: bool = True) -> list[Path]:
    manifest = load_dataset_manifest()
    downloaded: list[Path] = []
    for rel, entry in sorted(manifest.artifacts.items()):
        if census_year is not None and census_year not in entry.census_years:
            continue
        downloaded.append(ensure_data_file(rel, verify_sha256=verify_sha256))
    return downloaded


def dataset_cache_status(*, census_year: int | None = None, verify_sha256: bool = False) -> dict[str, Any]:
    manifest = load_dataset_manifest()
    rev_dir = get_revision_cache_dir(manifest)
    rows: list[dict[str, Any]] = []
    for rel, entry in sorted(manifest.artifacts.items()):
        if census_year is not None and census_year not in entry.census_years:
            continue
        local_file = PACKAGE_DATA_DIR / rel
        cache_file = rev_dir / rel
        if os.environ.get('PTBR_SAMPLER_IGNORE_LOCAL_DATA') != '1' and local_file.is_file():
            state = 'local-checkout'
            valid = not verify_sha256 or _sha256_file(local_file) == entry.sha256
        elif cache_file.is_file() and cache_file.stat().st_size == entry.size_bytes:
            state = 'cached'
            valid = not verify_sha256 or _sha256_file(cache_file) == entry.sha256
        else:
            state = 'remote-hf'
            valid = True
        rows.append(
            {
                'relpath': rel,
                'size_bytes': entry.size_bytes,
                'census_years': list(entry.census_years),
                'state': state,
                'valid': valid,
            }
        )
    return {
        'hf_repo_id': manifest.hf_repo_id,
        'hf_revision': manifest.hf_revision,
        'cache_dir': str(rev_dir),
        'artifacts': rows,
    }


def clear_dataset_cache(*, all_revisions: bool = False) -> int:
    target = get_cache_root() if all_revisions else get_revision_cache_dir()
    if not target.exists():
        return 0
    removed = sum(1 for p in target.rglob('*') if p.is_file())
    shutil.rmtree(target)
    return removed

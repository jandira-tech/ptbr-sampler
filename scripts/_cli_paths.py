"""Shared CLI path-confinement helpers for offline dataset maintenance scripts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
_REPO_ROOT_REAL: str = os.path.realpath(REPO_ROOT)
_TMP_ROOT_REAL: str = os.path.realpath(tempfile.gettempdir())


def resolve_cli_path(raw: str | Path) -> Path:
    """Validate and canonicalize a CLI filesystem path inside the repo or system temp root."""
    raw_str = os.fspath(raw)
    if '\x00' in raw_str:
        raise ValueError('Null byte in CLI path is not allowed')
    if '..' in Path(raw_str).parts:
        raise ValueError(f'Parent-directory traversal ("..") is not allowed in CLI path: {raw_str}')

    resolved = os.path.realpath(raw_str)
    in_repo = resolved == _REPO_ROOT_REAL or resolved.startswith(_REPO_ROOT_REAL + os.sep)
    in_tmp = resolved == _TMP_ROOT_REAL or resolved.startswith(_TMP_ROOT_REAL + os.sep)
    if not (in_repo or in_tmp):
        raise ValueError(f'CLI path must reside inside repository or temp directory: {raw_str}')
    if in_repo and os.path.commonpath([_REPO_ROOT_REAL, resolved]) != _REPO_ROOT_REAL:
        raise ValueError(f'CLI path escapes repository root: {raw_str}')
    if in_tmp and os.path.commonpath([_TMP_ROOT_REAL, resolved]) != _TMP_ROOT_REAL:
        raise ValueError(f'CLI path escapes temp root: {raw_str}')
    return Path(resolved)

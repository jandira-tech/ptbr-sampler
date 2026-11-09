"""Checksum-first inspection of the pinned IBGE SQLite ZIP mirror."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath

from ptbr_sampler.data_pipeline.io import atomic_write, sha256_file


def extract_verified_sqlite(
    archive: Path,
    output: Path,
    *,
    sha256: str,
    zip_bytes: int,
    sqlite_bytes: int,
    sqlite_sha256: str = '',
) -> Path:
    if archive.stat().st_size != zip_bytes:
        raise ValueError(f'archive byte count mismatch: expected {zip_bytes}, got {archive.stat().st_size}')
    if sha256_file(archive) != sha256:
        raise ValueError('archive checksum mismatch')
    if output.exists() and output.stat().st_size == sqlite_bytes and (not sqlite_sha256 or sha256_file(output) == sqlite_sha256):
        return output
    with zipfile.ZipFile(archive) as zipped:
        members = [member for member in zipped.infolist() if not member.is_dir()]
        if len(members) != 1 or members[0].filename != 'nomes.sqlite':
            raise ValueError('archive must contain exactly the nomes.sqlite member')
        member = members[0]
        path = PurePosixPath(member.filename)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('unsafe archive member path')
        if member.file_size != sqlite_bytes:
            raise ValueError(f'SQLite byte count mismatch: expected {sqlite_bytes}, got {member.file_size}')
        with zipped.open(member) as stream:
            digest = hashlib.sha256()
            chunks = []
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
                chunks.append(chunk)
        if sqlite_sha256 and digest.hexdigest() != sqlite_sha256:
            raise ValueError('SQLite checksum mismatch')
        atomic_write(output, b''.join(chunks))
    return output

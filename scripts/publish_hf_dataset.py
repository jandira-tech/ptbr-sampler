"""Build dataset_manifest.json and publish runtime datasets to Hugging Face Hub."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

import ptbr_sampler

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / 'ptbr_sampler' / 'data'
DEFAULT_REPO_ID = 'arthrod/ptbr-sampler-data'
_SHARED_JSON_FILES = frozenset({'cities_with_ceps.json', 'locations_data.json', 'middle_names.json'})
_LEGACY_2010_JSON_FILES = frozenset({'names_data.json', 'surnames_data.json'})
_SAFE_ID_CHAR_MAP: dict[str, str] = {ch: ch for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/'}
_HF_REPO_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$')
_HF_REVISION_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def _validate_hf_repo_id(repo_id: str) -> str:
    if '\x00' in repo_id or '..' in repo_id or not _HF_REPO_ID_RE.fullmatch(repo_id):
        raise ValueError(f'Invalid Hugging Face repo_id: {repo_id!r}')
    return ''.join(_SAFE_ID_CHAR_MAP[ch] for ch in repo_id)


def _validate_hf_revision(revision: str) -> str:
    if '\x00' in revision or '..' in revision or not _HF_REVISION_RE.fullmatch(revision):
        raise ValueError(f'Invalid Hugging Face revision: {revision!r}')
    return ''.join(_SAFE_ID_CHAR_MAP[ch] for ch in revision)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _classify_census_years(relpath: str) -> list[int]:
    if relpath.startswith('parquet/census_year=2022/'):
        return [2022]
    if relpath.startswith(('parquet/middle_names/', 'parquet/states/')) or relpath in _SHARED_JSON_FILES:
        return [2010, 2022]
    if relpath.startswith(('parquet/first_names/', 'parquet/surnames/', 'parquet/sex_prior/')) or relpath in _LEGACY_2010_JSON_FILES:
        return [2010]
    raise ValueError(f'Unclassified runtime artifact: {relpath}')


def collect_runtime_artifacts(data_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    parquet_root = data_dir / 'parquet'
    if parquet_root.is_dir():
        for file_path in sorted(parquet_root.rglob('*')):
            if not file_path.is_file() or file_path.name.startswith('.') or '.bak' in file_path.name:
                continue
            if file_path.suffix == '.parquet':
                meta = pq.read_metadata(file_path)
                if meta.num_rows < 1:
                    raise ValueError(f'Empty Parquet artifact rejected: {file_path}')
            elif file_path.name == 'data_origin.json':
                json.loads(file_path.read_text(encoding='utf-8'))
            else:
                continue
            rel = file_path.relative_to(data_dir).as_posix()
            artifacts[rel] = {
                'sha256': _sha256(file_path),
                'size_bytes': file_path.stat().st_size,
                'census_years': _classify_census_years(rel),
            }

    for json_name in sorted(_SHARED_JSON_FILES | _LEGACY_2010_JSON_FILES):
        json_path = data_dir / json_name
        if not json_path.is_file():
            continue
        json.loads(json_path.read_text(encoding='utf-8'))
        artifacts[json_name] = {
            'sha256': _sha256(json_path),
            'size_bytes': json_path.stat().st_size,
            'census_years': _classify_census_years(json_name),
        }
    return artifacts


def build_dataset_card(repo_id: str, artifacts: dict[str, dict[str, Any]]) -> str:
    total_mib = sum(int(v['size_bytes']) for v in artifacts.values()) / (1024 * 1024)
    return (
        '---\n'
        'license: other\n'
        'language:\n'
        '- pt\n'
        'pretty_name: ptbr-sampler Runtime Demographic & Geographic Tables (Census 2022 & 2010)\n'
        'tags:\n'
        '- brazil\n'
        '- ibge\n'
        '- census-2022\n'
        '- names\n'
        '- demographics\n'
        '---\n\n'
        f'# `{repo_id}`\n\n'
        f'Pinned runtime dataset bundle (`{len(artifacts)}` files, `{total_mib:.2f} MiB`) fetched lazily on demand '
        f'by [`ptbr-sampler`](https://github.com/jandira-tech/ptbr-sampler) `v{ptbr_sampler.__version__}` so the PyPI '
        'wheel stays `< 150 KiB`.\n\n'
        '## Provenance & Attribution\n\n'
        '- **IBGE Censo Demográfico 2022 — Nomes no Brasil** '
        '(disclosure thresholds `< 20` national/cohort, `< 15` UF, `< 10` municipality; IBGE Liv102228).\n'
        '- **Census 2022 Parquet compilation:** Gabriel Lobo '
        '(`olob0/ibge-nomes-no-brasil-2022` @ `05efb85c92af43da2ed4ed088d1e0c9f17160e65`).\n'
        '- **Legacy 2010 Sex Prior:** Álvaro Justen (`brasil.io/genero-nomes`, CC BY-SA 4.0).\n'
        '- **IBGE Geography & Correios CEP ranges:** IBGE Localidades / CNEFE & CEP ranges.\n'
    )


def write_dataset_manifest(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    repo_id: str = DEFAULT_REPO_ID,
    revision: str = 'main',
) -> Path:
    from scripts._cli_paths import resolve_cli_path  # noqa: PLC0415

    safe_data_dir = resolve_cli_path(data_dir)
    safe_repo_id = _validate_hf_repo_id(repo_id)
    safe_revision = _validate_hf_revision(revision)
    artifacts = collect_runtime_artifacts(safe_data_dir)
    manifest = {
        'schema_version': 1,
        'package_version': ptbr_sampler.__version__,
        'hf_repo_id': safe_repo_id,
        'hf_revision': safe_revision,
        'artifacts': artifacts,
    }
    out_path = safe_data_dir / 'dataset_manifest.json'
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return out_path


def publish_to_huggingface(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    repo_id: str = DEFAULT_REPO_ID,
    private: bool = False,
    token: str | None = None,
) -> Path:
    from huggingface_hub import HfApi  # noqa: PLC0415

    from scripts._cli_paths import resolve_cli_path  # noqa: PLC0415

    safe_data_dir = resolve_cli_path(data_dir)
    safe_repo_id = _validate_hf_repo_id(repo_id)
    artifacts = collect_runtime_artifacts(safe_data_dir)
    api = HfApi(token=token or os.environ.get('HF_TOKEN'))
    api.create_repo(repo_id=safe_repo_id, repo_type='dataset', private=private, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='ptbr_hf_stage_') as tmp:
        stage = resolve_cli_path(tmp)
        for rel in artifacts:
            if '..' in Path(rel).parts:
                raise ValueError(f'Invalid artifact relative path: {rel!r}')
            src = safe_data_dir / rel
            dst = resolve_cli_path(stage / rel)
            if os.path.commonpath([str(stage), str(dst)]) != str(stage):
                raise ValueError(f'Artifact destination escapes staging directory: {rel!r}')
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        readme_path = resolve_cli_path(stage / 'README.md')
        if os.path.commonpath([str(stage), str(readme_path)]) != str(stage):
            raise ValueError('Staging README path escaped staging directory')
        with readme_path.open('w', encoding='utf-8') as fh:
            fh.write(build_dataset_card(safe_repo_id, artifacts))

        commit_info = api.upload_folder(
            repo_id=safe_repo_id,
            repo_type='dataset',
            folder_path=str(stage),
            commit_message=f'Publish ptbr-sampler v{ptbr_sampler.__version__} runtime datasets ({len(artifacts)} files)',
        )

    commit_oid = str(commit_info.oid)
    if len(commit_oid) != 40:
        info = api.repo_info(repo_id=safe_repo_id, repo_type='dataset')
        commit_oid = str(info.sha)
    return write_dataset_manifest(safe_data_dir, repo_id=safe_repo_id, revision=_validate_hf_revision(commit_oid))


def main(argv: list[str] | None = None) -> int:
    from scripts._cli_paths import resolve_cli_path  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument('--repo-id', default=os.environ.get('PTBR_SAMPLER_HF_REPO', DEFAULT_REPO_ID))
    parser.add_argument('--revision', default='main', help='Revision written in --manifest-only mode')
    parser.add_argument('--manifest-only', action='store_true', help='Write dataset_manifest.json without uploading')
    parser.add_argument('--publish', action='store_true', help='Upload runtime bundle to Hugging Face and pin commit SHA')
    parser.add_argument('--private', action='store_true', help='Create private HF dataset repo if creating new')
    args = parser.parse_args(argv)

    safe_data_dir = resolve_cli_path(args.data_dir)
    safe_repo_id = _validate_hf_repo_id(args.repo_id)
    if args.publish:
        out = publish_to_huggingface(safe_data_dir, repo_id=safe_repo_id, private=args.private)
        print(f'Published to {safe_repo_id} and pinned manifest: {out}')
    else:
        safe_revision = _validate_hf_revision(args.revision)
        out = write_dataset_manifest(safe_data_dir, repo_id=safe_repo_id, revision=safe_revision)
        print(f'Wrote manifest ({out})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

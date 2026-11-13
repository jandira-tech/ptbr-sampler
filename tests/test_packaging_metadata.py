"""Tests for MIT license, third-party notices, and PyPI packaging metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_license_is_mit_under_jandira_tech() -> None:
    license_text = (REPO_ROOT / 'LICENSE').read_text(encoding='utf-8')
    assert 'MIT License' in license_text
    assert 'Copyright (c) 2026 Jandira Tech' in license_text
    assert 'Permission is hereby granted, free of charge' in license_text
    assert 'All rights reserved' not in license_text


def test_third_party_notices_distinguishes_mit_code_from_data_terms() -> None:
    notices = (REPO_ROOT / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    assert 'MIT License' in notices
    assert 'All rights reserved' not in notices
    assert 'IBGE' in notices
    assert 'olob0/ibge-nomes-no-brasil-2022' in notices
    assert 'CC-BY-SA-4.0' in notices


def test_pyproject_metadata_extras_and_dependency_hygiene() -> None:
    pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    project = pyproject['project']

    assert project['name'] == 'ptbr-sampler'
    assert project['version'] == '0.3.0'
    assert project['license'] == 'MIT'
    assert project['requires-python'] == '>=3.12'
    assert not any(dep.startswith('richer') for dep in project['dependencies'])

    urls = project.get('urls', {})
    for key in ('Homepage', 'Documentation', 'Repository', 'Dataset', 'Issues', 'Changelog'):
        assert key in urls, f'Missing project.urls.{key}'
        assert urls[key].startswith('https://')

    extras = project['optional-dependencies']
    assert 'faker' in extras
    assert any(dep.lower().startswith('faker') for dep in extras['faker'])
    assert any(dep.startswith('uv>=0.13.7') for dep in extras['dev'])

    build_reqs = pyproject['build-system']['requires']
    assert any('uv_build>=0.5,<0.14' in req.replace(' ', '') for req in build_reqs)

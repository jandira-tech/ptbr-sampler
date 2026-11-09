"""Regression tests for publishable package metadata and bundled data."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def load_pyproject():
    with (ROOT / 'pyproject.toml').open('rb') as stream:
        return tomllib.load(stream)


def test_release_metadata_is_pypi_ready():
    config = load_pyproject()
    project = config['project']

    assert project['version'] == '0.3.0'
    assert project['requires-python'] == '>=3.12'
    assert project['readme'] == 'README.md'
    assert project['license'] == 'MIT'
    assert project['license-files'] == ['LICENSE']
    assert project['urls'] == {
        'Homepage': 'https://github.com/jandira-tech/ptbr-sampler',
        'Repository': 'https://github.com/jandira-tech/ptbr-sampler',
        'Issues': 'https://github.com/jandira-tech/ptbr-sampler/issues',
    }

    import ptbr_sampler

    assert ptbr_sampler.__version__ == project['version']


def test_optional_and_development_dependencies_cover_faker_and_notebooks():
    extras = load_pyproject()['project']['optional-dependencies']

    assert any(requirement.startswith('faker>=') for requirement in extras['faker'])
    for dependency in ('ipykernel', 'marimo', 'nbclient', 'nbconvert'):
        assert any(requirement.startswith(f'{dependency}>=') for requirement in extras['dev'])


def test_build_configuration_explicitly_includes_all_bundled_datasets():
    config = load_pyproject()

    assert config['build-system']['requires'] == ['uv_build>=0.13.7,<0.14']
    assert 'ptbr_sampler/data/**' in config['tool']['uv']['build-backend']['source-include']
    requirements = config['project']['dependencies']
    assert not any(requirement.startswith('richer') for requirement in requirements)
    assert any(requirement.startswith('openpyxl>=') for requirement in requirements)
    assert config['project']['scripts']['ptbr-data'] == 'ptbr_sampler.data_pipeline.cli:main'


def test_stale_dataset_backups_are_excluded_without_deleting_sources():
    excluded = set(load_pyproject()['tool']['uv']['build-backend']['source-exclude'])
    expected = {
        'ptbr_sampler/data/locations_data.bak2.json',
        'ptbr_sampler/data/locations_data.json.bak',
        'ptbr_sampler/data/locations_data_old.bak.json',
        'ptbr_sampler/data/locations_data_normalized.json',
    }

    assert excluded == expected
    assert all((ROOT / path).is_file() for path in expected)

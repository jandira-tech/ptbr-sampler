"""Regression tests for publishable package metadata and bundled data."""

from pathlib import Path
import tomllib


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


def test_bundled_dataset_inventory_matches_tracked_files():
    tracked_files = {
        path
        for path in (ROOT / 'ptbr_sampler' / 'data').rglob('*')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}
    }

    assert tracked_files
    assert 'ptbr_sampler/data/**' in load_pyproject()['tool']['uv']['build-backend']['source-include']

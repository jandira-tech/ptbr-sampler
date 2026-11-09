"""Build and exercise the actual distributions, including the Node CEP adapter."""

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.packaging

ROOT = Path(__file__).resolve().parents[1]
PERIODS = ('ate1930', 'ate1940', 'ate1950', 'ate1960', 'ate1970', 'ate1980', 'ate1990', 'ate2000', 'ate2010')
REQUIRED_DATA = {
    'ptbr_sampler/data/cities_with_ceps.json',
    'ptbr_sampler/data/locations_data.json',
    'ptbr_sampler/data/manifest.json',
    'ptbr_sampler/data/middle_names.json',
    'ptbr_sampler/data/names_data.json',
    'ptbr_sampler/data/surnames_data.json',
    'ptbr_sampler/data/raw/gemini_gender/classifications.jsonl',
    'ptbr_sampler/data/raw/genero_nomes/nomes.csv',
    'ptbr_sampler/data/raw/genero_nomes/nomes.csv.gz',
    'ptbr_sampler/data/parquet/middle_names/part.parquet',
    'ptbr_sampler/data/parquet/sex_prior/scope=national/data_origin.json',
    'ptbr_sampler/data/parquet/sex_prior/scope=national/part.parquet',
    'ptbr_sampler/data/parquet/states/part.parquet',
    'ptbr_sampler/data/parquet/surnames/scope=national/part.parquet',
}
REQUIRED_DATA.update(
    f'ptbr_sampler/data/parquet/first_names/period={period}/{leaf}'
    for period in PERIODS
    for leaf in ('part.parquet', 'sex=F/part.parquet', 'sex=F/data_origin.json', 'sex=M/part.parquet', 'sex=M/data_origin.json')
)
# The manifest is an exact, generated inventory of the new live-source
# artifacts, not a glob-based assertion that would silently accept omissions.
REQUIRED_DATA.update(json.loads((ROOT / 'ptbr_sampler/data/manifest.json').read_text())['artifacts'])
STALE_DATA = {
    'ptbr_sampler/data/locations_data.bak2.json',
    'ptbr_sampler/data/locations_data.json.bak',
    'ptbr_sampler/data/locations_data_old.bak.json',
    'ptbr_sampler/data/locations_data_normalized.json',
}
NODE_ROOT = 'ptbr_sampler/utils/node_modules'
VENDORED_LICENSES = {
    f'{NODE_ROOT}/cep-promise/LICENSE',
    f'{NODE_ROOT}/node-fetch/LICENSE.md',
    f'{NODE_ROOT}/tr46/LICENSE.md',
    f'{NODE_ROOT}/unfetch/LICENSE.md',
    f'{NODE_ROOT}/webidl-conversions/LICENSE.md',
    f'{NODE_ROOT}/whatwg-url/LICENSE.txt',
}
VENDORED_RUNTIME = {
    f'{NODE_ROOT}/cep-promise/package.json',
    f'{NODE_ROOT}/cep-promise/dist/cep-promise.min.js',
    f'{NODE_ROOT}/node-fetch/package.json',
    f'{NODE_ROOT}/node-fetch/lib/index.js',
    f'{NODE_ROOT}/tr46/package.json',
    f'{NODE_ROOT}/tr46/index.js',
    f'{NODE_ROOT}/tr46/lib/mappingTable.json',
    f'{NODE_ROOT}/unfetch/package.json',
    f'{NODE_ROOT}/unfetch/dist/unfetch.js',
    f'{NODE_ROOT}/webidl-conversions/package.json',
    f'{NODE_ROOT}/webidl-conversions/lib/index.js',
    f'{NODE_ROOT}/whatwg-url/package.json',
    f'{NODE_ROOT}/whatwg-url/lib/URL.js',
    f'{NODE_ROOT}/whatwg-url/lib/URL-impl.js',
    f'{NODE_ROOT}/whatwg-url/lib/public-api.js',
    f'{NODE_ROOT}/whatwg-url/lib/url-state-machine.js',
    f'{NODE_ROOT}/whatwg-url/lib/utils.js',
}


def dataset_names(names: set[str], *, strip_root: bool = False) -> set[str]:
    if strip_root:
        names = {name.split('/', 1)[1] for name in names if '/' in name}
    return {name for name in names if name.startswith('ptbr_sampler/data/') and not name.endswith('/')}


@pytest.mark.timeout(120)
def test_built_distributions_are_complete_and_self_contained(tmp_path):
    dist = tmp_path / 'dist'
    subprocess.run(
        ['uv', 'build', '--out-dir', str(dist), str(ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist.glob('*.whl'))
    sdist = next(dist.glob('*.tar.gz'))

    with zipfile.ZipFile(wheel) as archive:
        wheel_files = set(archive.namelist())
    assert dataset_names(wheel_files) == REQUIRED_DATA
    assert not dataset_names(wheel_files) & STALE_DATA
    assert VENDORED_LICENSES | VENDORED_RUNTIME <= wheel_files

    with tarfile.open(sdist) as archive:
        sdist_files = {member.name for member in archive.getmembers() if member.isfile()}
    normalized_sdist_files = {name.split('/', 1)[1] for name in sdist_files}
    assert dataset_names(sdist_files, strip_root=True) == REQUIRED_DATA
    assert not dataset_names(sdist_files, strip_root=True) & STALE_DATA
    assert VENDORED_LICENSES | VENDORED_RUNTIME <= normalized_sdist_files

    venv = tmp_path / 'venv'
    subprocess.run(['uv', 'venv', '--python', sys.executable, str(venv)], check=True, capture_output=True)
    python = venv / 'bin' / 'python'
    subprocess.run(
        ['uv', 'pip', 'install', '--python', str(python), f'{wheel}[faker]'],
        check=True,
        capture_output=True,
        text=True,
    )
    smoke = r"""
import asyncio
import json
from pathlib import Path

from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import BrazilianNameSampler
from ptbr_sampler.utils.cep_wrapper import get_cep_data
from ptbr_sampler.faker import PTBRProvider, install_ptbr
from faker import Faker
import ptbr_sampler


def seeded_faker_profile():
    fake = Faker('pt_BR')
    install_ptbr(fake, uf='SP')
    assert isinstance(fake.providers[0], PTBRProvider)
    fake.seed_instance(827)
    return fake.ptbr_profile()


assert seeded_faker_profile() == seeded_faker_profile()
package = Path(ptbr_sampler.__file__).parent
data = package / 'data'
names = json.loads((data / 'names_data.json').read_text())
surnames = json.loads((data / 'surnames_data.json').read_text())
name_sampler = BrazilianNameSampler({'surnames': surnames['surnames'], **names}, data / 'middle_names.json', None)
name = name_sampler.get_random_name()
location = BrazilianLocationSampler(data / 'cities_with_ceps.json').batch_sample_locations(1)[0]
cep_result = asyncio.run(get_cep_data('000000000'))
assert isinstance(name, str) and name
assert location['city_name'] and location['state_abbr']
assert cep_result['cep'] == '000000000'
assert 'error' in cep_result
assert 'MODULE_NOT_FOUND' not in json.dumps(cep_result)
print(json.dumps({'name': name, 'location': location['city_name'], 'cep': cep_result}, ensure_ascii=False))
"""
    isolated_cwd = tmp_path / 'outside-checkout'
    isolated_cwd.mkdir()
    result = subprocess.run(
        [str(python), '-I', '-c', smoke],
        check=True,
        capture_output=True,
        text=True,
        cwd=isolated_cwd,
        env={**os.environ, 'PYTHONPATH': ''},
        timeout=30,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload['name']
    assert payload['location']
    assert payload['cep']['error'] == 'CEP deve conter exatamente 8 caracteres.'

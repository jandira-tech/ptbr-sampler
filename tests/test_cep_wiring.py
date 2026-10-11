"""The Node-backed CEP lookup must point at files and packages that exist.

The src/ -> ptbr_sampler/ rename (2ac36f0) left the wrapper running
`node src/utils/cep_service.js` from the working directory, and the script
importing a `dist/` build the repository never ships, so every real-data CEP
lookup retried 100 times and returned an error. The sampler tests mock the
lookup away, so nothing caught it.
"""

import json
import re
from pathlib import Path

from ptbr_sampler.utils import cep_wrapper

ROOT = Path(__file__).resolve().parents[1]


def test_node_command_runs_the_service_script_beside_the_wrapper():
    command = cep_wrapper.node_command('01001000')

    assert command[0] == 'node'
    script = Path(command[1])
    assert script.is_absolute()
    assert script.is_file()
    assert script == Path(cep_wrapper.__file__).with_name('cep_service.js')
    assert command[2:] == ['01001000']


def test_service_script_imports_the_declared_cep_promise_package():
    source = cep_wrapper.CEP_SERVICE.read_text(encoding='utf-8')
    specifiers = re.findall(r'^import .+? from ["\']([^"\']+)["\'];?$', source, re.M)
    declared = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['dependencies']

    assert specifiers == ['cep-promise']
    assert 'cep-promise' in declared

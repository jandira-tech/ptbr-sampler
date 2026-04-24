"""Targeted tests for src.sampler internals: caching, parse_result, JSONL I/O."""

import asyncio
import json
from pathlib import Path
from unittest import mock

import pytest

from src import sampler as sampler_module
from src.br_name_class import NameComponents


DATA_DIR = Path(__file__).parent.parent / 'src' / 'data'


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test in this module starts with a pristine JSON cache."""
    sampler_module._json_cache.clear()
    yield
    sampler_module._json_cache.clear()


class TestJsonCache:
    def test_cache_dict_exists(self):
        assert isinstance(sampler_module._json_cache, dict)

    def test_load_caches_by_resolved_path(self, tmp_path: Path):
        f = tmp_path / 'x.json'
        f.write_text(json.dumps({'a': 1}), encoding='utf-8')
        first = sampler_module._load_json_cached(f)
        second = sampler_module._load_json_cached(f)
        # Same in-memory dict (by identity) — no re-parse.
        assert first is second
        key = str(f.resolve())
        assert key in sampler_module._json_cache

    def test_cache_skips_second_disk_read(self, tmp_path: Path):
        f = tmp_path / 'y.json'
        f.write_text(json.dumps([1, 2, 3]), encoding='utf-8')
        original_open = Path.open
        open_counter = {'n': 0}

        def tracking_open(self, *args, **kwargs):
            if str(self) == str(f):
                open_counter['n'] += 1
            return original_open(self, *args, **kwargs)

        with mock.patch.object(Path, 'open', tracking_open):
            sampler_module._load_json_cached(f)
            sampler_module._load_json_cached(f)
        assert open_counter['n'] == 1


class TestParseResult:
    def test_location_string_with_cep(self):
        nc = NameComponents('João', None, 'Silva')
        res = sampler_module.parse_result(
            'São Paulo - 01000-000, São Paulo (SP)', nc, {'cpf': '123'}
        )
        assert res['city'] == 'São Paulo'
        assert res['cep'] == '01000-000'
        assert res['state'] == 'São Paulo'
        assert res['state_abbr'] == 'SP'
        assert res['cpf'] == '123'

    def test_location_without_cep(self):
        nc = NameComponents('Ana', None, 'Costa')
        res = sampler_module.parse_result('Campinas, São Paulo (SP)', nc, {})
        assert res['city'] == 'Campinas'
        assert res['state_abbr'] == 'SP'

    def test_state_info_overrides_location(self):
        res = sampler_module.parse_result(
            'ignored', None, {}, state_info=('Rio de Janeiro', 'RJ', 'Petrópolis')
        )
        assert res['city'] == 'Petrópolis'
        assert res['state_abbr'] == 'RJ'
        assert res['state'] == 'Rio de Janeiro'

    def test_address_data_overrides(self):
        res = sampler_module.parse_result(
            '',
            None,
            {},
            address_data={
                'street': 'Rua A',
                'neighborhood': 'Centro',
                'building_number': '42',
                'city': 'Campinas',
                'state': 'SP',
                'cep': '13000-000',
            },
        )
        assert res['street'] == 'Rua A'
        assert res['neighborhood'] == 'Centro'
        assert res['building_number'] == '42'
        assert res['city'] == 'Campinas'
        assert res['cep'] == '13000-000'

    def test_malformed_location_tolerated(self):
        """The swallowed-ValueError branch should leave location fields empty."""
        nc = NameComponents('', None, '')
        # A location with the wrong shape triggers the except ValueError: pass branch.
        res = sampler_module.parse_result('a, b, c, d', nc, {})
        assert res['state'] == ''

    def test_missing_name_components_safe(self):
        res = sampler_module.parse_result('', None, {'cpf': '1'})
        assert res['name'] == ''
        assert res['cpf'] == '1'

    def test_state_part_without_paren(self):
        """Exercise the 'else' branch when state_part has no '(' — line 92."""
        res = sampler_module.parse_result('Foo, Bar', None, {})
        assert res['city'] == 'Foo'
        assert res['state'] == 'Bar'
        assert res['state_abbr'] == ''


class TestSaveToJsonlFile:
    def test_append_creates_directory(self, tmp_path: Path):
        target = tmp_path / 'sub' / 'nested' / 'out.jsonl'
        asyncio.run(
            sampler_module.save_to_jsonl_file(
                [{'a': 1}, {'b': 2}], str(target), append=False
            )
        )
        assert target.exists()
        lines = target.read_text(encoding='utf-8').strip().splitlines()
        assert [json.loads(x) for x in lines] == [{'a': 1}, {'b': 2}]

    def test_append_preserves_previous(self, tmp_path: Path):
        target = tmp_path / 'append.jsonl'
        target.write_text('{"initial": true}\n', encoding='utf-8')
        asyncio.run(
            sampler_module.save_to_jsonl_file([{'added': 1}], str(target), append=True)
        )
        lines = target.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1]) == {'added': 1}


class TestGetAddressDataBatch:
    def test_offline_generates_address(self, seeded_random):
        ceps = ['01000000', '13000-000']
        results = asyncio.run(
            sampler_module.get_address_data_batch(ceps, make_api_call=False)
        )
        assert len(results) == 2
        for entry in results:
            assert entry['street']
            assert entry['neighborhood']
            assert entry['building_number']
            # First CEP had no dash — must be formatted by the batch helper.
            assert '-' in entry['cep']

    def test_single_wrapper_returns_dict(self, seeded_random):
        result = asyncio.run(
            sampler_module.get_address_data('12345-678', make_api_call=False)
        )
        assert isinstance(result, dict)
        assert result['cep'] == '12345-678'

    def test_single_wrapper_empty_list(self):
        """If the batch ever returned nothing, get_address_data yields {}."""
        with mock.patch.object(
            sampler_module, 'get_address_data_batch',
            new=mock.AsyncMock(return_value=[]),
        ):
            result = asyncio.run(sampler_module.get_address_data('12345678'))
        assert result == {}

    def test_offline_progress_callback_invoked(self, seeded_random):
        events: list[tuple[int, str]] = []
        ceps = [f'0100000{i}' for i in range(10)]
        asyncio.run(
            sampler_module.get_address_data_batch(
                ceps,
                make_api_call=False,
                progress_callback=lambda count, msg: events.append((count, msg)),
            )
        )
        assert events  # at least one update should have been emitted

    def test_api_call_path_with_mocked_wrapper(self, seeded_random):
        """Exercise the make_api_call=True branch with a mocked resolver."""
        fake_response = [
            {
                'cep': '01000-000',
                'state': 'SP',
                'city': 'São Paulo',
                'street': 'Praça da Sé',
                'neighborhood': '',
            },
            {'cep': '13000-000', 'state': 'SP', 'city': 'Campinas', 'error': 'no data'},
        ]
        with mock.patch(
            'src.utils.cep_wrapper.workers_for_multiple_cep',
            new=mock.AsyncMock(return_value=fake_response),
        ):
            results = asyncio.run(
                sampler_module.get_address_data_batch(
                    ['01000-000', '13000-000'],
                    make_api_call=True,
                    progress_callback=lambda count, msg: None,
                )
            )
        assert len(results) == 2
        assert results[0]['street'] == 'Praça da Sé'
        assert results[0]['neighborhood']  # offline fallback populated it
        assert results[1]['street']  # offline fallback for error entry
        assert results[1]['neighborhood']


_DEFAULT_KWARGS_BASE = {
    'qty': 1,
    'q': None,
    'city_only': False,
    'state_abbr_only': False,
    'state_full_only': False,
    'only_cep': False,
    'cep_without_dash': False,
    'make_api_call': False,
    'return_only_name': False,
    'name_raw': False,
    'json_path': DATA_DIR / 'cities_with_ceps.json',
    'names_path': DATA_DIR / 'names_data.json',
    'middle_names_path': DATA_DIR / 'middle_names.json',
    'only_surname': False,
    'top_40': False,
    'with_only_one_surname': False,
    'always_middle': False,
    'only_middle': False,
    'always_cpf': True,
    'always_pis': False,
    'always_cnpj': False,
    'always_cei': False,
    'always_rg': True,
    'always_phone': True,
    'only_cpf': False,
    'only_pis': False,
    'only_cnpj': False,
    'only_cei': False,
    'only_rg': False,
    'only_fone': False,
    'include_issuer': True,
    'only_document': False,
    'surnames_path': DATA_DIR / 'surnames_data.json',
    'locations_path': DATA_DIR / 'locations_data.json',
    'save_to_jsonl': None,
    'all_data': False,
}


def _call_sample(**overrides):
    from src.br_name_class import TimePeriod

    kwargs = {'time_period': TimePeriod.UNTIL_2010, **_DEFAULT_KWARGS_BASE, **overrides}
    return sampler_module.sample(**kwargs)


@pytest.fixture(autouse=True, scope='module')
def _require_real_data():
    for fname in (
        'cities_with_ceps.json', 'names_data.json', 'middle_names.json',
        'surnames_data.json', 'locations_data.json',
    ):
        if not (DATA_DIR / fname).exists():
            pytest.skip(f'Missing data file: {fname}')


class TestSampleBranches:
    def test_progress_callback_full_flow(self, tmp_path):
        events: list[tuple[int, str]] = []
        _call_sample(
            qty=3,
            save_to_jsonl=str(tmp_path / 'out.jsonl'),
            progress_callback=lambda count, msg: events.append((count, msg)),
        )
        assert any('Complete' == m for _, m in events)
        assert any('Preparing address data' == m for _, m in events)

    def test_city_only_format(self):
        result = _call_sample(qty=5, city_only=True)
        assert isinstance(result, list)
        # City-only output is the city name without state info.
        for r in result:
            assert r['city']

    def test_state_abbr_only_format(self):
        result = _call_sample(qty=3, state_abbr_only=True)
        for r in result:
            assert r['state_abbr']

    def test_state_full_only_format(self):
        result = _call_sample(qty=3, state_full_only=True)
        for r in result:
            assert r['state']

    def test_only_cep_format(self):
        result = _call_sample(qty=3, only_cep=True)
        for r in result:
            assert r['cep']

    def test_only_pis_branch(self):
        result = _call_sample(qty=2, only_pis=True, always_cpf=False, always_rg=False, always_phone=False)
        for r in result:
            assert r['pis']

    def test_only_cnpj_branch(self):
        result = _call_sample(qty=2, only_cnpj=True, always_cpf=False, always_rg=False, always_phone=False)
        for r in result:
            assert r['cnpj']

    def test_only_cei_branch(self):
        result = _call_sample(qty=2, only_cei=True, always_cpf=False, always_rg=False, always_phone=False)
        for r in result:
            assert r['cei']

    def test_only_rg_branch(self):
        result = _call_sample(qty=2, only_rg=True, always_cpf=False, always_rg=False, always_phone=False)
        for r in result:
            assert r['rg']

    def test_only_fone_branch(self):
        result = _call_sample(qty=2, only_fone=True, always_cpf=False, always_rg=False, always_phone=False)
        for r in result:
            assert r['phone']

    def test_only_surname(self):
        result = _call_sample(qty=2, only_surname=True)
        for r in result:
            assert r['surnames']

    def test_only_middle(self):
        result = _call_sample(qty=2, only_middle=True, always_cpf=False, always_rg=False, always_phone=False)
        for r in result:
            assert r['middle_name']

    def test_only_document_docs_all(self):
        result = _call_sample(
            qty=2,
            only_document=True,
            always_cpf=True,
            always_pis=True,
            always_cnpj=True,
            always_cei=True,
            always_rg=True,
            always_phone=True,
        )
        for r in result:
            assert r['cpf'] and r['pis'] and r['cnpj'] and r['cei'] and r['rg'] and r['phone']

    def test_locations_path_missing_file_warns(self, capsys):
        # Point locations_path at something that doesn't exist — the sampler
        # prints a warning and continues using the default dataset.
        result = _call_sample(qty=1, locations_path='/nonexistent/locations.json')
        assert isinstance(result, dict)
        captured = capsys.readouterr()
        assert 'Warning: Could not use locations_path data' in captured.out

    def test_save_to_jsonl_single_record(self, tmp_path):
        out = tmp_path / 'single.jsonl'
        _call_sample(qty=1, save_to_jsonl=str(out), append_to_jsonl=False)
        assert out.exists()
        lines = out.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 1

    def test_save_to_jsonl_multiple(self, tmp_path):
        out = tmp_path / 'multi.jsonl'
        _call_sample(qty=4, save_to_jsonl=str(out), append_to_jsonl=False)
        assert len(out.read_text(encoding='utf-8').strip().splitlines()) == 4

    def test_exception_reraised_as_runtime_error(self, tmp_path):
        bad_path = tmp_path / 'empty.json'
        bad_path.write_text('this is not json', encoding='utf-8')
        with pytest.raises(RuntimeError, match='Error generating samples'):
            _call_sample(qty=1, json_path=bad_path)

    def test_all_data_full_profile(self):
        result = _call_sample(qty=1, all_data=True)
        for key in ('cpf', 'pis', 'cnpj', 'cei', 'rg', 'phone'):
            assert result[key]

    def test_api_call_messages(self):
        events: list[tuple[int, str]] = []
        with mock.patch(
            'src.utils.cep_wrapper.workers_for_multiple_cep',
            new=mock.AsyncMock(return_value=[
                {'cep': '01000-000', 'state': 'SP', 'city': 'SP',
                 'street': 'Rua X', 'neighborhood': 'Centro'}
            ] * 2),
        ):
            _call_sample(
                qty=2,
                make_api_call=True,
                progress_callback=lambda count, msg: events.append((count, msg)),
            )
        # The API-only branches emit their own progress strings.
        messages = [m for _, m in events]
        assert 'API calls starting' in messages
        assert 'API calls completed' in messages

    def test_only_document_progress(self):
        events: list[tuple[int, str]] = []
        _call_sample(
            qty=2,
            only_document=True,
            progress_callback=lambda count, msg: events.append((count, msg)),
        )
        assert any(m == 'Generating documents' for _, m in events)

    def test_only_specific_progress(self):
        events: list[tuple[int, str]] = []
        _call_sample(
            qty=2,
            only_cpf=True,
            always_cpf=False,
            always_rg=False,
            always_phone=False,
            progress_callback=lambda count, msg: events.append((count, msg)),
        )
        assert any(m == 'Generating specific documents' for _, m in events)

    def test_return_only_name_progress(self):
        events: list[tuple[int, str]] = []
        _call_sample(
            qty=2,
            return_only_name=True,
            progress_callback=lambda count, msg: events.append((count, msg)),
        )
        assert any(m == 'Generating names' for _, m in events)

    def test_save_to_jsonl_progress(self, tmp_path):
        events: list[tuple[int, str]] = []
        _call_sample(
            qty=1,
            save_to_jsonl=str(tmp_path / 'e.jsonl'),
            progress_callback=lambda count, msg: events.append((count, msg)),
        )
        assert any(m == 'Saving to JSONL file' for _, m in events)

    def test_return_only_name_with_all_documents(self):
        """Exercise the always_pis/always_cnpj/always_cei branches within the name-only path."""
        result = _call_sample(
            qty=1,
            return_only_name=True,
            always_pis=True,
            always_cnpj=True,
            always_cei=True,
        )
        assert result['pis']
        assert result['cnpj']
        assert result['cei']

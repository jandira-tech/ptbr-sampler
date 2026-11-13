"""Tests for injected random.Random streams, fixed UF filtering, and async/thread safety."""

from __future__ import annotations

import random
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from typer.testing import CliRunner

import ptbr_sampler
from ptbr_sampler import BrazilianLocationSampler, BrazilianNameSampler, TimePeriod, app, sample
from ptbr_sampler.br_rg_class import BrazilianRG
from ptbr_sampler.datasets import ensure_data_file
from ptbr_sampler.document_sampler import DocumentSampler
from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore
from ptbr_sampler.utils.address_for_offline import AddressProvider_for_offline
from ptbr_sampler.utils.cei import random_cei, validate_cei
from ptbr_sampler.utils.cnpj import random_cnpj, validate_cnpj
from ptbr_sampler.utils.cpf import random_cpf, validate_cpf
from ptbr_sampler.utils.phone import generate_phone_number
from ptbr_sampler.utils.pis import random_pis, validate_pis


def _numpy_state_bytes() -> tuple:
    state = np.random.get_state()
    return (state[0], state[1].tobytes(), state[2], state[3], state[4])


def _assert_global_rngs_untouched(py_state: tuple, np_state: tuple) -> None:
    assert random.getstate() == py_state
    assert _numpy_state_bytes() == np_state


@pytest.mark.parametrize('random_mode', [False, True])
def test_injected_profile_is_repeatable_without_mutating_global_rngs(random_mode: bool) -> None:
    random.seed(9999)
    np.random.seed(8888)
    py_before = random.getstate()
    np_before = _numpy_state_bytes()

    out_a = sample(q=1, all_data=True, random=random_mode, rng=random.Random(123456))
    _assert_global_rngs_untouched(py_before, np_before)

    out_b = sample(q=1, all_data=True, random=random_mode, rng=random.Random(123456))
    _assert_global_rngs_untouched(py_before, np_before)

    assert out_a == out_b
    assert isinstance(out_a, dict)
    assert out_a['name']
    assert out_a['cpf']
    assert out_a['pis']
    assert out_a['cnpj']
    assert out_a['cei']


def test_injected_batches_are_repeatable_and_isolated_between_streams() -> None:
    solo_a = [sample(q=3, rng=random.Random(101)), sample(q=2, rng=random.Random(101))]
    del solo_a  # sanity warm-up of caches

    stream_a1 = random.Random(2026)
    stream_b1 = random.Random(7777)
    batch_a_solo = [sample(q=4, uf_conditioning=True, rng=stream_a1), sample(q=3, uf_conditioning=True, rng=stream_a1)]
    batch_b_solo = [sample(q=2, sex_conditioning='F', rng=stream_b1), sample(q=2, sex_conditioning='M', rng=stream_b1)]

    stream_a2 = random.Random(2026)
    stream_b2 = random.Random(7777)
    a_first = sample(q=4, uf_conditioning=True, rng=stream_a2)
    b_first = sample(q=2, sex_conditioning='F', rng=stream_b2)
    a_second = sample(q=3, uf_conditioning=True, rng=stream_a2)
    b_second = sample(q=2, sex_conditioning='M', rng=stream_b2)

    assert [a_first, a_second] == batch_a_solo
    assert [b_first, b_second] == batch_b_solo


@pytest.mark.parametrize(
    'options',
    [
        {'uf': 'SP'},
        {'uf': 'BA', 'sex_conditioning': 'F', 'conditioning_mode': 'estimated'},
        {'time_period': TimePeriod.PERIOD_2020_2022},
        {'census_year': 2010, 'time_period': TimePeriod.UNTIL_1990},
    ],
)
def test_injected_fixed_uf_and_conditioning_modes_are_repeatable(options: dict) -> None:
    first = sample(q=5, rng=random.Random(4242), **options)
    second = sample(q=5, rng=random.Random(4242), **options)
    assert first == second


def test_fixed_uf_filters_locations_and_validates_strict_vs_estimated() -> None:
    sp_rows = sample(q=12, uf='sp', rng=random.Random(314))
    assert len(sp_rows) == 12
    assert all(row['state_abbr'] == 'SP' for row in sp_rows)
    assert all(row['state'] == 'São Paulo' for row in sp_rows)
    assert all('SSP-SP' in row['rg'] for row in sp_rows)

    # Subsequent unconditioned call must still draw across Brazil (no cache mutation)
    national_rows = sample(q=40, rng=random.Random(2718))
    assert len({row['state_abbr'] for row in national_rows}) > 5

    with pytest.raises(ValueError, match='Unknown UF'):
        sample(q=1, uf='XX', rng=random.Random(1))

    with pytest.raises(ValueError, match='conditioning_mode'):
        sample(q=1, uf='SP', sex_conditioning='F', conditioning_mode='strict', rng=random.Random(1))


def test_cli_supports_fixed_uf_option() -> None:
    runner = CliRunner()
    res = runner.invoke(app, ['generate', '-q', '3', '--uf', 'RJ', '--format', 'json'])
    assert res.exit_code == 0, res.output
    import json

    payload = json.loads(res.stdout)
    assert len(payload) == 3
    assert all(item['state_abbr'] == 'RJ' for item in payload)
    assert all('DETRAN-RJ' in item['rg'] for item in payload)


def test_injected_zero_single_and_negative_quantities() -> None:
    rng = random.Random(555)
    before = rng.getstate()
    empty = sample(q=0, rng=rng)
    assert empty == []
    assert rng.getstate() == before

    one = sample(q=1, rng=random.Random(555))
    assert isinstance(one, dict)

    with pytest.raises(ValueError, match='>= 0'):
        sample(q=-1, rng=random.Random(555))


def test_legacy_global_random_seed_reproducibility_is_preserved() -> None:
    random.seed(202611)
    first = sample(q=4, all_data=True)
    random.seed(202611)
    second = sample(q=4, all_data=True)
    assert first == second


def test_low_level_document_phone_rg_and_address_accept_injected_rng() -> None:
    py_before = random.getstate()

    def draw_bundle(seed: int, formatted: bool) -> dict[str, str]:
        r = random.Random(seed)
        ds = DocumentSampler()
        ap = AddressProvider_for_offline(rng=r)
        return {
            'cpf_u': random_cpf(formatted=formatted, rng=r),
            'cnpj_u': random_cnpj(formatted=formatted, rng=r),
            'pis_u': random_pis(formatted=formatted, rng=r),
            'cei_u': random_cei(formatted=formatted, rng=r),
            'cpf_d': ds.generate_cpf(formatted=formatted, rng=r),
            'cnpj_d': ds.generate_cnpj(formatted=formatted, rng=r),
            'pis_d': ds.generate_pis(formatted=formatted, rng=r),
            'cei_d': ds.generate_cei(formatted=formatted, rng=r),
            'rg_rj': ds.generate_rg(state='RJ', include_issuer=True, formatted=formatted, rng=r),
            'rg_mg': BrazilianRG(state='MG', include_issuer=True).generate(rng=r),
            'phone': generate_phone_number(ddd='21', rng=r),
            'street': f'{ap.street_prefix()} {ap.last_name()}',
            'bairro': ap.bairro(),
            'num': ap.building_number(),
        }

    fmt_1 = draw_bundle(909, True)
    fmt_2 = draw_bundle(909, True)
    raw_1 = draw_bundle(909, False)
    raw_2 = draw_bundle(909, False)

    assert random.getstate() == py_before
    assert fmt_1 == fmt_2
    assert raw_1 == raw_2

    assert validate_cpf(fmt_1['cpf_d']) and validate_cpf(raw_1['cpf_d'])
    assert validate_cnpj(fmt_1['cnpj_d']) and validate_cnpj(raw_1['cnpj_d'])
    assert validate_pis(fmt_1['pis_d']) and validate_pis(raw_1['pis_d'])
    assert validate_cei(fmt_1['cei_d']) and validate_cei(raw_1['cei_d'])
    assert '.' in fmt_1['cpf_d'] and fmt_1['cpf_d'].replace('.', '').replace('-', '') == raw_1['cpf_d']
    assert 'DETRAN-RJ' in fmt_1['rg_rj']
    assert raw_1['rg_rj'].isdigit()
    assert fmt_1['phone'].startswith('(21) ')


def test_name_and_location_samplers_accept_injected_rng_directly() -> None:
    loc_sampler = BrazilianLocationSampler(ensure_data_file('cities_with_ceps.json'))
    name_sampler = BrazilianNameSampler.from_parquet(census_year=2022)

    py_before = random.getstate()
    np_before = _numpy_state_bytes()

    loc_a = loc_sampler.batch_sample_locations(6, uf='PE', rng=random.Random(77))
    loc_b = loc_sampler.batch_sample_locations(6, uf='PE', rng=random.Random(77))
    names_a = name_sampler.batch_sample_names(6, ufs=['PE'] * 6, rng=random.Random(88))
    names_b = name_sampler.batch_sample_names(6, ufs=['PE'] * 6, rng=random.Random(88))
    single_a = name_sampler.get_random_name(uf='PE', rng=random.Random(99))
    single_b = name_sampler.get_random_name(uf='PE', rng=random.Random(99))
    sur_a = name_sampler.get_random_surname(uf='PE', rng=random.Random(111))
    sur_b = name_sampler.get_random_surname(uf='PE', rng=random.Random(111))

    _assert_global_rngs_untouched(py_before, np_before)
    assert loc_a == loc_b
    assert all(item['state_abbr'] == 'PE' for item in loc_a)
    assert names_a == names_b
    assert single_a == single_b
    assert sur_a == sur_b


@pytest.mark.asyncio
async def test_offline_sample_runs_inside_active_event_loop_and_online_fails_cleanly() -> None:
    out = sample(q=3, uf='MG', rng=random.Random(17))
    assert len(out) == 3
    assert all(r['state_abbr'] == 'MG' for r in out)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with pytest.raises(RuntimeError, match='running event loop'):
            sample(q=1, make_api_call=True, rng=random.Random(17))
    unawaited = [w for w in caught if 'never awaited' in str(w.message)]
    assert unawaited == []


def test_concurrent_threads_and_partition_store_are_thread_safe(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    random.seed(4444)
    np.random.seed(5555)
    py_before = random.getstate()
    np_before = _numpy_state_bytes()

    ufs = ['SP', 'RJ', 'MG', 'BA', 'RS', 'PR', 'PE', 'CE']

    def worker(idx: int) -> dict:
        return sample(q=1, uf=ufs[idx % len(ufs)], rng=random.Random(10_000 + idx))

    with ThreadPoolExecutor(max_workers=6) as pool:
        parallel_results = list(pool.map(worker, range(24)))

    serial_results = [worker(i) for i in range(24)]
    assert parallel_results == serial_results
    _assert_global_rngs_untouched(py_before, np_before)

    # PartitionStore concurrent cache miss loads underlying _load only once under lock
    store = PartitionStore(max_entries=1)
    load_count = 0
    barrier = threading.Barrier(4)
    spec = PartitionSpec.of(tmp_path / 'first_names', scope='national')
    dummy_table = AliasTable.from_counts(['ANA', 'JOAO'], [60, 40])

    def fake_load(requested: PartitionSpec) -> AliasTable:
        nonlocal load_count
        load_count += 1
        return dummy_table

    monkeypatch.setattr(store, '_load', fake_load)

    def get_from_store(_: int) -> AliasTable:
        barrier.wait()
        return store.get(spec)

    with ThreadPoolExecutor(max_workers=4) as pool:
        tables = list(pool.map(get_from_store, range(4)))

    assert all(t is dummy_table for t in tables)
    assert load_count == 1
    assert ptbr_sampler.__version__ == '0.3.0'

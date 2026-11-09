"""Injected RNG reproducibility and high-level sampler resource reuse."""

import copy
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from ptbr_sampler.br_name_class import Cohort, TimePeriod
from ptbr_sampler.document_sampler import DocumentSampler
from sample import sample


@pytest.fixture(autouse=True)
def _clean_high_level_caches():
    import ptbr_sampler.sampler as sampler_module

    sampler_module._sampler_cache.clear()
    sampler_module._json_cache.clear()
    yield
    sampler_module._sampler_cache.clear()
    sampler_module._json_cache.clear()


def _numpy_state():
    state = np.random.get_state()
    return state[0], state[1].copy(), state[2], state[3], state[4]


def _assert_global_states_unchanged(python_state, numpy_state):
    assert random.getstate() == python_state
    current = np.random.get_state()
    assert current[0] == numpy_state[0]
    np.testing.assert_array_equal(current[1], numpy_state[1])
    assert current[2:] == numpy_state[2:]


@pytest.mark.parametrize('random_mode', [False, True])
def test_injected_complete_profile_is_repeatable_without_touching_global_rngs(random_mode):
    python_state = random.getstate()
    numpy_state = _numpy_state()

    first = sample(q=1, all_data=True, random=random_mode, rng=random.Random(8128))
    second = sample(q=1, all_data=True, random=random_mode, rng=random.Random(8128))

    assert first == second
    assert all(first[field] for field in ('cpf', 'rg', 'pis', 'cnpj', 'cei', 'phone', 'street'))
    _assert_global_states_unchanged(python_state, numpy_state)


def test_injected_batches_are_repeatable_and_independent_between_streams():
    first = sample(q=4, all_data=True, uf='SP', rng=random.Random(10))
    other = sample(q=4, all_data=True, uf='SP', rng=random.Random(11))
    repeated = sample(q=4, all_data=True, uf='SP', rng=random.Random(10))

    assert first == repeated
    assert first != other

    stream_a = random.Random(21)
    stream_b = random.Random(22)
    a1 = sample(q=2, rng=stream_a)
    b1 = sample(q=2, rng=stream_b)
    a2 = sample(q=2, rng=stream_a)
    replay = random.Random(21)
    assert a1 == sample(q=2, rng=replay)
    assert a2 == sample(q=2, rng=replay)
    assert b1 == sample(q=2, rng=random.Random(22))


@pytest.mark.parametrize(
    'options',
    [
        {},
        {'cohort': Cohort.CENSUS2022, 'sex_conditioning': 'F'},
        {'cohort': Cohort.NEWBORN2025, 'sex_conditioning': 'mixed'},
        {'time_period': TimePeriod.UNTIL_1950, 'sex_conditioning': 'M'},
    ],
)
def test_injected_fixed_uf_cohort_and_history_are_repeatable(options):
    kwargs = {'q': 2, 'uf': 'RJ', **options}
    assert sample(rng=random.Random(1977), **kwargs) == sample(rng=random.Random(1977), **kwargs)


@pytest.mark.parametrize('q', [0, 1])
def test_injected_zero_and_single_draws(q):
    result = sample(q=q, rng=random.Random(4))
    if q == 0:
        assert result == []
    else:
        assert isinstance(result, dict)


def test_default_random_seed_reproducibility_is_preserved():
    random.seed(928)
    first = sample(q=2, all_data=True)
    random.seed(928)
    second = sample(q=2, all_data=True)
    assert first == second


def test_document_sampler_supports_injected_rng_and_all_formats():
    def draw(seed, formatted):
        docs = DocumentSampler()
        rng = random.Random(seed)
        return (
            docs.generate_cpf(formatted, rng=rng),
            docs.generate_pis(formatted, rng=rng),
            docs.generate_cnpj(formatted, rng=rng),
            docs.generate_cei(formatted, rng=rng),
            docs.generate_rg('MG', include_issuer=True, rng=rng),
        )

    python_state = random.getstate()
    assert draw(33, True) == draw(33, True)
    assert draw(33, False) == draw(33, False)
    assert random.getstate() == python_state


@pytest.mark.parametrize('fork', ['only_surname', 'only_middle'])
def test_surname_and_middle_forks_do_not_consume_mixed_sex_draws(fork):
    common = {'q': 3, fork: True, 'return_only_name': True}
    without_flag = sample(rng=random.Random(51), **common)
    with_flag = sample(rng=random.Random(51), experimental_uf_sex_conditioning=True, **common)
    assert with_flag == without_flag


@pytest.mark.parametrize(
    'options',
    [
        {'only_surname': True, 'return_only_name': True},
        {'only_middle': True, 'return_only_name': True},
        {'only_cpf': True},
        {'only_document': True},
    ],
)
def test_explicit_mixed_sex_does_not_advance_non_name_branches(options):
    without_sex = sample(q=2, rng=random.Random(612), **options)
    with_sex = sample(q=2, rng=random.Random(612), sex_conditioning='mixed', **options)
    assert with_sex == without_sex
    legacy = sample(q=2, rng=random.Random(612), experimental_uf_sex_conditioning=True, **options)
    assert legacy == without_sex


def test_high_level_calls_reuse_samplers_partition_store_and_aliases(monkeypatch):
    import ptbr_sampler.sampler as sampler_module
    from ptbr_sampler.sampling.store import PartitionStore

    sampler_module._sampler_cache.clear()
    sampler_module._json_cache.clear()
    constructors = {'name': 0, 'location': 0}
    original_name_init = sampler_module.BrazilianNameSampler.__init__
    original_location_init = sampler_module.BrazilianLocationSampler.__init__

    def name_init(self, *args, **kwargs):
        constructors['name'] += 1
        original_name_init(self, *args, **kwargs)

    def location_init(self, *args, **kwargs):
        constructors['location'] += 1
        original_location_init(self, *args, **kwargs)

    loads = []
    original_load = PartitionStore._load

    def load(self, spec):
        loads.append(spec)
        return original_load(self, spec)

    monkeypatch.setattr(sampler_module.BrazilianNameSampler, '__init__', name_init)
    monkeypatch.setattr(sampler_module.BrazilianLocationSampler, '__init__', location_init)
    monkeypatch.setattr(PartitionStore, '_load', load)

    first = sample(q=1, rng=random.Random(77))
    loads_after_first = len(loads)
    second = sample(q=1, rng=random.Random(78))

    assert constructors == {'name': 1, 'location': 1}
    assert loads_after_first > 0
    assert len(loads) == loads_after_first
    assert first != second

    # Every resolved JSON path, Parquet root and alias LRU size participates.
    sample(q=1, rng=random.Random(79), lru_size=17)
    assert constructors == {'name': 2, 'location': 2}
    assert len(sampler_module._sampler_cache) == 2
    data_dir = Path(__file__).parent.parent / 'ptbr_sampler' / 'data'
    default_key, resized_key = sampler_module._sampler_cache
    assert default_key == (
        str((data_dir / 'cities_with_ceps.json').resolve()),
        str((data_dir / 'locations_data.json').resolve()),
        str((data_dir / 'surnames_data.json').resolve()),
        str((data_dir / 'names_data.json').resolve()),
        str((data_dir / 'middle_names.json').resolve()),
        str((data_dir / 'parquet').resolve()),
        32,
        None,
    )
    assert resized_key[:6] == default_key[:6]
    assert resized_key[6:] == (17, None)


def test_cached_location_data_is_not_mutated_by_fixed_uf():
    import ptbr_sampler.sampler as sampler_module

    sampler_module._sampler_cache.clear()
    sampler_module._json_cache.clear()
    data_path = Path(__file__).parent.parent / 'ptbr_sampler' / 'data' / 'cities_with_ceps.json'
    before = copy.deepcopy(sampler_module._load_json_cached(data_path))
    sample(q=1, uf='SP', rng=random.Random(1))
    assert sampler_module._load_json_cached(data_path) == before


def test_real_multi_cohort_aliases_obey_global_sampler_lru():
    from ptbr_sampler.br_name_class import BrazilianNameSampler

    sampler = BrazilianNameSampler.from_bundled_parquet(lru_size=1)
    for cohort in (Cohort.CURRENT, Cohort.CENSUS2022, Cohort.NEWBORN2025, Cohort.CURRENT):
        for uf in ('SP', 'RJ'):
            sampler.batch_sample_names(1, cohort=cohort, ufs=[uf], top_40=True)
            total_aliases = len(sampler._alias_cache)

            assert len(sampler._partition_store) <= 1
            assert total_aliases <= 1


def test_concurrent_lru_one_calls_are_race_free_and_preserve_global_rngs():
    python_state = random.getstate()
    numpy_state = _numpy_state()

    def draw(index):
        return sample(q=1, uf=('SP', 'RJ', 'MG')[index % 3], lru_size=1, rng=random.Random(1000 + index))

    expected = [draw(index) for index in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(draw, range(24)))

    assert actual == expected
    _assert_global_states_unchanged(python_state, numpy_state)


def test_partition_store_concurrent_miss_loads_only_once(monkeypatch):
    from ptbr_sampler.sampling.alias import AliasTable
    from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore

    store = PartitionStore(max_entries=1)
    spec = PartitionSpec.of('/unused', cohort='current')
    table = AliasTable.from_weights(['only'], [1.0])
    barrier = threading.Barrier(8)
    loads = []
    load_lock = threading.Lock()

    release = threading.Event()

    def load(requested):
        with load_lock:
            loads.append(requested.key())
        release.wait(timeout=0.02)
        return table

    def concurrent_get(_):
        barrier.wait(timeout=10)
        return store.get(spec)

    monkeypatch.setattr(store, '_load', load)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(concurrent_get, index) for index in range(8)]
        release.set()
        results = [future.result(timeout=10) for future in futures]

    assert results == [table] * 8
    assert loads == [spec.key()]
    assert len(store) == 1

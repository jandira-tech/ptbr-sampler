"""Public cohort, period, UF, sex, top40, and uniform-selection contracts."""

import inspect
from pathlib import Path

import numpy as np
import pytest

from ptbr_sampler import BrazilianNameSampler, Cohort, TimePeriod
from ptbr_sampler.sampling.alias import AliasTable

DATA = Path(__file__).resolve().parents[1] / 'ptbr_sampler' / 'data'


def bundled() -> BrazilianNameSampler:
    return BrazilianNameSampler.from_bundled_parquet()


def test_public_enums_and_default_cohort_selector():
    assert [item.value for item in Cohort] == ['current', 'census2022', 'newborn2025']
    assert TimePeriod.UNTIL_2020.value == 'ate2020'
    assert TimePeriod.AFTER_2010.value == 'after2010'
    assert len(TimePeriod) == 11
    assert inspect.signature(BrazilianNameSampler.get_random_name).parameters['time_period'].default is None
    assert inspect.signature(BrazilianNameSampler.get_random_name).parameters['cohort'].default is Cohort.CURRENT


def test_default_and_cohorts_use_precomputed_national_marginals():
    sampler = bundled()
    default_table = sampler._first_names_table(cohort=Cohort.CURRENT)
    current_table = sampler._first_names_table(cohort=Cohort.CURRENT)
    census_table = sampler._first_names_table(cohort=Cohort.CENSUS2022)
    newborn_table = sampler._first_names_table(cohort=Cohort.NEWBORN2025)
    assert default_table is current_table
    assert len(census_table) > 50_000  # population-weighted union of UF support
    assert len(newborn_table) > 50
    assert len(current_table) >= len(census_table)


def test_uf_conditioning_does_not_require_experimental_flag_or_sex():
    sampler = bundled()
    sp = sampler._first_names_table(uf='SP')
    ac = sampler._first_names_table(uf='AC')
    assert set(map(str, sp.labels)) != set(map(str, ac.labels))


def test_noncurrent_cohort_with_explicit_period_is_rejected():
    sampler = bundled()
    for cohort in (Cohort.CENSUS2022, Cohort.NEWBORN2025):
        with pytest.raises(ValueError, match='cohort.*time_period|time_period.*cohort'):
            sampler.get_random_name(cohort=cohort, time_period=TimePeriod.UNTIL_2010)
    assert sampler.get_random_name(cohort=Cohort.CURRENT, time_period=TimePeriod.UNTIL_2010)


@pytest.mark.parametrize('period, directory', [(TimePeriod.UNTIL_2020, 'until2020'), (TimePeriod.AFTER_2010, 'after2010')])
def test_explicit_period_uses_ibge_history_without_cohort_blend(period, directory):
    sampler = bundled()
    table = sampler._first_names_table(time_period=period)
    expected = sampler._partition_store.get(
        __import__('ptbr_sampler.sampling.store', fromlist=['PartitionSpec']).PartitionSpec.of(
            DATA / 'parquet/ibge2022/historical', period=directory
        )
    )
    assert set(map(str, table.labels)) == set(map(str, expected.labels))


def test_modern_missing_partition_fails_instead_of_stale_json(tmp_path):
    sampler = bundled()
    sampler.parquet_root = tmp_path
    with pytest.raises(FileNotFoundError, match='cohort=current'):
        sampler._first_names_table()


def test_json_only_fixture_retains_legacy_fallback(mock_name_data):
    sampler = BrazilianNameSampler(mock_name_data)
    table = sampler._first_names_table(time_period=TimePeriod.UNTIL_2010, uf='SP', sex='F')
    assert set(map(str, table.labels)) == {'Maria', 'João', 'Ana', 'Pedro'}
    assert set(map(str, sampler._top_40_table(uf='SP').labels)) == {'Silva', 'Santos'}


def test_bundled_root_missing_fails_instead_of_json_fallback(tmp_path, monkeypatch):
    import ptbr_sampler.br_name_class as names

    monkeypatch.setattr(names, '_DEFAULT_PARQUET_ROOT', tmp_path / 'absent')
    with pytest.raises(FileNotFoundError, match='parquet'):
        names.BrazilianNameSampler.from_bundled_parquet()


def test_sex_conditioned_tables_drop_null_sex_and_renormalize():
    sampler = bundled()
    unconditioned = sampler._first_names_table(uf='SP')
    female = sampler._first_names_table(uf='SP', sex='F')
    assert len(female) < len(unconditioned)
    assert np.isclose(female.weights.sum(), 1.0)
    assert np.all(np.isfinite(female.weights)) and np.all(female.weights >= 0)


def test_top40_is_derived_from_selected_uf_final_probabilities():
    sampler = bundled()
    full = sampler._surnames_table(uf='SE')
    top = sampler._top_40_table(uf='SE')
    expected = sorted(range(len(full)), key=lambda i: -full.weights[i])[:40]
    assert list(map(str, top.labels)) == [str(full.labels[i]) for i in expected]
    assert np.isclose(top.weights.sum(), 1.0)


def test_top40_stable_ties_and_random_uniform_support(monkeypatch):
    sampler = bundled()
    labels = np.asarray(['a', 'b', 'c'], dtype=object)
    weights = np.asarray([0.5, 0.25, 0.25])
    tied = AliasTable.from_weights(labels, weights)
    monkeypatch.setattr(sampler, '_surnames_table', lambda uf=None: tied)
    # Keep the legacy top40 fixture out of the modern path by requesting UF.
    top = sampler._top_40_table(uf='SP')
    assert list(map(str, top.labels)) == ['a', 'b', 'c']

    calls = []
    monkeypatch.setattr('ptbr_sampler.br_name_class._alias_draw', lambda table, n, rng, *, random_mode: calls.append(random_mode) or table.labels[:n])
    sampler.get_random_surname(uf='SP', with_only_one_surname=True, random_mode=True)
    assert calls == [True]


def test_middle_name_probability_remains_3099():
    sampler = bundled()

    class FixedRng:
        def random(self, n):
            return np.full(n, 0.4)

    assert sampler.middle_names_data['percentage_with_second'] == pytest.approx(30.99, abs=0.01)
    assert sampler._draw_middle_names(1, raw=False, always_middle=False, rng=FixedRng(), random_mode=True) == [None]


def test_high_level_fixed_uf_cohort_and_period_errors():
    from sample import sample

    rows = sample(q=3, uf='ac', cohort=Cohort.NEWBORN2025, sex_conditioning='F')
    assert [row['state_abbr'] for row in rows] == ['AC', 'AC', 'AC']
    assert all(row['name'] for row in rows)
    with pytest.raises(ValueError, match='cohort.*time_period|time_period.*cohort') as error:
        sample(q=1, cohort=Cohort.CENSUS2022, time_period=TimePeriod.UNTIL_2010)
    assert not isinstance(error.value, RuntimeError)
    historical = sample(q=1, time_period=TimePeriod.AFTER_2010)
    assert historical['name']


def test_public_wrapper_forwards_cohort_and_uf(monkeypatch):
    import sample as wrapper

    captured = {}
    monkeypatch.setattr(wrapper, 'sampler_function', lambda **kwargs: captured.update(kwargs) or {'name': 'x'})
    result = wrapper.sample(cohort='newborn2025', uf='SP')
    assert result == {'name': 'x'}
    assert captured['cohort'] == 'newborn2025'
    assert captured['uf'] == 'SP'
    assert captured['time_period'] is None


def test_cli_generate_exposes_cohort_uf_and_new_periods():
    from typer.testing import CliRunner
    from ptbr_sampler.cli import app

    result = CliRunner().invoke(app, ['generate', '--help'])
    assert result.exit_code == 0
    assert '--cohort' in result.stdout
    assert '--uf' in result.stdout

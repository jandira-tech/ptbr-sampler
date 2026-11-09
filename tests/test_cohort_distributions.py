"""Independent formula and committed-artifact tests for first-name cohorts."""

import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ptbr_sampler.data_pipeline.derived import (
    apply_national_sex_prior,
    blend_distributions,
    derive_national_marginal,
    derive_newborn_distribution,
)
from ptbr_sampler.data_pipeline.registry import UF_CODES

DATA = Path(__file__).resolve().parents[1] / 'ptbr_sampler' / 'data'
COHORTS = ('current', 'census2022', 'newborn2025')


def weights(path: Path) -> dict[str, float]:
    return {row['name']: row['weight'] for row in pq.read_table(path, columns=['name', 'weight']).to_pylist()}


def test_newborn_hand_calculated_observed_residual_and_tail_exclusion():
    # births=100; observed HELENA=20 and NOVO=5; residual=.75. Tail before
    # exclusion is {.2 HELENA, .3 LIZ, .5 CAIO}; excluding HELENA leaves
    # LIZ=.3/.8 and CAIO=.5/.8. NOVO is not in the tail and keeps .05.
    result = derive_newborn_distribution(
        {'HELENA': 20, 'NOVO': 5},
        births=100,
        national_post2010={'helena': 0.2, 'liz': 0.3, 'caio': 0.5},
    )
    assert result == pytest.approx({'helena': 0.2, 'novo': 0.05, 'liz': 0.75 * 0.3 / 0.8, 'caio': 0.75 * 0.5 / 0.8})
    assert math.isclose(sum(result.values()), 1.0)


def test_newborn_preserves_zero_mass_tail_labels_without_inventing_probability():
    result = derive_newborn_distribution(
        {'ANA': 5}, births=10, national_post2010={'ana': 0.2, 'liz': 0.8, 'zero-stock-bin': 0.0}
    )
    assert set(result) == {'ana', 'liz', 'zero-stock-bin'}
    assert result['ana'] == pytest.approx(0.5)
    assert result['liz'] == pytest.approx(0.5)
    assert result['zero-stock-bin'] == 0.0


def test_newborn_rejects_compound_rows_and_excess_observed_mass():
    with pytest.raises(ValueError, match='atomic|compound'):
        derive_newborn_distribution({'MARIA CLARA': 1}, births=10, national_post2010={'ana': 1.0})
    with pytest.raises(ValueError, match='observed|residual'):
        derive_newborn_distribution({'ANA': 11}, births=10, national_post2010={'liz': 1.0})


def test_current_hand_calculated_union_blend():
    result = blend_distributions({'a': 0.6, 'b': 0.4}, {'b': 0.5, 'c': 0.5}, alpha=0.25)
    assert result == pytest.approx({'a': 0.45, 'b': 0.425, 'c': 0.125})
    assert math.isclose(sum(result.values()), 1.0)


def test_national_marginal_uses_official_population_not_arpen_or_rows():
    result = derive_national_marginal({'SP': {'a': 1.0}, 'AC': {'a': 0.25, 'b': 0.75}}, {'SP': 100, 'AC': 300})
    assert result == pytest.approx({'a': 0.4375, 'b': 0.5625})


def test_sex_prior_is_national_and_drops_unknown_only_when_conditioned():
    result = apply_national_sex_prior(
        {'maria': 0.5, 'unknown': 0.5},
        {'maria': {'p_male': 0.25, 'p_female': 0.75}},
        'F',
    )
    assert result == {'maria': 1.0}


@pytest.mark.real_data
def test_committed_newborn_support_and_probabilities_follow_source_rows_independently():
    """Rebuild expectations from after2010 + Arpen, not generated newborn data."""
    source_rows = pq.read_table(
        DATA / 'parquet/ibge2022/historical/period=after2010/part.parquet', columns=['name', 'weight']
    ).to_pylist()
    assert len(source_rows) == 61_469
    tail = {row['name']: row['weight'] for row in source_rows}
    tail_total = math.fsum(tail.values())
    assert tail_total == pytest.approx(1.0)
    births = {row['uf']: row['count'] for row in pq.read_table(DATA / 'parquet/arpen2025/births/part.parquet').to_pylist()}
    for uf in UF_CODES:
        observed_rows = pq.read_table(
            DATA / f'parquet/arpen2025/simple/uf={uf}/part.parquet', columns=['name', 'count']
        ).to_pylist()
        observed = {row['name'].casefold(): row['count'] / births[uf] for row in observed_rows}
        residual = 1 - math.fsum(observed.values())
        denominator = math.fsum(weight for name, weight in tail.items() if name not in observed)
        expected = dict(observed)
        for name, weight in tail.items():
            if name not in observed:
                expected[name] = residual * weight / denominator
        actual = weights(DATA / f'parquet/cohorts/cohort=newborn2025/uf={uf}/part.parquet')
        assert set(actual) == set(expected)
        assert len(actual) == 61_469 + len(set(observed) - set(tail))
        for name, expected_weight in expected.items():
            assert actual[name] == pytest.approx(expected_weight, abs=2e-15)
            assert math.isfinite(actual[name]) and actual[name] >= 0
        assert math.fsum(actual.values()) == pytest.approx(1.0)
        sidecar = json.loads((DATA / f'parquet/cohorts/cohort=newborn2025/uf={uf}/data_origin.json').read_text())
        assert sidecar['tail_coverage']['national_after2010_rows'] == 61_469
        assert sidecar['tail_coverage']['modeled_rows_after_top50_exclusion'] == len(tail) - len(set(tail) & set(observed))


@pytest.mark.real_data
def test_committed_cohorts_match_exact_mixture_and_national_marginals():
    root = DATA / 'parquet' / 'cohorts'
    births = {row['uf']: row['count'] for row in pq.read_table(DATA / 'parquet/arpen2025/births/part.parquet').to_pylist()}
    locations = json.loads((DATA / 'locations_data.json').read_text(encoding='utf-8'))
    populations = {state['state_abbr']: state['state_population'] for state in locations['states'].values()}
    national_population = sum(populations.values())
    for uf in UF_CODES:
        census = weights(root / 'cohort=census2022' / f'uf={uf}' / 'part.parquet')
        newborn = weights(root / 'cohort=newborn2025' / f'uf={uf}' / 'part.parquet')
        current = weights(root / 'cohort=current' / f'uf={uf}' / 'part.parquet')
        sidecar = json.loads((root / 'cohort=current' / f'uf={uf}' / 'data_origin.json').read_text(encoding='utf-8'))
        alpha = sidecar['alpha']
        assert alpha == pytest.approx(births[uf] / populations[uf])
        assert len(newborn) > 50, f'{uf}: residual tail collapsed into top50'
        assert set(current) == set(census) | set(newborn)
        for name in current:
            assert current[name] == pytest.approx(
                (1 - alpha) * census.get(name, 0.0) + alpha * newborn.get(name, 0.0), abs=2e-15
            )

    for cohort in COHORTS:
        national = weights(root / f'cohort={cohort}' / 'scope=national' / 'part.parquet')
        ufs = {
            uf: weights(root / f'cohort={cohort}' / f'uf={uf}' / 'part.parquet')
            for uf in UF_CODES
        }
        assert set(national) == set().union(*(set(values) for values in ufs.values()))
        for name, value in national.items():
            expected = sum(populations[uf] * ufs[uf].get(name, 0.0) for uf in UF_CODES) / national_population
            assert value == pytest.approx(expected, abs=3e-15)


@pytest.mark.real_data
def test_cohort_sidecars_declare_model_and_complete_partitions():
    root = DATA / 'parquet' / 'cohorts'
    for cohort in COHORTS:
        for scope in ['scope=national', *(f'uf={uf}' for uf in UF_CODES)]:
            directory = root / f'cohort={cohort}' / scope
            metadata = json.loads((directory / 'data_origin.json').read_text(encoding='utf-8'))
            assert metadata['simple_only'] is True
            assert metadata['formula']
            assert 'tail_coverage' in metadata
            for sex in ('M', 'F'):
                conditional = weights(directory / f'sex={sex}' / 'part.parquet')
                assert math.isclose(sum(conditional.values()), 1.0, abs_tol=1e-12)
    model = json.loads((root / 'cohort=newborn2025' / 'uf=SP' / 'data_origin.json').read_text(encoding='utf-8'))
    assert model['tail_scope'] == 'national_after2010'
    assert 'not UF-observed' in ' '.join(model['limitations'])
    assert model['registrations_uf'] and model['population_uf']


@pytest.mark.real_data
@pytest.mark.parametrize('period', ['until2020', 'after2010'])
def test_new_historical_sex_partitions_match_bins_and_national_empirical_prior(period):
    base = weights(DATA / f'parquet/ibge2022/historical/period={period}/part.parquet')
    assert len(base) == 61_469
    prior_rows = pq.read_table(DATA / 'parquet/ibge2022/sex_prior/scope=national/part.parquet').to_pylist()
    priors = {row['name']: row for row in prior_rows}
    expected_support = set(base) & set(priors)
    for sex, key in [('M', 'p_male'), ('F', 'p_female')]:
        actual = weights(DATA / f'parquet/ibge2022/historical/period={period}/sex={sex}/part.parquet')
        assert set(actual) == expected_support
        assert set(actual).isdisjoint(set(base) - set(priors))
        expected = {name: base[name] * priors[name][key] for name in expected_support}
        denominator = math.fsum(expected.values())
        assert denominator > 0
        for name, numerator in expected.items():
            assert actual[name] == pytest.approx(numerator / denominator, abs=2e-15)
            assert math.isfinite(actual[name]) and actual[name] >= 0
        assert math.fsum(actual.values()) == pytest.approx(1.0)
        sidecar = json.loads((DATA / f'parquet/ibge2022/historical/period={period}/sex={sex}/data_origin.json').read_text())
        assert sidecar['derived'] is True
        assert sidecar['sex_prior_scope'] == 'national'
        assert sidecar['source_rows'] == 61_469
        assert 'not UF-sex' in ' '.join(sidecar['limitations'])

"""Four-layer statistical validation suite for 2022 (default) and 2010 Parquet distributions."""

from __future__ import annotations

import math
import random
from collections import Counter

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ptbr_sampler.br_name_class import BrazilianNameSampler, TimePeriod
from ptbr_sampler.datasets import ensure_data_file, ensure_parquet_root, load_dataset_manifest, resolve_partition_path
from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore
from ptbr_sampler.sampling.validation import (
    exhaustive_multinomial_gof,
    holm_bonferroni_reject,
    linf_distance,
    total_variation_distance,
)


def _read_parquet_rel(relpath: str) -> pa.Table:
    return pq.read_table(ensure_data_file(relpath))


class TestLayerACensus2022IngestionConservation:
    """Layer A: Deterministic source-to-Parquet conservation & anchor invariants."""

    def test_partition_row_counts_and_published_anchors(self):
        nat_given = _read_parquet_rel('parquet/census_year=2022/first_names/scope=national/part.parquet')
        nat_surnames = _read_parquet_rel('parquet/census_year=2022/surnames/scope=national/part.parquet')
        sex_m = _read_parquet_rel('parquet/census_year=2022/first_names/sex=M/part.parquet')
        sex_f = _read_parquet_rel('parquet/census_year=2022/first_names/sex=F/part.parquet')
        states = _read_parquet_rel('parquet/census_year=2022/states/part.parquet')

        assert nat_given.num_rows == 128_458
        assert nat_surnames.num_rows == 201_601
        assert sex_m.num_rows == 60_954
        assert sex_f.num_rows == 73_361
        assert states.num_rows == 27
        assert sum(states['population'].to_pylist()) == 203_080_756

        given_counts = dict(zip(nat_given['name'].to_pylist(), nat_given['count'].to_pylist(), strict=True))
        surname_counts = dict(zip(nat_surnames['name'].to_pylist(), nat_surnames['count'].to_pylist(), strict=True))
        assert given_counts['Maria'] == 12_284_478
        assert surname_counts['Silva'] == 34_030_104
        assert surname_counts['Santos'] == 21_367_475
        assert surname_counts['Perl'] == 24

    def test_every_manifest_parquet_partition_sums_to_unit_mass_in_float64(self):
        manifest = load_dataset_manifest()
        parquet_rels = [rel for rel in sorted(manifest.artifacts) if rel.endswith('part.parquet')]
        assert parquet_rels
        for rel in parquet_rels:
            pf = ensure_data_file(rel)
            schema = pq.read_schema(pf)
            if 'weight' not in schema.names:
                continue
            weights = pq.read_table(pf, columns=['weight'])['weight'].to_pylist()
            assert abs(math.fsum(weights) - 1.0) < 1e-12, f'non-unit weight sum in {rel}'

    def test_exact_national_marginal_coherence_between_sex_prior_and_strict_sex_tables(self):
        nat = _read_parquet_rel('parquet/census_year=2022/first_names/scope=national/part.parquet')
        prior = _read_parquet_rel('parquet/census_year=2022/sex_prior/scope=national/part.parquet')
        strict_f = _read_parquet_rel('parquet/census_year=2022/first_names/sex=F/part.parquet')

        p_f_by_name = dict(zip(prior['name'].to_pylist(), prior['p_female'].to_pylist(), strict=True))
        bayes_num = {
            str(n): float(w) * p_f_by_name[str(n)]
            for n, w in zip(nat['name'].to_pylist(), nat['weight'].to_pylist(), strict=True)
            if math.isfinite(p_f_by_name[str(n)]) and p_f_by_name[str(n)] > 0.0
        }
        z = math.fsum(bayes_num.values())
        bayes_f = {k: v / z for k, v in bayes_num.items()}
        strict_f_map = dict(zip(strict_f['name'].to_pylist(), strict_f['weight'].to_pylist(), strict=True))

        assert set(bayes_f) == set(strict_f_map)
        vocab = sorted(strict_f_map)
        tvd = total_variation_distance(
            np.array([bayes_f[k] for k in vocab]),
            np.array([strict_f_map[k] for k in vocab]),
        )
        assert tvd < 1e-14

    def test_cohort_enzo_shift_and_regional_surname_concentration(self):
        p2010 = _read_parquet_rel('parquet/census_year=2022/first_names/period=ate2010/part.parquet')
        p2020 = _read_parquet_rel('parquet/census_year=2022/first_names/period=ate2020/part.parquet')
        w2010 = dict(zip(p2010['name'].to_pylist(), p2010['weight'].to_pylist(), strict=True))
        w2020 = dict(zip(p2020['name'].to_pylist(), p2020['weight'].to_pylist(), strict=True))
        assert w2020['Enzo'] > 5.0 * w2010['Enzo']

        nat_s = _read_parquet_rel('parquet/census_year=2022/surnames/scope=national/part.parquet')
        se_s = _read_parquet_rel('parquet/census_year=2022/surnames/uf=SE/part.parquet')
        al_s = _read_parquet_rel('parquet/census_year=2022/surnames/uf=AL/part.parquet')
        wnat = dict(zip(nat_s['name'].to_pylist(), nat_s['weight'].to_pylist(), strict=True))
        wse = dict(zip(se_s['name'].to_pylist(), se_s['weight'].to_pylist(), strict=True))
        wal = dict(zip(al_s['name'].to_pylist(), al_s['weight'].to_pylist(), strict=True))
        assert wse['Santos'] > 2.5 * wnat['Santos']
        assert wal['Silva'] > 1.8 * wnat['Silva']


class TestLayerBExactAliasReconstruction:
    """Layer B: Closed-form O(M) alias probability verification (zero Monte Carlo variance)."""

    @pytest.mark.parametrize(
        ('census_year', 'subdir', 'filters'),
        [
            (2010, 'first_names', {'period': 'ate2010'}),
            (2022, 'first_names', {'scope': 'national'}),
            (2022, 'surnames', {'scope': 'national'}),
            (2022, 'first_names', {'sex': 'F'}),
            (2022, 'first_names', {'uf': 'SP'}),
            (2022, 'first_names', {'uf': 'AC'}),
            (2022, 'first_names', {'period': '2020_2022'}),
        ],
    )
    def test_induced_alias_probabilities_match_weights_to_machine_precision(self, census_year: int, subdir: str, filters: dict[str, str]):
        root = ensure_parquet_root(census_year)
        store = PartitionStore(max_entries=4, path_resolver=resolve_partition_path)
        table = store.get(PartitionSpec.of(root / subdir, **filters))
        induced = table.induced_probabilities()
        assert total_variation_distance(induced, table.weights) < 1e-13
        assert linf_distance(induced, table.weights) < 1e-14


@pytest.mark.slow
class TestLayerCMonteCarloAndNegativeControls:
    """Layer C: Exhaustive tail-pooled GoF + Holm-Bonferroni FWER + negative controls."""

    def test_end_to_end_family_passes_holm_bonferroni_at_alpha_0_001(self):
        pytest.importorskip('scipy.stats')
        sampler_2010 = BrazilianNameSampler.from_parquet(census_year=2010)
        sampler_2022 = BrazilianNameSampler.from_parquet()  # default census_year=2022
        sampler_2022_est = BrazilianNameSampler.from_parquet(conditioning_mode='estimated')
        n = 50_000
        cases = {
            '2010_ate2010': (
                sampler_2010,
                sampler_2010._first_names_table(TimePeriod.UNTIL_2010),
                {'time_period': TimePeriod.UNTIL_2010},
            ),
            '2022_all': (
                sampler_2022,
                sampler_2022._first_names_table(TimePeriod.ALL),
                {'time_period': TimePeriod.ALL},
            ),
            '2022_sex_f': (
                sampler_2022,
                sampler_2022._first_names_table(TimePeriod.ALL, sex='F'),
                {'time_period': TimePeriod.ALL, 'sexes': ['F'] * n},
            ),
            '2022_sex_m': (
                sampler_2022,
                sampler_2022._first_names_table(TimePeriod.ALL, sex='M'),
                {'time_period': TimePeriod.ALL, 'sexes': ['M'] * n},
            ),
            '2022_ate2020': (
                sampler_2022,
                sampler_2022._first_names_table(TimePeriod.UNTIL_2020),
                {'time_period': TimePeriod.UNTIL_2020},
            ),
            '2022_uf_sp': (
                sampler_2022,
                sampler_2022._first_names_table(TimePeriod.ALL, uf='SP'),
                {'time_period': TimePeriod.ALL, 'ufs': ['SP'] * n},
            ),
            '2022_est_ba_f': (
                sampler_2022_est,
                sampler_2022_est._first_names_table(TimePeriod.ALL, uf='BA', sex='F'),
                {'time_period': TimePeriod.ALL, 'ufs': ['BA'] * n, 'sexes': ['F'] * n},
            ),
        }
        p_values: dict[str, float] = {}
        for idx, (key, (smp, table, draw_kw)) in enumerate(cases.items()):
            random.seed(10_000 + idx)
            comps = smp.batch_sample_names(n, include_surname=False, **draw_kw)
            tally = Counter(c.first_name for c in comps)
            obs = np.array([tally.get(str(lbl), 0) for lbl in table.labels], dtype=np.int64)
            res = exhaustive_multinomial_gof(obs, table.weights, min_expected=5.0)
            p_values[key] = res.p_value
            # Note: with M up to 128,458 discrete names and n = 50,000 draws (M > n),
            # unpooled L1/TVD has positive finite-sample expectation from zero-count tail
            # cells, whereas L_inf is O(n^{-1/2}) independent of M and tail-pooled GoF
            # tests 100% of probability mass with valid asymptotic chi-square calibration.
            assert res.linf < 0.008, f'{key}: excessive L_inf={res.linf:.5f}'
            expected_tvd_upper = 0.5 * float(np.sum(np.sqrt(table.weights * (1.0 - table.weights) / n))) * 1.25
            assert res.tvd < expected_tvd_upper, f'{key}: excessive TVD={res.tvd:.4f} > {expected_tvd_upper:.4f}'

        assert holm_bonferroni_reject(p_values, alpha=0.001) == set(), f'FWER rejection: {p_values}'

    def test_surname_slot_share_and_two_slot_person_presence_match_distinct_targets(self):
        sampler_2022 = BrazilianNameSampler.from_parquet()
        table = sampler_2022._surnames_table()
        q = dict(zip((str(x) for x in table.labels), table.weights.tolist(), strict=True))
        q_silva = q['Silva']  # ~0.10204044
        # Analytical 2-slot non-colliding presence: q_s + sum_{j != s} q_j * q_s / (1 - q_j)
        expected_two_slot = q_silva + math.fsum(qj * (q_silva / (1.0 - qj)) for name, qj in q.items() if name != 'Silva')
        random.seed(2022)
        one_slot = sampler_2022.batch_sample_names(40_000, time_period=TimePeriod.ALL, with_only_one_surname=True, raw=True)
        two_slot = sampler_2022.batch_sample_names(40_000, time_period=TimePeriod.ALL, with_only_one_surname=False, raw=True)

        emp_one = sum('SILVA' in c.surname.split() for c in one_slot) / 40_000
        emp_two = sum('SILVA' in c.surname.split() for c in two_slot) / 40_000
        assert abs(emp_one - q_silva) < 0.008
        assert abs(emp_two - expected_two_slot) < 0.008

    def test_negative_control_head_to_tail_leak_and_dropped_conditioning_are_rejected(self):
        pytest.importorskip('scipy.stats')
        root_2022 = ensure_parquet_root(2022)
        store = PartitionStore(max_entries=4, path_resolver=resolve_partition_path)
        nat = store.get(PartitionSpec.of(root_2022 / 'first_names', scope='national'))
        sex_f = store.get(PartitionSpec.of(root_2022 / 'first_names', sex='F'))

        # Negative Control 1: 5% mass leaked from tail into top-10 head
        corrupt = nat.weights.copy()
        order = np.argsort(-corrupt)
        corrupt[order[:10]] += 0.005
        corrupt[order[10:]] *= (1.0 - float(corrupt[order[:10]].sum())) / float(corrupt[order[10:]].sum())
        rng = np.random.default_rng(99)
        draws = rng.choice(len(nat), size=30_000, p=corrupt)
        obs = np.bincount(draws, minlength=len(nat))
        res_leak = exhaustive_multinomial_gof(obs, nat.weights, min_expected=5.0)
        assert res_leak.p_value < 1e-6

        # Negative Control 2: unconditioned national draws evaluated against sex=F target.
        # Most common male names (Joao, Jose, Antonio, ...) have >=20 female bearers in a
        # 203M census so ~95.3% of draws land inside sex_f.labels (with ~4.7% strictly
        # outside sex_f support), while sex-ratio weights diverge massively (TVD > 0.40).
        nat_draws = nat.sample(20_000, rng)
        tally = Counter(str(x) for x in nat_draws)
        obs_f = np.array([tally.get(str(lbl), 0) for lbl in sex_f.labels], dtype=np.int64)
        in_support = int(obs_f.sum())
        assert 20_000 - in_support > 500
        res_drop = exhaustive_multinomial_gof(obs_f, sex_f.weights, min_expected=5.0)
        assert res_drop.p_value < 1e-12
        assert res_drop.tvd > 0.25

    def test_batch_size_invariance(self):
        pytest.importorskip('scipy.stats')
        table = AliasTable.from_counts(
            ['alpha', 'beta', 'gamma', 'delta'],
            [50, 30, 15, 5],
        )
        rng_big = np.random.default_rng(11)
        big = table.sample(50_000, rng_big)
        obs_big = np.array([int((big == lab).sum()) for lab in table.labels], dtype=np.int64)

        rng_small = np.random.default_rng(11)
        small_counts = Counter(str(table.sample(1, rng_small)[0]) for _ in range(50_000))
        obs_small = np.array([small_counts.get(str(lab), 0) for lab in table.labels], dtype=np.int64)

        assert exhaustive_multinomial_gof(obs_big, table.weights, min_expected=5.0).p_value > 0.001
        assert exhaustive_multinomial_gof(obs_small, table.weights, min_expected=5.0).p_value > 0.001

"""Deterministic unit tests for Census 2022 statistical auditing and validation primitives."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.validation import (
    exhaustive_multinomial_gof,
    holm_bonferroni_reject,
    linf_distance,
    reconstruct_alias_probabilities,
    total_variation_distance,
)
from scripts.audit_datasets import (
    CensoringSummary,
    audit_cross_table_coherence,
    audit_ibge_2022_tables,
    classify_sex_censoring,
    compute_cohort_alignment_tvd,
    format_census_2022_display_name,
    main as audit_main,
)


def test_reconstruct_alias_probabilities_is_exact_to_machine_precision():
    weights = np.array([0.50, 0.30, 0.15, 0.049, 0.001], dtype=np.float64)
    table = AliasTable.from_weights(['A', 'B', 'C', 'D', 'E'], weights)
    induced = reconstruct_alias_probabilities(table.prob, table.alias)
    assert total_variation_distance(induced, table.weights) < 1e-14
    assert linf_distance(induced, table.weights) < 1e-14
    assert np.allclose(table.induced_probabilities(), induced)


def test_alias_table_top_k_slices_and_renormalises_counts_and_weights():
    by_counts = AliasTable.from_counts(['C', 'A', 'B'], [10, 70, 20])
    top2 = by_counts.top_k(2)
    assert list(top2.labels) == ['A', 'B']
    assert list(top2.counts) == [70, 20]
    assert np.allclose(top2.weights, [70 / 90, 20 / 90])

    by_weights = AliasTable.from_weights(['X', 'Y', 'Z'], [0.1, 0.6, 0.3])
    top2_w = by_weights.top_k(2)
    assert list(top2_w.labels) == ['Y', 'Z']
    assert np.allclose(top2_w.weights, [0.6 / 0.9, 0.3 / 0.9])
    assert by_weights.top_k(10) is by_weights
    with pytest.raises(ValueError, match='k must be >= 1'):
        by_weights.top_k(0)


def test_validation_error_guards():
    with pytest.raises(ValueError, match='non-empty 1D'):
        reconstruct_alias_probabilities(np.array([]), np.array([]))
    with pytest.raises(ValueError, match='shape mismatch'):
        total_variation_distance(np.array([0.5, 0.5]), np.array([1.0]))
    with pytest.raises(ValueError, match='shape mismatch'):
        linf_distance(np.array([0.5, 0.5]), np.array([1.0]))
    with pytest.raises(ValueError, match='matching non-empty 1D'):
        exhaustive_multinomial_gof(np.array([]), np.array([]))
    with pytest.raises(ValueError, match=r'sum to 1\.0'):
        exhaustive_multinomial_gof(np.array([10, 10]), np.array([0.2, 0.2]))
    with pytest.raises(ValueError, match='sample size'):
        exhaustive_multinomial_gof(np.array([0, 0]), np.array([0.5, 0.5]))
    with pytest.raises(ValueError, match='at least 2 pooled bins'):
        exhaustive_multinomial_gof(np.array([2, 2]), np.array([0.5, 0.5]), min_expected=5.0)
    with pytest.raises(ValueError, match='alpha'):
        holm_bonferroni_reject({'p1': 0.01}, alpha=1.5)


def test_exhaustive_multinomial_gof_catches_head_to_tail_leak():
    # 50 head items (each 0.01 = 0.50 total) + 500 tail items (each 0.001 = 0.50 total)
    probs = np.concatenate([np.full(50, 0.01), np.full(500, 0.001)])
    # Corrupt draw generator: shifts 15% mass from tail into head uniformly
    corrupt_probs = np.concatenate([np.full(50, 0.013), np.full(500, 0.0007)])
    rng = np.random.default_rng(12345)
    draws = rng.choice(len(probs), size=20_000, p=corrupt_probs)
    counts = np.bincount(draws, minlength=len(probs))

    res = exhaustive_multinomial_gof(counts, probs, min_expected=5.0)
    assert res.pooled_bins >= 51
    assert abs(res.expected_sum - 20_000.0) < 1e-9
    assert res.p_value < 1e-10
    assert res.tvd > 0.10


def test_holm_bonferroni_controls_familywise_error():
    p_values = {'p1': 0.0001, 'p2': 0.02, 'p3': 0.50}
    rejected = holm_bonferroni_reject(p_values, alpha=0.001)
    assert rejected == {'p1'}


def test_classify_sex_censoring_distinguishes_four_regimes():
    assert classify_sex_censoring(total=100, male=60, female=40) == 'both_observed'
    assert classify_sex_censoring(total=55, male=55, female=None) == 'one_null_exact_zero'
    assert classify_sex_censoring(total=60, male=50, female=None) == 'one_null_suppressed_positive'
    assert classify_sex_censoring(total=28, male=None, female=None) == 'both_null_suppressed'
    with pytest.raises(ValueError, match='conservation'):
        classify_sex_censoring(total=100, male=50, female=40)
    with pytest.raises(ValueError, match='threshold'):
        classify_sex_censoring(total=100, male=75, female=None)


def test_display_name_preserves_spelling_variants_and_capitalizes():
    assert format_census_2022_display_name('maria') == 'Maria'
    assert format_census_2022_display_name('ana') != format_census_2022_display_name('anna')
    assert format_census_2022_display_name('luis') != format_census_2022_display_name('luiz')


def _write_minimal_2022_fixture(root: Path, *, duplicate: bool = False, negative: bool = False) -> None:
    ranking_rows = [
        ('maria', 'given', -10 if negative else 100, 50.0, 1),
        ('ana', 'given', 60, 30.0, 2),
        ('anna', 'given', 25, 12.5, 3),
        ('ariel', 'given', 24, 12.0, 4),
        ('silva', 'surname', 120, 60.0, 1),
        ('perl', 'surname', 24, 12.0, 2),
    ]
    if duplicate:
        ranking_rows.append(('maria', 'given', 100, 50.0, 1))
    pq.write_table(
        pa.table(
            {
                'name_text': [r[0] for r in ranking_rows],
                'name_type': [r[1] for r in ranking_rows],
                'frequency': pa.array([r[2] for r in ranking_rows], type=pa.int32()),
                'percentage': pa.array([r[3] for r in ranking_rows], type=pa.float64()),
                'rank': pa.array([r[4] for r in ranking_rows], type=pa.int32()),
            }
        ),
        root / 'name_ranking.parquet',
    )
    # Note: ('perl', 'surname') intentionally absent from detail to test documented IBGE WAF gap
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria', 'ana', 'anna', 'ariel', 'silva'],
                'name_type': ['given', 'given', 'given', 'given', 'surname'],
                'letter_rank': pa.array([1, 1, 2, 3, 1], type=pa.int32()),
                'male_count': pa.array([20, None, None, None, None], type=pa.int32()),
                'female_count': pa.array([80, 60, 20, None, None], type=pa.int32()),
                'median_age': pa.array([45.0, 38.0, 35.0, 29.0, 40.0], type=pa.float64()),
            }
        ),
        root / 'name_detail.parquet',
    )
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria', 'ana'],
                'name_type': ['given', 'given'],
                'decade': pa.array([2000, 2010], type=pa.int16()),
                'frequency': pa.array([50, 30], type=pa.int32()),
            }
        ),
        root / 'name_by_decade.parquet',
    )
    pq.write_table(
        pa.table(
            {
                'name_text': ['maria', 'silva'],
                'name_type': ['given', 'surname'],
                'state_code': pa.array([35, 35], type=pa.uint8()),
                'frequency': pa.array([40, 50], type=pa.int32()),
                'percentage': pa.array([40.0, 50.0], type=pa.float64()),
            }
        ),
        root / 'name_by_state.parquet',
    )
    pq.write_table(
        pa.table(
            {
                'code': pa.array([35], type=pa.uint8()),
                'abbreviation': ['SP'],
                'name': ['São Paulo'],
                'region_code': pa.array([3], type=pa.uint8()),
                'population': pa.array([200], type=pa.int32()),
            }
        ),
        root / 'state.parquet',
    )


def test_audit_ibge_2022_tables_passes_valid_fixture_and_tolerates_perl_gap(tmp_path: Path):
    _write_minimal_2022_fixture(tmp_path)
    report = audit_ibge_2022_tables(tmp_path)
    assert report['missing_detail_keys'] == [('perl', 'surname')]
    censoring: CensoringSummary = report['censoring']
    assert censoring.both_observed == 1
    assert censoring.one_null_exact_zero == 1
    assert censoring.one_null_suppressed_positive == 1
    assert censoring.both_null_suppressed == 1
    assert abs(report['maria_proportion_from_percentage'] - 0.50) < 1e-12


def test_audit_ibge_2022_tables_rejects_duplicates_and_negative_frequencies(tmp_path: Path):
    dup_dir = tmp_path / 'dup'
    dup_dir.mkdir()
    _write_minimal_2022_fixture(dup_dir, duplicate=True)
    with pytest.raises(ValueError, match='duplicate'):
        audit_ibge_2022_tables(dup_dir)

    neg_dir = tmp_path / 'neg'
    neg_dir.mkdir()
    _write_minimal_2022_fixture(neg_dir, negative=True)
    with pytest.raises(ValueError, match='negative'):
        audit_ibge_2022_tables(neg_dir)


def test_cohort_alignment_detects_ten_year_endpoint_vs_start_shift():
    legacy_2010 = {
        'ate2000': {'MARIA': 0.60, 'ENZO': 0.01, 'ANA': 0.39},
        'ate2010': {'MARIA': 0.38, 'ENZO': 0.02, 'ANA': 0.60},
    }
    olob0_2022_by_decade = {
        1990: {'maria': 610, 'enzo': 10, 'ana': 380},
        2000: {'maria': 390, 'enzo': 20, 'ana': 590},
        2010: {'maria': 250, 'enzo': 250, 'ana': 500},
    }
    matrix = compute_cohort_alignment_tvd(legacy_2010, olob0_2022_by_decade)
    # Legacy 'ate2010' (born 2000-2009) aligns with olob0 decade=2000, NOT decade=2010!
    assert matrix['ate2010'][2000] < 0.03
    assert matrix['ate2010'][2010] > 0.20


def test_audit_cross_table_coherence_and_cli_parquet_dir(tmp_path: Path):
    import json

    from scripts.ingest_to_parquet import ingest_ibge_2022

    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    _write_minimal_2022_fixture(raw_dir)
    parquet_dir = tmp_path / 'parquet'
    ingest_ibge_2022(raw_dir, parquet_dir)

    coherence = audit_cross_table_coherence(raw_dir, parquet_dir)
    assert 0.0 <= coherence['uf_weighted_vs_national_given_tvd'] <= 1.0
    assert abs(coherence['decade_sum_to_national_given_ratio'] - (80.0 / 209.0)) < 1e-12

    json_out = tmp_path / 'audit.json'
    rc = audit_main(['--raw-dir', str(raw_dir), '--parquet-dir', str(parquet_dir), '--json-out', str(json_out)])
    assert rc == 0
    payload = json.loads(json_out.read_text(encoding='utf-8'))
    assert 'cross_table_coherence' in payload
    assert abs(payload['cross_table_coherence']['decade_sum_to_national_given_ratio'] - (80.0 / 209.0)) < 1e-12

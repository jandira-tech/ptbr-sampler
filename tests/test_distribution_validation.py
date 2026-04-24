"""Statistical validation for ingested Parquet tables.

These tests verify that 100k-sample empirical marginals match the ingested
weights per condition. They catch alias-table bugs and data-ingestion
regressions that unit tests would silently accept.

Marked ``slow`` — deselect with ``-m 'not slow'`` for fast iteration.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('scipy.stats')

from scipy.stats import chisquare, ks_2samp

from scripts import ingest_to_parquet
from src.sampling.alias import AliasTable
from src.sampling.store import PartitionSpec, PartitionStore


DATA_DIR = Path(__file__).parent.parent / 'src' / 'data'
PARQUET_DIR = DATA_DIR / 'parquet'


def _ensure_parquet():
    if not (PARQUET_DIR / 'surnames' / 'scope=national' / 'part.parquet').exists():
        ingest_to_parquet.main(['--data-dir', str(DATA_DIR), '--out', str(PARQUET_DIR)])


@pytest.mark.slow
class TestAliasTableReproducesWeights:
    def test_first_names_ate2010(self):
        _ensure_parquet()
        store = PartitionStore(max_entries=4)
        spec = PartitionSpec.of(PARQUET_DIR / 'first_names', period='ate2010')
        table = store.get(spec)
        rng = np.random.default_rng(314159)
        n = 100_000
        draws = table.sample(n, rng)
        observed = {}
        for name in draws:
            key = str(name)
            observed[key] = observed.get(key, 0) + 1

        # Only test the top-50 cells to avoid chi-squared's low-expected-count
        # regime. The remaining tail contributes noise, not signal.
        order = np.argsort(-table.weights)[:50]
        obs_counts = []
        exp_counts = []
        for idx in order:
            label = str(table.labels[idx])
            exp = float(table.weights[idx]) * n
            if exp < 5:
                continue
            obs_counts.append(observed.get(label, 0))
            exp_counts.append(exp)

        # Rescale expected to match observed sum (required by scipy chisquare).
        total_obs = sum(obs_counts)
        total_exp = sum(exp_counts)
        exp_counts = [e * total_obs / total_exp for e in exp_counts]

        stat, p = chisquare(obs_counts, f_exp=exp_counts)
        assert p > 0.01, f'first-name marginals diverged: chi2={stat:.1f}, p={p:.4f}'

    def test_surnames_empirical_silva_share(self):
        _ensure_parquet()
        store = PartitionStore(max_entries=2)
        spec = PartitionSpec.of(PARQUET_DIR / 'surnames', scope='national')
        table = store.get(spec)
        rng = np.random.default_rng(271828)
        draws = table.sample(100_000, rng)

        silva_share = (draws == 'Silva').sum() / len(draws)
        # Repository's committed national weight for Silva is ~0.128. Tolerate
        # 1 percentage point of sampling noise.
        assert 0.115 < silva_share < 0.145


@pytest.mark.slow
class TestAliasVsReferenceDistribution:
    """``ks_2samp`` against a direct ``numpy.random.choice`` draw.

    Both should produce the same categorical distribution, so the KS test on
    the rank-indexed empirical CDFs should fail to reject."""

    def test_first_names_match_reference_numpy(self):
        _ensure_parquet()
        store = PartitionStore(max_entries=2)
        spec = PartitionSpec.of(PARQUET_DIR / 'first_names', period='ate2000')
        table = store.get(spec)
        rng = np.random.default_rng(42)

        # Rank indices for KS — categorical → ordinal → continuous-ish.
        alias_idx = np.where(np.isin(table.labels, table.labels))[0]
        # Map labels to fixed integer positions for KS input.
        pos = {lab: i for i, lab in enumerate(table.labels)}
        alias_draws = np.fromiter(
            (pos[str(s)] for s in table.sample(20_000, rng)),
            dtype=np.int64,
            count=20_000,
        )

        ref_rng = np.random.default_rng(42)
        ref_draws = ref_rng.choice(
            np.arange(len(table)),
            size=20_000,
            p=table.weights,
            replace=True,
        )

        stat, p = ks_2samp(alias_draws, ref_draws)
        assert p > 0.01, f'alias draws diverge from numpy.random.choice: KS={stat:.3f}, p={p:.4f}'


@pytest.mark.slow
class TestAliasIsInvariantToBatchSize:
    """Draws made with ``k=1`` repeatedly vs. one ``k=N`` call must agree
    statistically (the alias method guarantees this by construction)."""

    def test_batch_equivalence(self):
        table = AliasTable.from_counts(
            ['alpha', 'beta', 'gamma', 'delta'],
            [50, 30, 15, 5],
        )
        rng_big = np.random.default_rng(11)
        big = table.sample(50_000, rng_big)
        big_counts = {lab: int((big == lab).sum()) for lab in table.labels}

        rng_small = np.random.default_rng(11)
        small_counts = dict.fromkeys((str(lab) for lab in table.labels), 0)
        for _ in range(50_000):
            small_counts[str(table.sample(1, rng_small)[0])] += 1

        # Compare as chi-square between two empirical samples with the same
        # underlying distribution — both should land in the same ballpark.
        labels = list(table.labels)
        obs_a = [big_counts[lab] for lab in labels]
        obs_b = [small_counts[str(lab)] for lab in labels]

        # Pearson chi-square between two multinomials with common expected
        # counts (the theoretical weights). Both should fail to reject the
        # null at p > 0.01.
        n = sum(obs_a)
        exp = [float(w) * n for w in table.weights]
        _, p_a = chisquare(obs_a, f_exp=exp)
        _, p_b = chisquare(obs_b, f_exp=exp)
        assert p_a > 0.01
        assert p_b > 0.01

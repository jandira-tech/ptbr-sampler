"""Walker/Vose alias-method correctness."""

from __future__ import annotations

import numpy as np
import pytest

from src.sampling.alias import AliasTable, build_alias, draw


class TestBuildAlias:
    def test_uniform(self):
        prob, alias = build_alias(np.ones(5))
        assert prob.shape == (5,)
        assert alias.shape == (5,)
        assert np.allclose(prob, 1.0)

    def test_skewed(self):
        prob, alias = build_alias(np.array([1.0, 9.0]))
        assert prob.shape == (2,)
        assert prob[0] == pytest.approx(0.2)

    def test_empty_weights_rejected(self):
        with pytest.raises(ValueError):
            build_alias(np.array([]))

    def test_negative_weights_rejected(self):
        with pytest.raises(ValueError):
            build_alias(np.array([1.0, -1.0]))

    def test_zero_total_rejected(self):
        with pytest.raises(ValueError):
            build_alias(np.zeros(3))

    def test_non_finite_rejected(self):
        with pytest.raises(ValueError):
            build_alias(np.array([np.inf, 1.0]))

    def test_multidim_rejected(self):
        with pytest.raises(ValueError):
            build_alias(np.ones((2, 3)))


class TestDraw:
    def test_draw_shape(self):
        prob, alias = build_alias(np.array([1.0, 2.0, 3.0]))
        rng = np.random.default_rng(0)
        out = draw(prob, alias, 10, rng)
        assert out.shape == (10,)

    def test_draw_negative_k_rejected(self):
        prob, alias = build_alias(np.array([1.0]))
        with pytest.raises(ValueError):
            draw(prob, alias, -1, np.random.default_rng(0))

    def test_empirical_matches_weights(self):
        weights = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        expected = weights / weights.sum()
        prob, alias = build_alias(weights)
        rng = np.random.default_rng(123)
        samples = draw(prob, alias, 200_000, rng)
        counts = np.bincount(samples, minlength=5)
        empirical = counts / counts.sum()
        # Tolerance 1.5% absolute is generous for 200k samples over 5 cells.
        np.testing.assert_allclose(empirical, expected, atol=0.015)


class TestAliasTable:
    def test_from_counts(self):
        t = AliasTable.from_counts(['a', 'b', 'c'], [1, 2, 3])
        assert len(t) == 3
        assert t.labels.tolist() == ['a', 'b', 'c']

    def test_from_weights(self):
        t = AliasTable.from_weights(['x', 'y'], [0.25, 0.75])
        rng = np.random.default_rng(0)
        draws = t.sample(50_000, rng)
        frac_y = (draws == 'y').sum() / len(draws)
        assert 0.72 < frac_y < 0.78

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            AliasTable.from_counts([], [])

    def test_shape_mismatch_rejected(self):
        with pytest.raises(ValueError):
            AliasTable.from_counts(['a', 'b'], [1])

    def test_from_weights_shape_mismatch_rejected(self):
        with pytest.raises(ValueError):
            AliasTable.from_weights(['a'], [0.5, 0.5])

    def test_sample_returns_labels(self):
        t = AliasTable.from_counts(['silva', 'santos'], [100, 50])
        rng = np.random.default_rng(42)
        draws = t.sample(10, rng)
        assert set(draws.tolist()).issubset({'silva', 'santos'})

    def test_cost_is_independent_of_support_size(self):
        """Sanity check: a 50k-cell alias table is not massively slower to
        draw from than a 5-cell one. Exact timings are platform-dependent,
        so we just assert both complete within a generous envelope."""
        import time

        small = AliasTable.from_counts(['a', 'b', 'c', 'd', 'e'], [1, 1, 1, 1, 1])
        large = AliasTable.from_counts(
            [f'n{i}' for i in range(50_000)],
            list(range(1, 50_001)),
        )
        rng = np.random.default_rng(0)
        t0 = time.perf_counter()
        small.sample(100_000, rng)
        t1 = time.perf_counter()
        large.sample(100_000, rng)
        t2 = time.perf_counter()
        # Envelope: large should be within 5x of small — i.e. the per-draw
        # cost does not scale with support size in any alarming way.
        assert (t2 - t1) < 5 * (t1 - t0) + 0.5

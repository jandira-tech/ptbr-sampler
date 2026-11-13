"""Walker/Vose alias method.

``random.choices`` and ``numpy.random.choice(p=...)`` both rebuild cumulative
weights on every call — O(m) per draw. The alias method is O(m) to build
once and O(1) per draw forever after, and is trivially vectorisable. For a
50k-entry surname distribution that is the difference between tens of
milliseconds per draw and a few microseconds.

This implementation keeps the probability (``prob``) and alias (``alias``)
arrays as NumPy ``float64`` / ``int64`` so that ``draw`` can operate on a
whole batch of uniforms without Python-level loops.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np


def build_alias(weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build alias-method tables for ``weights``.

    Args:
        weights: Non-negative, finite weights. Must contain at least one
            positive value. Will be normalised internally.

    Returns:
        ``(prob, alias)`` where ``prob[i]`` is the probability of staying in
        cell ``i`` and ``alias[i]`` is the fallback cell. Both arrays have
        length ``len(weights)``.
    """
    w = np.asarray(weights, dtype=np.float64)
    if w.ndim != 1:
        raise ValueError('weights must be 1-dimensional')
    if w.size == 0:
        raise ValueError('weights must be non-empty')
    if np.any(w < 0) or not np.all(np.isfinite(w)):
        raise ValueError('weights must be non-negative and finite')
    total = math.fsum(w.tolist())
    if total <= 0.0:
        raise ValueError('weights must sum to a positive value')

    n = w.size
    q = n * (w / total)
    prob = np.ones(n, dtype=np.float64)
    alias = np.arange(n, dtype=np.int64)

    # Deque ops are O(1); list.pop(0) would be O(m) which matters for 50k+.
    small: deque[int] = deque(int(i) for i in np.flatnonzero(q < 1.0))
    large: deque[int] = deque(int(i) for i in np.flatnonzero(q >= 1.0))

    while small and large:
        small_idx = small.pop()
        large_idx = large.pop()
        prob[small_idx] = q[small_idx]
        alias[small_idx] = large_idx
        q[large_idx] = q[large_idx] + q[small_idx] - 1.0
        if q[large_idx] < 1.0:
            small.append(large_idx)
        else:
            large.append(large_idx)

    # Remaining indices should have q ≈ 1; pin them to avoid f.p. drift.
    for i in large:
        prob[i] = 1.0
    for i in small:
        prob[i] = 1.0

    return prob, alias


def draw(
    prob: np.ndarray,
    alias: np.ndarray,
    k: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw ``k`` indices from the distribution represented by ``prob``/``alias``.

    Cost is O(k) and does not depend on the support size.
    """
    if k < 0:
        raise ValueError('k must be non-negative')
    n = prob.shape[0]
    u = rng.random(k) * n
    i = u.astype(np.int64)
    # ``u - i`` is the fractional part in [0, 1).
    return np.where(u - i < prob[i], i, alias[i])


@dataclass(slots=True, frozen=True)
class AliasTable:
    """Named alias table keyed by ``labels``.

    ``labels`` are kept as a NumPy object array for cheap fancy indexing.
    Construction normalises ``weights`` but also keeps the original ``counts``
    so downstream code can report ground-truth frequencies without
    re-reading the partition.
    """

    labels: np.ndarray
    counts: np.ndarray
    weights: np.ndarray
    prob: np.ndarray
    alias: np.ndarray

    @classmethod
    def from_counts(cls, labels: Iterable[str], counts: Iterable[int]) -> AliasTable:
        labels_arr = np.asarray(list(labels), dtype=object)
        counts_arr = np.asarray(list(counts), dtype=np.int64)
        if labels_arr.shape != counts_arr.shape:
            raise ValueError('labels and counts must have the same length')
        if labels_arr.size == 0:
            raise ValueError('alias table must be non-empty')
        total = int(counts_arr.sum())
        if total <= 0:
            raise ValueError('counts must sum to a positive value')
        weights = counts_arr.astype(np.float64) / float(total)
        prob, alias = build_alias(counts_arr.astype(np.float64))
        return cls(labels=labels_arr, counts=counts_arr, weights=weights, prob=prob, alias=alias)

    @classmethod
    def from_weights(cls, labels: Iterable[str], weights: Iterable[float]) -> AliasTable:
        labels_arr = np.asarray(list(labels), dtype=object)
        weights_arr = np.asarray(list(weights), dtype=np.float64)
        if labels_arr.shape != weights_arr.shape:
            raise ValueError('labels and weights must have the same length')
        if labels_arr.size == 0:
            raise ValueError('alias table must be non-empty')
        counts_arr = np.zeros_like(weights_arr, dtype=np.int64)
        total = math.fsum(weights_arr.tolist())
        if total <= 0.0:
            raise ValueError('weights must sum to a positive value')
        weights_arr = weights_arr / total
        prob, alias = build_alias(weights_arr)
        return cls(labels=labels_arr, counts=counts_arr, weights=weights_arr, prob=prob, alias=alias)

    def induced_probabilities(self) -> np.ndarray:
        """Return the exact categorical probabilities induced by ``(self.prob, self.alias)``."""
        from .validation import reconstruct_alias_probabilities  # noqa: PLC0415

        return reconstruct_alias_probabilities(self.prob, self.alias)

    def top_k(self, k: int) -> AliasTable:
        """Return a renormalised ``AliasTable`` over the top ``k`` entries ranked by weight/count."""
        if k < 1:
            raise ValueError('k must be >= 1')
        if k >= len(self):
            return self
        metric = self.counts.astype(np.float64) if int(self.counts.sum()) > 0 else self.weights
        order = np.argsort(-metric, kind='mergesort')[:k]
        if int(self.counts.sum()) > 0:
            return AliasTable.from_counts(self.labels[order].tolist(), self.counts[order].tolist())
        return AliasTable.from_weights(self.labels[order].tolist(), self.weights[order].tolist())

    def sample(self, k: int, rng: np.random.Generator) -> np.ndarray:
        """Draw ``k`` labels. Returns an object ndarray of length ``k``."""
        idx = draw(self.prob, self.alias, k, rng)
        return self.labels[idx]

    def sample_uniform(self, k: int, rng: np.random.Generator) -> np.ndarray:
        """Draw ``k`` labels uniformly across the support, ignoring weights.

        This is the explicit-random escape hatch documented in
        ``docs/architecture.md`` (``random=True``). The realistic default is
        :meth:`sample`, which honours the empirical distribution.
        """
        if k < 0:
            raise ValueError('k must be non-negative')
        n = self.labels.shape[0]
        idx = rng.integers(0, n, size=k)
        return self.labels[idx]

    def __len__(self) -> int:
        return int(self.labels.shape[0])

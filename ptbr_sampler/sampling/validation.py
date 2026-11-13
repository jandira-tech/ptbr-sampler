"""Exact and Monte Carlo statistical validation primitives for categorical tables."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True, frozen=True)
class MultinomialGoFResult:
    """Summary of an exhaustive tail-pooled categorical goodness-of-fit test."""

    chi2_stat: float
    g_stat: float
    p_value: float
    df: int
    pooled_bins: int
    sample_size: int
    expected_sum: float
    tvd: float
    linf: float


def reconstruct_alias_probabilities(prob: np.ndarray, alias: np.ndarray) -> np.ndarray:
    """Return the exact categorical probability vector induced by ``(prob, alias)`` in O(M).

    For a Walker/Vose table of size M, uniform slot choice i in {0..M-1} stays at i with
    probability prob[i]/M and redirects to alias[i] with probability (1 - prob[i])/M:

        p_induced[j] = (prob[j] + sum_{i: alias[i] == j} (1 - prob[i])) / M
    """
    p = np.asarray(prob, dtype=np.float64)
    a = np.asarray(alias, dtype=np.int64)
    if p.ndim != 1 or a.ndim != 1 or p.shape != a.shape or p.size == 0:
        raise ValueError('prob and alias must be non-empty 1D arrays of equal length')
    m = p.size
    donors = 1.0 - p
    nonzero_mask = donors != 0.0
    if not np.any(nonzero_mask):
        return p / float(m)
    targets = a[nonzero_mask]
    vals = donors[nonzero_mask]
    order = np.argsort(targets, kind='mergesort')
    sorted_targets = targets[order]
    sorted_vals = vals[order].tolist()
    uniq_targets, starts = np.unique(sorted_targets, return_index=True)
    ends = [*starts[1:].tolist(), len(sorted_vals)]
    redirected = np.zeros(m, dtype=np.float64)
    for tgt, s, e in zip(uniq_targets.tolist(), starts.tolist(), ends, strict=True):
        redirected[tgt] = math.fsum(sorted_vals[s:e])
    return (p + redirected) / float(m)


def total_variation_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Return TVD(p, q) = 0.5 * sum_i |p_i - q_i| using compensated summation."""
    pa = np.asarray(p, dtype=np.float64)
    qa = np.asarray(q, dtype=np.float64)
    if pa.shape != qa.shape:
        raise ValueError(f'probability shape mismatch: {pa.shape} vs {qa.shape}')
    return 0.5 * math.fsum(np.abs(pa - qa).tolist())


def linf_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Return max_i |p_i - q_i|."""
    pa = np.asarray(p, dtype=np.float64)
    qa = np.asarray(q, dtype=np.float64)
    if pa.shape != qa.shape:
        raise ValueError(f'probability shape mismatch: {pa.shape} vs {qa.shape}')
    return float(np.max(np.abs(pa - qa)))


def exhaustive_multinomial_gof(
    observed_counts: np.ndarray,
    target_probs: np.ndarray,
    *,
    min_expected: float = 5.0,
) -> MultinomialGoFResult:
    """Run an exhaustive categorical GoF test without dropping or rescaling tail mass.

    Categories are sorted in descending order of ``target_probs`` and greedily pooled
    from largest to smallest so every pooled cell satisfies ``E_j >= min_expected``.
    If the final remainder cell has ``E_last < min_expected``, it is merged into the
    preceding cell. Thus ``sum(E_j) == n == sum(O_j)`` holds identically without ad-hoc
    renormalization, making head-to-tail probability leaks strictly detectable.
    """
    from scipy.stats import chi2  # noqa: PLC0415 - scipy is test-only

    obs = np.asarray(observed_counts, dtype=np.int64)
    probs = np.asarray(target_probs, dtype=np.float64)
    if obs.ndim != 1 or probs.ndim != 1 or obs.shape != probs.shape or obs.size == 0:
        raise ValueError('observed_counts and target_probs must be matching non-empty 1D arrays')
    prob_sum = math.fsum(probs.tolist())
    if abs(prob_sum - 1.0) > 1e-9:
        raise ValueError(f'target_probs must sum to 1.0 (got {prob_sum:.12f})')
    n = int(obs.sum())
    if n <= 0:
        raise ValueError('sample size n must be positive')

    emp_probs = obs.astype(np.float64) / float(n)
    tvd = total_variation_distance(emp_probs, probs)
    linf = linf_distance(emp_probs, probs)

    order = np.argsort(-probs, kind='mergesort')
    pooled_obs: list[float] = []
    pooled_exp: list[float] = []
    acc_obs = 0.0
    acc_exp = 0.0
    for idx in order:
        acc_obs += float(obs[idx])
        acc_exp += float(probs[idx]) * n
        if acc_exp >= min_expected:
            pooled_obs.append(acc_obs)
            pooled_exp.append(acc_exp)
            acc_obs = 0.0
            acc_exp = 0.0
    if acc_exp > 0.0 or acc_obs > 0.0:
        if pooled_exp:
            pooled_obs[-1] += acc_obs
            pooled_exp[-1] += acc_exp
        else:
            pooled_obs.append(acc_obs)
            pooled_exp.append(acc_exp)

    if len(pooled_exp) < 2:
        raise ValueError('need at least 2 pooled bins with expected count >= min_expected')

    o_arr = np.asarray(pooled_obs, dtype=np.float64)
    e_arr = np.asarray(pooled_exp, dtype=np.float64)
    chi2_stat = float(math.fsum(((o_arr - e_arr) ** 2 / e_arr).tolist()))
    nonzero = o_arr > 0
    g_terms = np.zeros_like(o_arr)
    g_terms[nonzero] = 2.0 * o_arr[nonzero] * np.log(o_arr[nonzero] / e_arr[nonzero])
    g_stat = float(math.fsum(g_terms.tolist()))
    df = len(pooled_exp) - 1
    p_value = float(chi2.sf(chi2_stat, df))

    return MultinomialGoFResult(
        chi2_stat=chi2_stat,
        g_stat=g_stat,
        p_value=p_value,
        df=df,
        pooled_bins=len(pooled_exp),
        sample_size=n,
        expected_sum=float(math.fsum(pooled_exp)),
        tvd=tvd,
        linf=linf,
    )


def holm_bonferroni_reject(p_values: dict[str, float], *, alpha: float = 0.001) -> set[str]:
    """Return keys rejected by the step-down Holm-Bonferroni procedure at FWER ``alpha``."""
    if not 0.0 < alpha < 1.0:
        raise ValueError('alpha must be in (0, 1)')
    m = len(p_values)
    ranked = sorted(p_values.items(), key=lambda kv: kv[1])
    rejected: set[str] = set()
    for rank_idx, (key, p_val) in enumerate(ranked):
        threshold = alpha / float(m - rank_idx)
        if p_val <= threshold:
            rejected.add(key)
        else:
            break
    return rejected

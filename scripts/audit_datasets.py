"""Statistical audit and discrepancy-ledger generator for IBGE Census 2022 tables."""

from __future__ import annotations

import argparse
import json
import math
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from ptbr_sampler.sampling.validation import total_variation_distance

DOCUMENTED_MISSING_DETAIL_KEYS: frozenset[tuple[str, str]] = frozenset({('perl', 'surname')})


@dataclass(slots=True, frozen=True)
class CensoringSummary:
    both_observed: int
    one_null_exact_zero: int
    one_null_suppressed_positive: int
    both_null_suppressed: int
    observed_male_mass: int
    observed_female_mass: int
    suppressed_positive_residual_mass: int
    both_null_mass: int


def format_census_2022_display_name(name_text: str) -> str:
    """Convert lowercase upstream ``name_text`` into canonical Title-Cased display form."""
    cleaned = ' '.join(name_text.strip().split())
    if not cleaned:
        raise ValueError('name_text must be non-empty')
    return ' '.join(tok.capitalize() for tok in cleaned.split(' '))


def _fold_ascii_key(text: str) -> str:
    decomposed = unicodedata.normalize('NFKD', text.strip().lower())
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch))


def classify_sex_censoring(total: int, male: int | None, female: int | None) -> str:
    """Classify a given-name row under IBGE's <20 sex-cell disclosure rule."""
    if total < 20:
        raise ValueError(f'national given-name frequency below <20 threshold: {total}')
    if male is not None and female is not None:
        if male < 20 or female < 20:
            raise ValueError(f'observed sex count below <20 threshold: male={male}, female={female}')
        if total != male + female:
            raise ValueError(f'sex-count conservation violated: total={total} != {male}+{female}')
        return 'both_observed'
    if male is not None or female is not None:
        obs = male if male is not None else female
        if obs is None or obs < 20:
            raise ValueError(f'observed sex count below <20 threshold: {obs}')
        residual = total - obs
        if residual < 0 or residual > 19:
            raise ValueError(f'suppressed opposite-sex residual outside [0, 19] threshold: {residual}')
        return 'one_null_exact_zero' if residual == 0 else 'one_null_suppressed_positive'
    if total > 38:
        raise ValueError(f'both_null_suppressed impossible when total={total} > 38 (at least one sex >= 20)')
    return 'both_null_suppressed'


def audit_ibge_2022_tables(raw_dir: Path) -> dict[str, Any]:
    """Validate keys, foreign-key inclusion, signs, scaling, and censoring on 2022 Parquet tables."""
    ranking = pq.read_table(raw_dir / 'name_ranking.parquet')
    detail = pq.read_table(raw_dir / 'name_detail.parquet')
    by_decade = pq.read_table(raw_dir / 'name_by_decade.parquet')
    by_state = pq.read_table(raw_dir / 'name_by_state.parquet')
    states = pq.read_table(raw_dir / 'state.parquet')

    state_pop_by_code = dict(zip(states['code'].to_pylist(), states['population'].to_pylist(), strict=True))
    national_pop = int(sum(state_pop_by_code.values()))
    if national_pop <= 0:
        raise ValueError('state.parquet population sum must be positive')

    ranking_freq: dict[tuple[str, str], int] = {}
    ranking_pct: dict[tuple[str, str], float] = {}
    for name_text, name_type, freq, pct in zip(
        ranking['name_text'].to_pylist(),
        ranking['name_type'].to_pylist(),
        ranking['frequency'].to_pylist(),
        ranking['percentage'].to_pylist(),
        strict=True,
    ):
        if freq is None or int(freq) <= 0:
            raise ValueError(f'negative or zero frequency for {(name_text, name_type)}: {freq}')
        key = (str(name_text), str(name_type))
        if key in ranking_freq:
            raise ValueError(f'duplicate primary key in name_ranking: {key}')
        ranking_freq[key] = int(freq)
        ranking_pct[key] = float(pct)

    detail_map: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for name_text, name_type, male, female in zip(
        detail['name_text'].to_pylist(),
        detail['name_type'].to_pylist(),
        detail['male_count'].to_pylist(),
        detail['female_count'].to_pylist(),
        strict=True,
    ):
        key = (str(name_text), str(name_type))
        if key in detail_map:
            raise ValueError(f'duplicate primary key in name_detail: {key}')
        if key not in ranking_freq:
            raise ValueError(f'orphan key in name_detail absent from name_ranking: {key}')
        detail_map[key] = (None if male is None else int(male), None if female is None else int(female))

    missing_detail = sorted(set(ranking_freq) - set(detail_map))
    unexpected_missing = set(missing_detail) - DOCUMENTED_MISSING_DETAIL_KEYS
    if unexpected_missing:
        raise ValueError(f'unexpected missing name_detail keys: {sorted(unexpected_missing)}')

    seen_decade: set[tuple[str, str, int]] = set()
    for name_text, name_type, decade, freq in zip(
        by_decade['name_text'].to_pylist(),
        by_decade['name_type'].to_pylist(),
        by_decade['decade'].to_pylist(),
        by_decade['frequency'].to_pylist(),
        strict=True,
    ):
        dkey = (str(name_text), str(name_type), int(decade))
        if dkey in seen_decade:
            raise ValueError(f'duplicate key in name_by_decade: {dkey}')
        seen_decade.add(dkey)
        if (dkey[0], dkey[1]) not in ranking_freq:
            raise ValueError(f'orphan key in name_by_decade: {dkey}')
        if int(freq) <= 0:
            raise ValueError(f'negative or zero decade frequency: {dkey}')

    seen_state: set[tuple[str, str, int]] = set()
    for name_text, name_type, scode, freq in zip(
        by_state['name_text'].to_pylist(),
        by_state['name_type'].to_pylist(),
        by_state['state_code'].to_pylist(),
        by_state['frequency'].to_pylist(),
        strict=True,
    ):
        skey = (str(name_text), str(name_type), int(scode))
        if skey in seen_state:
            raise ValueError(f'duplicate key in name_by_state: {skey}')
        seen_state.add(skey)
        if int(scode) not in state_pop_by_code:
            raise ValueError(f'unknown state_code in name_by_state: {scode}')
        if (skey[0], skey[1]) not in ranking_freq:
            raise ValueError(f'orphan key in name_by_state: {skey}')
        if int(freq) <= 0:
            raise ValueError(f'negative or zero state frequency: {skey}')

    counts_by_regime: dict[str, int] = defaultdict(int)
    obs_m = 0
    obs_f = 0
    supp_pos_mass = 0
    both_null_mass = 0
    for (name_text, name_type), total in ranking_freq.items():
        if name_type != 'given':
            continue
        male, female = detail_map[name_text, name_type]
        regime = classify_sex_censoring(total=total, male=male, female=female)
        counts_by_regime[regime] += 1
        if male is not None:
            obs_m += male
        if female is not None:
            obs_f += female
        if regime == 'one_null_suppressed_positive':
            supp_pos_mass += total - (male if male is not None else (female or 0))
        elif regime == 'both_null_suppressed':
            both_null_mass += total

    maria_pct = ranking_pct.get(('maria', 'given'), 0.0)
    return {
        'national_population': national_pop,
        'given_rows': sum(1 for (_, t) in ranking_freq if t == 'given'),
        'surname_rows': sum(1 for (_, t) in ranking_freq if t == 'surname'),
        'missing_detail_keys': missing_detail,
        'maria_proportion_from_percentage': maria_pct / 100.0,
        'censoring': CensoringSummary(
            both_observed=counts_by_regime['both_observed'],
            one_null_exact_zero=counts_by_regime['one_null_exact_zero'],
            one_null_suppressed_positive=counts_by_regime['one_null_suppressed_positive'],
            both_null_suppressed=counts_by_regime['both_null_suppressed'],
            observed_male_mass=obs_m,
            observed_female_mass=obs_f,
            suppressed_positive_residual_mass=supp_pos_mass,
            both_null_mass=both_null_mass,
        ),
    }


def compute_cohort_alignment_tvd(
    legacy_2010_periods: dict[str, dict[str, float]],
    olob0_by_decade: dict[int, dict[str, int]],
) -> dict[str, dict[int, float]]:
    """Compute pairwise TVD between legacy 2010 ``ate<Y>`` keys and 2022 ``decade`` bins."""
    norm_2010: dict[str, dict[str, float]] = {}
    for pkey, mapping in legacy_2010_periods.items():
        folded: dict[str, float] = defaultdict(float)
        for name, weight in mapping.items():
            folded[_fold_ascii_key(name)] += float(weight)
        tot = math.fsum(folded.values())
        norm_2010[pkey] = {k: v / tot for k, v in folded.items()}

    norm_2022: dict[int, dict[str, float]] = {}
    for dec, mapping in olob0_by_decade.items():
        folded_22: dict[str, float] = defaultdict(float)
        for name, cnt in mapping.items():
            folded_22[_fold_ascii_key(name)] += float(cnt)
        tot = math.fsum(folded_22.values())
        norm_2022[dec] = {k: v / tot for k, v in folded_22.items()}

    out: dict[str, dict[int, float]] = {}
    for pkey, p_dist in norm_2010.items():
        out[pkey] = {}
        for dec, q_dist in norm_2022.items():
            vocab = sorted(set(p_dist) | set(q_dist))
            p_vec = np.array([p_dist.get(k, 0.0) for k in vocab], dtype=np.float64)
            q_vec = np.array([q_dist.get(k, 0.0) for k in vocab], dtype=np.float64)
            out[pkey][dec] = total_variation_distance(p_vec, q_vec)
    return out


def audit_cross_table_coherence(raw_dir: Path, parquet_dir: Path) -> dict[str, float]:
    """Layer D: Cross-table marginal coherence diagnostics across 2022 tables."""
    root_2022 = parquet_dir if parquet_dir.name == 'census_year=2022' else parquet_dir / 'census_year=2022'
    nat = pq.read_table(root_2022 / 'first_names' / 'scope=national' / 'part.parquet')
    states = pq.read_table(root_2022 / 'states' / 'part.parquet')
    by_decade = pq.read_table(raw_dir / 'name_by_decade.parquet')

    nat_w = dict(zip(nat['name'].to_pylist(), nat['weight'].to_pylist(), strict=True))
    total_pop = float(sum(states['population'].to_pylist()))
    uf_mix: dict[str, float] = defaultdict(float)
    for uf, pop in zip(states['abbreviation'].to_pylist(), states['population'].to_pylist(), strict=True):
        w_u = float(pop) / total_pop
        uf_tbl = pq.read_table(root_2022 / 'first_names' / f'uf={uf}' / 'part.parquet')
        for n, w in zip(uf_tbl['name'].to_pylist(), uf_tbl['weight'].to_pylist(), strict=True):
            uf_mix[str(n)] += w_u * float(w)

    vocab = sorted(set(nat_w) | set(uf_mix))
    tvd_uf_vs_nat = total_variation_distance(
        np.array([uf_mix.get(k, 0.0) for k in vocab]),
        np.array([nat_w.get(k, 0.0) for k in vocab]),
    )
    given_sum = float(sum(nat['count'].to_pylist()))
    decade_sum = float(
        sum(
            int(freq)
            for nt, freq in zip(by_decade['name_type'].to_pylist(), by_decade['frequency'].to_pylist(), strict=True)
            if nt == 'given'
        )
    )
    return {
        'uf_weighted_vs_national_given_tvd': tvd_uf_vs_nat,
        'decade_sum_to_national_given_ratio': decade_sum / given_sum,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Audit Census 2022 Parquet tables.')
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--parquet-dir', type=Path, default=None)
    parser.add_argument('--json-out', type=Path, default=None)
    args = parser.parse_args(argv)

    report = audit_ibge_2022_tables(args.raw_dir)
    serializable: dict[str, Any] = {
        **report,
        'missing_detail_keys': [list(k) for k in report['missing_detail_keys']],
        'censoring': asdict(report['censoring']),
    }
    if args.parquet_dir is not None:
        serializable['cross_table_coherence'] = audit_cross_table_coherence(args.raw_dir, args.parquet_dir)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(serializable, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(serializable, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

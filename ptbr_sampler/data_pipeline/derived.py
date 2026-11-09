"""First-name cohort derivations from verified IBGE, Arpen, and POP2026 data.

The arithmetic lives separately from I/O so the formulas can be checked with
small hand-calculated fixtures. All labels are case-folded before joining
sources; newborn rows must be the source's atomic SIMPLE classification.
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ptbr_sampler.data_pipeline.io import write_json
from ptbr_sampler.data_pipeline.registry import UF_CODES

Weights = Mapping[str, float]
Counts = Mapping[str, int]
SexPriors = Mapping[str, Mapping[str, float]]


def _normalise(values: Mapping[str, float], *, preserve_zeros: bool = False) -> dict[str, float]:
    clean: dict[str, float] = {}
    for name, weight in values.items():
        numeric_weight = float(weight)
        if not math.isfinite(numeric_weight) or numeric_weight < 0:
            raise ValueError('derived distribution must contain finite nonnegative weights')
        if preserve_zeros or numeric_weight > 0:
            key = str(name).casefold()
            clean[key] = clean.get(key, 0.0) + numeric_weight
    if not clean:
        raise ValueError('derived distribution must contain finite nonnegative weights')
    total = math.fsum(clean.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError('derived distribution needs finite positive total weights')
    return {name: weight / total for name, weight in clean.items()}


def derive_newborn_distribution(observed_simple: Counts, *, births: int, national_post2010: Weights) -> dict[str, float]:
    """Allocate Arpen residual mass over the national IBGE 2011-2020 tail.

    For each top50 row, ``p_i = count_i / births``. Names in that UF's top50
    are excluded from the national tail, and residual mass is spread over the
    remaining tail in proportion to its normalized IBGE national weights.
    A top50 label absent from the tail is added with exactly its observed mass.
    """
    if births <= 0:
        raise ValueError('births must be positive')
    observed: dict[str, float] = {}
    for name, count in observed_simple.items():
        label = str(name).strip()
        if any(character.isspace() for character in label):
            raise ValueError('newborn SIMPLE first-name rows must be atomic, not compound strings')
        if count < 0:
            raise ValueError('observed first-name counts must be nonnegative')
        key = label.casefold()
        observed[key] = observed.get(key, 0.0) + count / births
    observed_mass = math.fsum(observed.values())
    residual = 1.0 - observed_mass
    if residual < -1e-12:
        raise ValueError('observed top50 mass exceeds births; residual would be negative')
    residual = max(0.0, residual)
    tail_source = _normalise(national_post2010, preserve_zeros=True)
    tail = {name: weight for name, weight in tail_source.items() if name not in observed}
    tail_total = math.fsum(tail.values())
    if residual and tail_total <= 0:
        raise ValueError('residual mass requires positive eligible national post2010 tail mass')
    result = dict(observed)
    for name, weight in tail.items():
        result[name] = result.get(name, 0.0) + residual * weight / tail_total if tail_total else 0.0
    return _normalise(result, preserve_zeros=True)


def blend_distributions(census2022: Weights, newborn2025: Weights, *, alpha: float) -> dict[str, float]:
    """Return ``(1-alpha)*census2022 + alpha*newborn2025`` over union support."""
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError('alpha must be finite and in [0, 1]')
    census = _normalise(census2022, preserve_zeros=True)
    newborn = _normalise(newborn2025, preserve_zeros=True)
    result = {name: (1 - alpha) * census.get(name, 0.0) + alpha * newborn.get(name, 0.0) for name in set(census) | set(newborn)}
    return _normalise(result, preserve_zeros=True)


def derive_national_marginal(uf_distributions: Mapping[str, Weights], official_populations: Mapping[str, int]) -> dict[str, float]:
    """Population-weight UF distributions into a precomputed national marginal."""
    if not uf_distributions or set(uf_distributions) != set(official_populations):
        raise ValueError('national marginal needs matching UF distributions and official populations')
    if any(population <= 0 for population in official_populations.values()):
        raise ValueError('official UF populations must be positive')
    distributions = {uf: _normalise(values, preserve_zeros=True) for uf, values in uf_distributions.items()}
    population = sum(official_populations.values())
    support = set().union(*(set(values) for values in distributions.values()))
    result = {
        name: math.fsum(official_populations[uf] * distributions[uf].get(name, 0.0) for uf in uf_distributions) / population
        for name in support
    }
    return _normalise(result, preserve_zeros=True)


def combine_empirical_sex_rows(rows: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Aggregate count evidence before casefolding labels in sex priors."""
    combined: dict[str, tuple[int, int]] = {}
    for name, male, female in rows:
        if male < 0 or female < 0:
            raise ValueError('empirical sex counts must be nonnegative')
        key = str(name).casefold()
        previous_male, previous_female = combined.get(key, (0, 0))
        combined[key] = previous_male + int(male), previous_female + int(female)
    return [(name, male, female) for name, (male, female) in combined.items()]


def combine_sex_priors(rows: list[tuple[str, int, int]]) -> dict[str, dict[str, float]]:
    """Combine case variants by counts, not by overwriting normalized priors."""
    combined = combine_empirical_sex_rows(rows)
    return {
        name: {
            'p_male': male / (male + female) if male + female else 0.0,
            'p_female': female / (male + female) if male + female else 0.0,
        }
        for name, male, female in combined
    }


def apply_national_sex_prior(distribution: Weights, sex_priors: SexPriors, sex: str) -> dict[str, float]:
    """Apply the national IBGE empirical prior and drop unknown-sex rows.

    Unknown/null-sex labels are intentionally retained in unconditioned tables
    and removed only here. The prior is national evidence, never represented as
    UF-specific empirical sex observations.
    """
    selected = sex.upper()
    if selected not in {'M', 'F'}:
        raise ValueError("sex must be 'M' or 'F'")
    key = 'p_male' if selected == 'M' else 'p_female'
    normalized_priors: SexPriors = {}
    for name, prior in sex_priors.items():
        folded = str(name).casefold()
        if folded in normalized_priors:
            raise ValueError('duplicate casefolded sex prior; combine empirical counts before normalization')
        normalized_priors[folded] = prior
    source = _normalise(distribution, preserve_zeros=True)
    conditioned = {name: weight * float(normalized_priors[name][key]) for name, weight in source.items() if name in normalized_priors}
    return _normalise(conditioned, preserve_zeros=True)


def rows_from_weight_table(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Read all labels, retaining zero-mass rows and combining duplicates."""
    result: dict[str, float] = {}
    for row in rows:
        name = str(row['name'])
        result[name] = result.get(name, 0.0) + float(row['weight'])
    return result


_DERIVED_SCHEMA = pa.schema([('name', pa.large_string()), ('count', pa.uint64()), ('weight', pa.float64())])


def _read_weights(path: Path) -> dict[str, float]:
    return rows_from_weight_table(pq.read_table(path, columns=['name', 'weight']).to_pylist())


def _write_distribution(directory: Path, distribution: Weights, metadata: dict[str, Any]) -> None:
    values = _normalise(distribution, preserve_zeros=True)
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    directory.mkdir(parents=True, exist_ok=True)
    # Derived probabilities cannot in general be represented by source counts.
    # Zero counts deliberately force PartitionStore to use the exact float64
    # weights instead of rounding the blend into synthetic integers.
    table = pa.Table.from_pylist([{'name': name, 'count': 0, 'weight': weight} for name, weight in ordered], schema=_DERIVED_SCHEMA)
    pq.write_table(table, directory / 'part.parquet', compression='zstd', use_dictionary=['name'])
    write_json(directory / 'data_origin.json', metadata | {'rows': len(ordered)})


def build_cohorts(
    parquet_root: Path,
    locations_path: Path,
    *,
    acquired_at_utc: str,
) -> dict[str, Any]:
    """Build all national + 27 UF cohort and sex-conditioned partitions."""
    ibge = parquet_root / 'ibge2022'
    arpen = parquet_root / 'arpen2025'
    tail = _read_weights(ibge / 'historical' / 'period=after2010' / 'part.parquet')
    sex_rows = pq.read_table(ibge / 'sex_prior' / 'scope=national' / 'part.parquet').to_pylist()
    sex_priors = combine_sex_priors([(row['name'], row['count_male'], row['count_female']) for row in sex_rows])
    births = {row['uf']: row['count'] for row in pq.read_table(arpen / 'births' / 'part.parquet').to_pylist()}
    locations = json.loads(locations_path.read_text(encoding='utf-8'))
    populations = {state['state_abbr']: int(state['state_population']) for state in locations['states'].values()}
    if set(populations) != set(UF_CODES) or set(births) != set(UF_CODES) | {'BR'}:
        raise ValueError('cohort derivation requires 27 official UF populations and complete Arpen births')

    output = parquet_root / 'cohorts'
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cohorts-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'cohorts'
        by_cohort: dict[str, dict[str, dict[str, float]]] = {'census2022': {}, 'newborn2025': {}, 'current': {}}
        for uf in UF_CODES:
            census = _read_weights(ibge / 'first_names' / f'uf={uf}' / 'part.parquet')
            simple_rows = pq.read_table(arpen / 'simple' / f'uf={uf}' / 'part.parquet', columns=['name', 'count']).to_pylist()
            observed: Counts = {}
            for row in simple_rows:
                observed[row['name']] = observed.get(row['name'], 0) + row['count']
            newborn = derive_newborn_distribution(observed, births=births[uf], national_post2010=tail)
            alpha = births[uf] / populations[uf]
            current = blend_distributions(census, newborn, alpha=alpha)
            by_cohort['census2022'][uf] = census
            by_cohort['newborn2025'][uf] = newborn
            by_cohort['current'][uf] = current
            observed_mass = math.fsum(row['count'] for row in simple_rows) / births[uf]
            residual = 1.0 - observed_mass
            excluded = {name.casefold() for name in observed}
            remaining_tail = {name: weight for name, weight in _normalise(tail, preserve_zeros=True).items() if name not in excluded}
            tail_coverage = {
                'national_after2010_rows': len(tail),
                'modeled_rows_after_top50_exclusion': len(remaining_tail),
                'normalized_tail_mass_after_exclusion': math.fsum(remaining_tail.values()),
                'top50_labels_absent_from_tail': len(excluded - set(tail)),
            }
            formulas = {
                'census2022': 'p_census2022[i,UF] = IBGE2022_count[i,UF] / sum_i(IBGE2022_count[i,UF])',
                'newborn2025': (
                    'p_observed[i,UF]=Arpen_SIMPLE_count[i,UF]/registrations_uf; '
                    'residual_uf=1-sum_top50(p_observed); '
                    'p_newborn_tail[i,UF]=residual_uf*IBGE_national_after2010[i]/'
                    'sum(IBGE_national_after2010 excluding labels in UF top50); '
                    'top50 labels absent from the tail retain observed mass'
                ),
                'current': (
                    'p_current[i,UF]=(1-alpha_uf)*p_census2022[i,UF]+alpha_uf*p_newborn2025[i,UF]; alpha_uf=registrations_uf/population_uf'
                ),
            }
            for cohort, distribution in by_cohort.items():
                metadata: dict[str, Any] = {
                    'source': 'ibge2022+arpen2025+pop2026',
                    'acquired_at_utc': acquired_at_utc,
                    'cohort': cohort,
                    'uf': uf,
                    'scope': 'UF',
                    'formula': formulas[cohort],
                    'simple_only': True,
                    'simple_only_decision': (
                        'Only Arpen SIMPLE atomic first-name rows are observed newborn inputs; ALL and COMPOUND remain separate artifacts.'
                    ),
                    'registrations_uf': births[uf],
                    'population_uf': populations[uf],
                    'population_denominator': 'IBGE official POP2026 UF population, including the explicit MT source-only municipality',
                    'alpha': alpha,
                    'observed_top50_mass': observed_mass,
                    'residual_mass': residual,
                    'tail_scope': 'national_after2010',
                    'tail_coverage': tail_coverage,
                    'provenance': 'Deterministic normalized float64 derivation; no UF post-2010 history is inferred.',
                    'limitations': [
                        'The IBGE after2010 tail is national 2011-2020 evidence, not UF-observed post2010 data.',
                        'Arpen top50 is incomplete; residual mass is modeled, not observed by name.',
                        'No compound string or middle-name incidence is introduced.',
                    ],
                }
                directory = staged / f'cohort={cohort}' / f'uf={uf}'
                _write_distribution(directory, distribution[uf], metadata)
                base_metadata = metadata
                for sex in ('M', 'F'):
                    conditioned = apply_national_sex_prior(distribution[uf], sex_priors, sex)
                    _write_distribution(
                        directory / f'sex={sex}',
                        conditioned,
                        base_metadata
                        | {
                            'sex': sex,
                            'formula': base_metadata['formula']
                            + f'; conditioned p[i] ∝ p_cohort[i,UF]*national_IBGE_p_{sex}[i], null-sex omitted, renormalized',
                            'sex_prior_scope': 'national IBGE 2022 empirical counts; not UF empirical observations',
                        },
                    )

        for cohort, uf_values in by_cohort.items():
            national = derive_national_marginal(uf_values, populations)
            metadata = {
                'source': 'ibge2022+arpen2025+pop2026',
                'acquired_at_utc': acquired_at_utc,
                'cohort': cohort,
                'scope': 'national',
                'formula': f'p_{cohort}_national[i]=sum_UF(p_{cohort}[i,UF]*official_POP2026_population[UF])/national_POP2026_total',
                'simple_only': True,
                'simple_only_decision': 'National marginal of SIMPLE-only UF newborn models; no compound or middle-name inference.',
                'population_denominator': 'Sum of 27 official IBGE POP2026 UF populations',
                'population_national': sum(populations.values()),
                'alpha': None,
                'registrations_uf': None,
                'population_uf': None,
                'observed_top50_mass': None,
                'residual_mass': None,
                'tail_scope': 'national_after2010 through each UF newborn model',
                'tail_coverage': {'national_population': sum(populations.values()), 'uf_partitions': 27},
                'provenance': 'Precomputed official-population-weighted UF marginal; Arpen registrations never select state.',
                'limitations': ['The newborn residual tail is modeled from national after2010, not UF-observed post2010 data.'],
            }
            directory = staged / f'cohort={cohort}' / 'scope=national'
            _write_distribution(directory, national, metadata)
            for sex in ('M', 'F'):
                _write_distribution(
                    directory / f'sex={sex}',
                    apply_national_sex_prior(national, sex_priors, sex),
                    metadata
                    | {
                        'sex': sex,
                        'formula': metadata['formula']
                        + f'; conditioned p[i] ∝ p_national[i]*national_IBGE_p_{sex}[i], null-sex omitted, renormalized',
                        'sex_prior_scope': 'national IBGE 2022 empirical counts',
                    },
                )
        destination = output
        backup = output.with_name('cohorts.previous')
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.replace(backup)
        try:
            staged.replace(destination)
        except Exception:
            if backup.exists():
                backup.replace(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    return {'cohorts': 3, 'cohort_ufs': 27, 'cohort_tail_scope': 'national_after2010'}

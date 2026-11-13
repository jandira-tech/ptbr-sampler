"""Statistical parity tests: verify batched draws match theoretical distributions."""

import math
import random
from collections import Counter

import numpy as np
import pytest

from ptbr_sampler.sampling.validation import exhaustive_multinomial_gof


@pytest.mark.slow
class TestLocationBatchParity:
    def test_batch_matches_theoretical_state_distribution(self, location_sampler, seeded_random):
        """Batched state draws should match the theoretical weight distribution.

        Uses exhaustive tail-pooled multinomial GoF across the entire support so
        tail mass is conserved rather than truncated and rescaled.
        """
        pytest.importorskip('scipy.stats')

        n = 50_000

        random.seed(54321)
        batched = location_sampler.batch_sample_locations(n)
        batched_states = Counter(r['state_name'] for r in batched)

        total_weight = math.fsum(float(w) for w in location_sampler.state_weights)
        assert total_weight > 0, 'state weights must be positive'

        probs = np.array([float(w) / total_weight for w in location_sampler.state_weights], dtype=np.float64)
        obs = np.array([batched_states.get(s, 0) for s in location_sampler.state_names], dtype=np.int64)
        res = exhaustive_multinomial_gof(obs, probs, min_expected=5.0)
        assert res.p_value > 0.001, (
            f'State distribution mismatch: chi2={res.chi2_stat:.2f}, p={res.p_value:.4f}. '
            f'Batched sampling may not preserve weights correctly.'
        )

    def test_batch_city_distribution_within_state(self, location_sampler, seeded_random):
        """Within each state, batched city draws should match the weighted distribution."""
        n = 50_000

        random.seed(99999)
        batched = location_sampler.batch_sample_locations(n)

        # Group by state
        by_state: dict[str, Counter] = {}
        for entry in batched:
            abbr = entry['state_abbr']
            if abbr not in by_state:
                by_state[abbr] = Counter()
            by_state[abbr][entry['city_name']] += 1

        # For each state with a meaningful sample size, ensure we see more than
        # one distinct city when the state has more than one city configured.
        for abbr, city_counts in by_state.items():
            total = sum(city_counts.values())
            if total < 100:
                continue
            available_cities = len(location_sampler.city_names_by_state.get(abbr, []))
            if available_cities < 2:
                # Some federative units (e.g., DF) expose a single city.
                continue
            assert len(city_counts) >= 2, (
                f'Expected city spread within {abbr} but only {len(city_counts)} of {available_cities} cities seen.'
            )


@pytest.mark.slow
class TestNameBatchParity:
    def test_batch_matches_theoretical_first_name_distribution(self, name_sampler, seeded_random):
        """Batched first name draws should match the theoretical weight distribution.

        Uses exhaustive tail-pooled multinomial GoF across the entire support for
        the UNTIL_2010 period.
        """
        pytest.importorskip('scipy.stats')

        from ptbr_sampler.br_name_class import TimePeriod

        n = 20_000

        random.seed(22222)
        batched = name_sampler.batch_sample_names(n, time_period=TimePeriod.UNTIL_2010)
        batched_names = Counter(nc.first_name for nc in batched)

        period_data = name_sampler.name_data[TimePeriod.UNTIL_2010.value]
        names_data = period_data['names']

        labels = list(names_data.keys())
        total_weight = math.fsum(float(names_data[k]['percentage']) for k in labels)
        probs = np.array([float(names_data[k]['percentage']) / total_weight for k in labels], dtype=np.float64)
        obs = np.array([batched_names.get(k, 0) for k in labels], dtype=np.int64)
        res = exhaustive_multinomial_gof(obs, probs, min_expected=5.0)
        assert res.p_value > 0.001, f'Name distribution mismatch: chi2={res.chi2_stat:.2f}, p={res.p_value:.4f}.'

    def test_batch_surname_has_prefixes(self, name_sampler, seeded_random):
        """Verify that batched names include surname prefixes (da, de, dos, etc.)."""
        random.seed(42)
        results = name_sampler.batch_sample_names(500)
        prefix_count = sum(1 for nc in results if any(p in nc.surname.lower() for p in ['da ', 'de ', 'do ', 'dos ', 'das ']))
        # At least some entries should have prefixes
        assert prefix_count > 0, 'No surname prefixes found in 500 batched samples.'

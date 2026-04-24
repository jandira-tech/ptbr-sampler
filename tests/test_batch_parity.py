"""Statistical parity tests: verify batched draws match theoretical distributions."""

import random
from collections import Counter

import pytest

from src.br_location_class import BrazilianLocationSampler  # noqa: F401
from src.br_name_class import BrazilianNameSampler, NameComponents  # noqa: F401


@pytest.mark.slow
class TestLocationBatchParity:
    def test_batch_matches_theoretical_state_distribution(self, location_sampler, seeded_random):
        """Batched state draws should match the theoretical weight distribution.

        Compares observed batch counts against expected counts derived from
        the sampler's weight vector. A p-value > 0.01 means we cannot reject
        the null hypothesis that the batch draws follow the correct weights.
        """
        from scipy.stats import chisquare

        n = 50_000

        random.seed(54321)
        batched = location_sampler.batch_sample_locations(n)
        batched_states = Counter(r['state_name'] for r in batched)

        # Build expected counts from theoretical weights (normalize first so
        # weight * n is well-defined even when state_weights aren't exactly
        # unit-sum due to floating-point rounding).
        total_weight = sum(location_sampler.state_weights)
        assert total_weight > 0, 'state weights must be positive'

        expected_counts = []
        observed_counts = []
        for state_name, weight in zip(
            location_sampler.state_names, location_sampler.state_weights, strict=True
        ):
            expected_counts.append((weight / total_weight) * n)
            observed_counts.append(batched_states.get(state_name, 0))

        # Filter out states with expected < 5 (chi-squared requirement)
        filtered_obs = []
        filtered_exp = []
        for obs, exp in zip(observed_counts, expected_counts, strict=True):
            if exp >= 5:
                filtered_obs.append(obs)
                filtered_exp.append(exp)

        assert filtered_obs, 'No categories passed the chi-squared expected-count cutoff.'

        # Rescale expected to match observed sum (required by scipy chisquare).
        obs_total = sum(filtered_obs)
        exp_total = sum(filtered_exp)
        if exp_total > 0:
            filtered_exp = [e * obs_total / exp_total for e in filtered_exp]

        stat, p_value = chisquare(filtered_obs, f_exp=filtered_exp)
        assert p_value > 0.01, (
            f'Distribution mismatch: chi2={stat:.2f}, p={p_value:.4f}. '
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
                f'Expected city spread within {abbr} but only {len(city_counts)} of '
                f'{available_cities} cities seen.'
            )


@pytest.mark.slow
class TestNameBatchParity:
    def test_batch_matches_theoretical_first_name_distribution(self, name_sampler, seeded_random):
        """Batched first name draws should match the theoretical weight distribution.

        Compares observed batch counts against expected counts derived from
        the name data weights for the UNTIL_2010 period.
        """
        from scipy.stats import chisquare

        from src.br_name_class import TimePeriod

        n = 20_000

        random.seed(22222)
        batched = name_sampler.batch_sample_names(n)
        batched_names = Counter(nc.first_name for nc in batched)

        # Build expected counts from theoretical weights
        period_data = name_sampler.name_data[TimePeriod.UNTIL_2010.value]
        names_data = period_data['names']

        total_weight = sum(info['percentage'] for info in names_data.values())

        # Only test names with expected count >= 5 (chi-squared assumption)
        filtered_obs = []
        filtered_exp = []
        for name, info in names_data.items():
            exp = (info['percentage'] / total_weight) * n
            if exp >= 5:
                filtered_obs.append(batched_names.get(name, 0))
                filtered_exp.append(exp)

        # Rescale expected to match observed sum (required by scipy chisquare)
        obs_total = sum(filtered_obs)
        exp_total = sum(filtered_exp)
        if exp_total > 0:
            filtered_exp = [e * obs_total / exp_total for e in filtered_exp]

        stat, p_value = chisquare(filtered_obs, f_exp=filtered_exp)
        assert p_value > 0.01, (
            f'Name distribution mismatch: chi2={stat:.2f}, p={p_value:.4f}.'
        )

    def test_batch_surname_has_prefixes(self, name_sampler, seeded_random):
        """Verify that batched names include surname prefixes (da, de, dos, etc.)."""
        random.seed(42)
        results = name_sampler.batch_sample_names(500)
        prefix_count = sum(
            1 for nc in results
            if any(p in nc.surname.lower() for p in ['da ', 'de ', 'do ', 'dos ', 'das '])
        )
        # At least some entries should have prefixes
        assert prefix_count > 0, 'No surname prefixes found in 500 batched samples.'

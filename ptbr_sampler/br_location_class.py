import json
import logging
import random
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)


class BrazilianLocationSampler:
    """Brazilian location sampling class for generating realistic location data."""

    VALID_UFS: frozenset[str] = frozenset(
        {
            'AC',
            'AL',
            'AM',
            'AP',
            'BA',
            'CE',
            'DF',
            'ES',
            'GO',
            'MA',
            'MG',
            'MS',
            'MT',
            'PA',
            'PB',
            'PE',
            'PI',
            'PR',
            'RJ',
            'RN',
            'RO',
            'RR',
            'RS',
            'SC',
            'SE',
            'SP',
            'TO',
        }
    )

    def __init__(self, json_file_path: str | Path | dict):
        """Initialize the sampler with population data from JSON files or a dict.

        Args:
            json_file_path: Path to main JSON file with population data, or
                a pre-loaded dictionary with the same structure.

        Raises:
            ValueError: If required data is missing or invalid
            FileNotFoundError: If JSON files cannot be found
        """
        if isinstance(json_file_path, dict):
            self.data = json_file_path
        else:
            with Path(json_file_path).open(encoding='utf-8') as file:
                self.data = json.load(file)

        # Ensure we have required data
        if not self.data.get('cities') or not self.data.get('states'):
            raise ValueError("Missing 'cities' or 'states' data in JSON file")

        # Pre-calculate weights for more efficient sampling
        self._calculate_weights()

    def update_cities(self, cities_data: dict) -> None:
        """Update the cities data and recalculate weights.

        This method allows updating the cities data after initialization,
        which is useful when loading custom location data.

        Args:
            cities_data: Dictionary containing city data to update or add

        Raises:
            TypeError: If cities_data is not a valid dictionary
        """
        if not isinstance(cities_data, dict):
            raise TypeError('cities_data must be a dictionary')

        # Update the cities data
        if cities_data:
            self.data['cities'].update(cities_data)

        # Recalculate weights to ensure proper sampling
        self._calculate_weights()

    def update_states(self, states_data: dict) -> None:
        """Update the states data and recalculate weights.

        This method allows updating the states data after initialization,
        which is useful when loading custom location data.

        Args:
            states_data: Dictionary containing state data to update or add

        Raises:
            TypeError: If states_data is not a valid dictionary
        """
        if not isinstance(states_data, dict):
            raise TypeError('states_data must be a dictionary')

        # Update the states data
        if states_data:
            self.data['states'].update(states_data)

        # Recalculate weights to ensure proper sampling
        self._calculate_weights()

    def _calculate_weights(self) -> None:
        """Pre-calculate weights for states and cities based on population percentages."""
        # Calculate state weights
        self.state_weights = []
        self.state_names = []

        for state_name, state_data in self.data['states'].items():
            self.state_names.append(state_name)
            self.state_weights.append(state_data['population_percentage'])

        # Normalize state weights to sum to 1
        total_weight = sum(self.state_weights)
        self.state_weights = [w / total_weight for w in self.state_weights]

        # Calculate city weights per state
        self.city_weights_by_state = {}
        self.city_names_by_state = {}
        self.city_data_by_name = {}

        for city_data in self.data['cities'].values():
            state = city_data['city_uf']
            city_name = city_data['city_name']

            if state not in self.city_weights_by_state:
                self.city_weights_by_state[state] = []
                self.city_names_by_state[state] = []

            self.city_names_by_state[state].append(city_name)
            self.city_weights_by_state[state].append(city_data['population_percentage_state'])
            self.city_data_by_name[city_name] = city_data

        # Normalize city weights within each state
        for state in self.city_weights_by_state:
            total = sum(self.city_weights_by_state[state])
            if total > 0:
                self.city_weights_by_state[state] = [w / total for w in self.city_weights_by_state[state]]

        # Build reverse lookup: state abbreviation -> full state name
        self.abbr_to_name: dict[str, str] = {data['state_abbr']: name for name, data in self.data['states'].items()}

    @staticmethod
    def normalize_uf(uf: str | None) -> str | None:
        """Validate and uppercase an optional two-letter Brazilian UF code."""
        if uf is None:
            return None
        if not isinstance(uf, str):
            raise TypeError(f'uf must be a two-letter string or None; got {type(uf).__name__}')
        cleaned = uf.strip().upper()
        if cleaned not in BrazilianLocationSampler.VALID_UFS:
            raise ValueError(f'Unknown UF abbreviation: {uf!r}')
        return cleaned

    def _resolve_uf(self, uf: str | None) -> str | None:
        uf_norm = self.normalize_uf(uf)
        if uf_norm is not None and uf_norm not in self.abbr_to_name:
            raise ValueError(f'UF {uf_norm!r} is not present in loaded location data')
        return uf_norm

    def get_state(
        self,
        random_mode: bool = False,
        *,
        uf: str | None = None,
        rng: random.Random | None = None,
    ) -> tuple[str, str]:
        """Get a random state weighted by population percentage.

        Args:
            random_mode: When ``True``, ignore population weights and pick
                uniformly across the 27 UFs.
            uf: Optional fixed UF abbreviation (e.g. ``'SP'``).
            rng: Optional ``random.Random`` instance; defaults to module ``random``.

        Returns:
            Tuple of (state_name, state_abbreviation)
        """
        uf_norm = self._resolve_uf(uf)
        if uf_norm is not None:
            return self.abbr_to_name[uf_norm], uf_norm
        r = rng if rng is not None else random
        weights = None if random_mode else self.state_weights
        state_name = r.choices(self.state_names, weights=weights, k=1)[0]
        state_abbr = self.data['states'][state_name]['state_abbr']
        return state_name, state_abbr

    def get_city(
        self,
        state_abbr: str | None = None,
        random_mode: bool = False,
        *,
        rng: random.Random | None = None,
    ) -> tuple[str, str]:
        """Get a random city weighted by population percentage."""
        r = rng if rng is not None else random
        if state_abbr is None:
            if rng is None:
                _, state_abbr = self.get_state(random_mode=random_mode)
            else:
                _, state_abbr = self.get_state(random_mode=random_mode, rng=rng)
        else:
            state_abbr = state_abbr.strip().upper()

        if state_abbr not in self.city_weights_by_state:
            raise ValueError(f'No cities found for state: {state_abbr}')

        weights = None if random_mode else self.city_weights_by_state[state_abbr]
        city_name = r.choices(self.city_names_by_state[state_abbr], weights=weights, k=1)[0]

        return city_name, state_abbr

    def get_state_and_city(
        self,
        random_mode: bool = False,
        *,
        uf: str | None = None,
        rng: random.Random | None = None,
    ) -> tuple[str, str, str]:
        """Get a random state and city combination weighted by population percentage."""
        state_kwargs: dict[str, object] = {'random_mode': random_mode}
        if uf is not None:
            state_kwargs['uf'] = uf
        if rng is not None:
            state_kwargs['rng'] = rng
        state_name, state_abbr = self.get_state(**state_kwargs)  # type: ignore[arg-type]
        if rng is None:
            city_name, _ = self.get_city(state_abbr, random_mode=random_mode)
        else:
            city_name, _ = self.get_city(state_abbr, random_mode=random_mode, rng=rng)
        return state_name, state_abbr, city_name

    def batch_sample_locations(
        self,
        n: int,
        random_mode: bool = False,
        *,
        uf: str | None = None,
        rng: random.Random | None = None,
    ) -> list[dict[str, str]]:
        """Draw n location samples with batched random calls."""
        uf_norm = self._resolve_uf(uf)
        if n <= 0:
            return []
        r = rng if rng is not None else random

        if uf_norm is not None:
            state_name = self.abbr_to_name[uf_norm]
            if uf_norm in self.city_names_by_state:
                city_weights = None if random_mode else self.city_weights_by_state[uf_norm]
                cities = r.choices(
                    self.city_names_by_state[uf_norm],
                    weights=city_weights,
                    k=n,
                )
            else:
                logger.warning(
                    "No cities found for state '%s' (%s); emitting 'Unknown' for %d draw(s).",
                    state_name,
                    uf_norm,
                    n,
                )
                cities = ['Unknown'] * n
            return [
                {
                    'state_name': state_name,
                    'state_abbr': uf_norm,
                    'city_name': city_name,
                }
                for city_name in cities
            ]

        # Stage 1: batch-draw all states (self.state_names holds full names)
        state_weights = None if random_mode else self.state_weights
        drawn_state_names = r.choices(self.state_names, weights=state_weights, k=n)

        # Map full names to abbreviations for city lookup
        state_abbr_map = {name: self.data['states'][name]['state_abbr'] for name in set(drawn_state_names)}

        # Stage 2: count per-state, batch-draw cities
        state_name_counts = Counter(drawn_state_names)
        city_draws: dict[str, list[str]] = {}

        for state_name, count in state_name_counts.items():
            abbr = state_abbr_map[state_name]
            if abbr in self.city_names_by_state:
                city_weights = None if random_mode else self.city_weights_by_state[abbr]
                city_draws[state_name] = r.choices(
                    self.city_names_by_state[abbr],
                    weights=city_weights,
                    k=count,
                )
            else:
                logger.warning(
                    "No cities found for state '%s' (%s); emitting 'Unknown' for %d draw(s).",
                    state_name,
                    abbr,
                    count,
                )
                city_draws[state_name] = ['Unknown'] * count

        # Stage 3: reassemble in original order
        state_idx: dict[str, int] = dict.fromkeys(state_name_counts, 0)
        results: list[dict[str, str]] = []

        for state_name in drawn_state_names:
            abbr = state_abbr_map[state_name]
            city_name = city_draws[state_name][state_idx[state_name]]
            state_idx[state_name] += 1
            results.append(
                {
                    'state_name': state_name,
                    'state_abbr': abbr,
                    'city_name': city_name,
                }
            )

        return results

    def _get_random_cep_for_city(
        self,
        city_name: str,
        *,
        rng: random.Random | None = None,
    ) -> str:
        """Generate random CEP from city's available CEPs or CEP range."""
        if city_name not in self.city_data_by_name:
            raise ValueError(f'City not found: {city_name}')

        r = rng if rng is not None else random
        city_data = self.city_data_by_name[city_name]

        # Try using specific CEPs first
        if city_data.get('ceps'):
            return r.choice(city_data['ceps'])

        # Fall back to generating from CEP range if available.
        if city_data.get('cep_range_begins') and city_data.get('cep_range_ends'):
            range_start = int(city_data['cep_range_begins'].replace('-', ''))
            range_end = int(city_data['cep_range_ends'].replace('-', ''))
            # Always zero-pad to 8 digits so leading zeros aren't lost when
            # the numeric range straddles value<10_000_000 (e.g., starts "01").
            return f'{r.randint(range_start, range_end):08d}'

    def _format_cep(self, cep: str, with_dash: bool = True) -> str:
        """Format CEP string with optional dash."""
        cep = cep.replace('-', '')
        return f'{cep[:5]}-{cep[5:]}' if with_dash else cep

    def format_full_location(
        self,
        city: str,
        state: str,
        state_abbr: str,
        include_cep: bool = True,
        cep_without_dash: bool = False,
        name: str | None = None,
        *,
        rng: random.Random | None = None,
    ) -> str:
        """Format location information into a single string."""
        base = f'{city}, {state} ({state_abbr})'
        if not include_cep:
            return base

        parts = [base]

        if include_cep:
            cep = self._get_random_cep_for_city(city, rng=rng)
            formatted_cep = self._format_cep(cep, not cep_without_dash)
            parts.append(formatted_cep)

        return ', '.join(parts)

    def get_random_location(
        self,
        city_only: bool = False,
        state_abbr_only: bool = False,
        state_full_only: bool = False,
        only_cep: bool = False,
        cep_without_dash: bool = False,
        random_mode: bool = False,
        *,
        uf: str | None = None,
        rng: random.Random | None = None,
    ) -> str:
        """Get a random location with various formatting options."""
        uf_norm = self._resolve_uf(uf)
        state_kwargs: dict[str, object] = {'random_mode': random_mode}
        if uf_norm is not None:
            state_kwargs['uf'] = uf_norm
        if rng is not None:
            state_kwargs['rng'] = rng

        city_kwargs: dict[str, object] = {'random_mode': random_mode}
        if rng is not None:
            city_kwargs['rng'] = rng

        if only_cep:
            city_name, _ = self.get_city(uf_norm, **city_kwargs)  # type: ignore[arg-type]
            cep = self._get_random_cep_for_city(city_name, rng=rng)
            return self._format_cep(cep, not cep_without_dash)

        if state_abbr_only:
            return self.get_state(**state_kwargs)[1]  # type: ignore[arg-type]

        if state_full_only:
            return self.get_state(**state_kwargs)[0]  # type: ignore[arg-type]

        if city_only:
            return self.get_city(uf_norm, **city_kwargs)[0]  # type: ignore[arg-type]

        state_name, state_abbr, city_name = self.get_state_and_city(**state_kwargs)  # type: ignore[arg-type]
        return self.format_full_location(
            city_name,
            state_name,
            state_abbr,
            True,
            cep_without_dash,
            rng=rng,
        )

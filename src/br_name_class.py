"""Brazilian name sampler backed by Walker/Vose alias tables.

The public API (``get_random_name``, ``get_random_surname``,
``batch_sample_names``) is unchanged. Internally, draws that previously
routed through ``random.choices`` now go through :class:`AliasTable`, giving
O(1) per-draw cost regardless of support size. The batch and single-sample
paths share one draw implementation — the only difference is ``k``.

Reproducibility: the alias tables draw from a NumPy ``Generator`` seeded
from Python's ``random`` module on each call, so callers that rely on
``random.seed(...)`` continue to get deterministic output.
"""

import json
import random
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.sampling.alias import AliasTable
from src.sampling.store import alias_from_mapping


class TimePeriod(str, Enum):
    """Time periods available in the dataset."""

    UNTIL_1930 = 'ate1930'
    UNTIL_1940 = 'ate1940'
    UNTIL_1950 = 'ate1950'
    UNTIL_1960 = 'ate1960'
    UNTIL_1970 = 'ate1970'
    UNTIL_1980 = 'ate1980'
    UNTIL_1990 = 'ate1990'
    UNTIL_2000 = 'ate2000'
    UNTIL_2010 = 'ate2010'


@dataclass(slots=True)
class NameComponents:
    """Structure to hold the components of a Brazilian name."""

    first_name: str
    middle_name: str | None
    surname: str


def _rng_from_python_random() -> np.random.Generator:
    """Return a NumPy ``Generator`` seeded from Python's ``random`` state.

    Tying NumPy reproducibility to the stdlib ``random`` module keeps
    existing tests that do ``random.seed(n)`` deterministic, while letting
    the alias tables operate on vectorised NumPy arrays.
    """
    return np.random.default_rng(random.getrandbits(64))


class BrazilianNameSampler:
    # Dictionary mapping surnames to their prefixes and weights.
    SURNAME_PREFIXES = {
        'SANTOS': [('dos', 0.85), ('de', 0.05)],
        'SILVA': [('da', 0.85), ('e', 0.05)],
        'NASCIMENTO': [('do', 0.9)],
        'COSTA': [('da', 0.9)],
        'SOUZA': [('de', 0.8)],
        'SOUSA': [('de', 0.8)],
        'OLIVEIRA': [('de', 0.8)],
        'JESUS': [('de', 0.8)],
        'PEREIRA': [('da', 0.6)],
        'FERREIRA': [('da', 0.6)],
        'LIMA': [('de', 0.6)],
        'CARVALHO': [('de', 0.6)],
        'RIBEIRO': [('do', 0.6)],
    }

    def __init__(
        self,
        json_file_path: str | Path | dict,
        middle_names_path: str | Path | None = None,
        names_path: str | Path | None = None,
    ):
        """Initialize the name sampler with population data.

        Args:
            json_file_path: Path to JSON file or pre-loaded data dictionary
                with surname data.
            middle_names_path: Path to middle names JSON file.
            names_path: Path to first names JSON file.
        """
        if isinstance(json_file_path, (str, Path)):
            with Path(json_file_path).open(encoding='utf-8') as file:
                data = json.load(file)
        else:
            data = json_file_path

        if names_path:
            with Path(names_path).open(encoding='utf-8') as file:
                names_data = json.load(file)
                self.name_data = names_data['common_names_percentage']
        else:
            self.name_data = data['common_names_percentage']

        if 'surnames' not in data:
            raise ValueError("Missing 'surnames' data")

        self.surname_data = data['surnames']
        self.top_40_surnames = data['surnames'].get('top_40', {})

        self.middle_names_data = (
            self._load_middle_names(middle_names_path) if middle_names_path else None
        )
        self._validate_data()

        # Alias-table caches. Built lazily on first use so construction
        # cost (~a few ms per period) is paid only if the period is drawn.
        self._first_name_alias: dict[str, AliasTable | None] = {}
        self._surname_alias: AliasTable | None = None
        self._top_40_alias: AliasTable | None = None
        self._middle_name_alias: AliasTable | None = None

    # ------------------------------------------------------------------
    # Data loading / validation
    # ------------------------------------------------------------------

    def _load_middle_names(self, path: str | Path) -> dict[str, Any]:
        with Path(path).open(encoding='utf-8') as file:
            data = json.load(file)
            if 'second_names' not in data or 'percentage_with_second' not in data:
                raise ValueError('Missing required fields in middle names file')
            return data

    def _validate_data(self) -> None:
        for period in TimePeriod:
            if period.value not in self.name_data:
                raise ValueError(f'Missing data for time period: {period.value}')

            period_data = self.name_data[period.value]
            if 'names' not in period_data:
                raise ValueError(f'Missing names data for time period: {period.value}')

            if not isinstance(period_data['names'], dict):
                raise TypeError(
                    f'Invalid names data format for time period: {period.value}'
                )

        if not isinstance(self.surname_data, dict):
            raise TypeError('Invalid surname data format')

        if self.middle_names_data:
            required_keys = {'second_names', 'percentage_with_second'}
            if not required_keys.issubset(self.middle_names_data.keys()):
                raise ValueError(
                    'Invalid middle names data structure. Missing required keys.'
                )

            second_names = self.middle_names_data['second_names']
            if not isinstance(second_names, dict):
                raise TypeError(
                    "Invalid middle names data structure. 'second_names' must be a dictionary"
                )

            if not second_names:
                raise ValueError("Middle names data contains no entries in 'second_names'")

            for name, data in second_names.items():
                required_keys = {'count', 'percentage'}
                if not required_keys.issubset(data.keys()):
                    raise ValueError(
                        f'Invalid middle name entry structure for {name}. Missing required keys.'
                    )

    # ------------------------------------------------------------------
    # Lazy alias-table builders
    # ------------------------------------------------------------------

    def _first_names_table(self, time_period: TimePeriod) -> AliasTable:
        key = time_period.value
        cached = self._first_name_alias.get(key)
        if cached is not None:
            return cached
        period_data = self.name_data[key]
        table = alias_from_mapping(period_data['names'])
        self._first_name_alias[key] = table
        return table

    def _surnames_table(self) -> AliasTable:
        if self._surname_alias is None:
            source = {k: v for k, v in self.surname_data.items() if k != 'top_40'}
            self._surname_alias = alias_from_mapping(source)
        return self._surname_alias

    def _top_40_table(self) -> AliasTable:
        if self._top_40_alias is None:
            if not self.top_40_surnames:
                # Fall back to full table so downstream code never crashes.
                return self._surnames_table()
            self._top_40_alias = alias_from_mapping(self.top_40_surnames)
        return self._top_40_alias

    def _middle_names_table(self) -> AliasTable | None:
        if self._middle_name_alias is not None:
            return self._middle_name_alias
        if not self.middle_names_data:
            return None
        second_names = self.middle_names_data.get('second_names', {})
        try:
            table = alias_from_mapping(second_names)
        except ValueError:
            return None
        self._middle_name_alias = table
        return table

    # ------------------------------------------------------------------
    # Middle-name helpers
    # ------------------------------------------------------------------

    def _should_add_middle_name(self) -> bool:
        if not self.middle_names_data:
            return False
        return random.random() < (self.middle_names_data['percentage_with_second'] / 100)

    def _get_random_middle_name(self) -> str:
        """Return one middle name draw using the cached alias table.

        Kept as a compatibility shim so callers and tests that reach into
        this method continue to work.
        """
        if not self.middle_names_data or 'second_names' not in self.middle_names_data:
            return ''
        try:
            for _name, data in self.middle_names_data['second_names'].items():
                # Surface malformed entries the same way the legacy loop did
                # (``percentage`` missing raised ``KeyError`` which became a
                # ``ValueError`` at the outer boundary).
                _ = data['percentage']
            table = self._middle_names_table()
        except (KeyError, ValueError, TypeError) as err:
            raise ValueError(f'Error processing middle names data: {err}') from err
        if table is None:
            return ''
        rng = _rng_from_python_random()
        return str(table.sample(1, rng)[0])

    # ------------------------------------------------------------------
    # Public draw API
    # ------------------------------------------------------------------

    def get_random_name(
        self,
        time_period: TimePeriod = TimePeriod.UNTIL_2010,
        raw: bool = False,
        include_surname: bool = True,
        top_40: bool = False,
        with_only_one_surname: bool = False,
        always_middle: bool = False,
        only_middle: bool = False,
        return_components: bool = False,
    ) -> str | NameComponents:
        """Get a single random name. Delegates to the unified batch path
        with ``k=1`` so the batch and single-sample code paths share one
        vectorised alias lookup.
        """
        if only_middle:
            middle_name = self._get_random_middle_name()
            if return_components:
                return NameComponents('', middle_name, '')
            return middle_name.upper() if raw else middle_name

        components = self._draw(
            1,
            time_period=time_period,
            raw=raw,
            include_surname=include_surname,
            top_40=top_40,
            with_only_one_surname=with_only_one_surname,
            always_middle=always_middle,
        )[0]

        if return_components:
            return components

        parts: list[str] = [components.first_name]
        if components.middle_name:
            parts.append(components.middle_name)
        if include_surname and components.surname:
            parts.append(components.surname)
        return ' '.join(parts)

    def batch_sample_names(
        self,
        n: int,
        time_period: TimePeriod = TimePeriod.UNTIL_2010,
        raw: bool = False,
        include_surname: bool = True,
        top_40: bool = False,
        with_only_one_surname: bool = False,
        always_middle: bool = False,
    ) -> list[NameComponents]:
        """Draw ``n`` name components with one vectorised alias lookup per
        independent draw (first names, middle names, two surnames).

        The only difference between ``batch_sample_names(1)`` and
        ``get_random_name(..., return_components=True)`` is the return type
        (a one-element list vs. a single ``NameComponents``).
        """
        if n <= 0:
            return []
        return self._draw(
            n,
            time_period=time_period,
            raw=raw,
            include_surname=include_surname,
            top_40=top_40,
            with_only_one_surname=with_only_one_surname,
            always_middle=always_middle,
        )

    def get_random_surname(
        self,
        top_40: bool = False,
        raw: bool = False,
        with_only_one_surname: bool = False,
    ) -> str:
        """Get random surname(s), optionally from top 40 only."""
        rng = _rng_from_python_random()
        table = self._top_40_table() if top_40 else self._surnames_table()
        draws = table.sample(2, rng)
        surname1 = str(draws[0])
        surname2 = str(draws[1])
        return self._assemble_surname(
            surname1,
            surname2,
            raw=raw,
            with_only_one_surname=with_only_one_surname,
        )

    # ------------------------------------------------------------------
    # Unified draw
    # ------------------------------------------------------------------

    def _draw(
        self,
        n: int,
        *,
        time_period: TimePeriod,
        raw: bool,
        include_surname: bool,
        top_40: bool,
        with_only_one_surname: bool,
        always_middle: bool,
    ) -> list[NameComponents]:
        rng = _rng_from_python_random()

        first_table = self._first_names_table(time_period)
        first_draws = first_table.sample(n, rng)
        first_names = [
            (str(name).upper() if raw else str(name)) for name in first_draws
        ]

        middle_names: list[str | None] = self._draw_middle_names(
            n, raw=raw, always_middle=always_middle, rng=rng
        )

        if not include_surname:
            return [
                NameComponents(first_names[i], middle_names[i], '') for i in range(n)
            ]

        surname_table = self._top_40_table() if top_40 else self._surnames_table()
        surname_draws_a = surname_table.sample(n, rng)
        if with_only_one_surname:
            surname_draws_b: np.ndarray | None = None
        else:
            surname_draws_b = surname_table.sample(n, rng)

        results: list[NameComponents] = []
        for i in range(n):
            s1 = str(surname_draws_a[i])
            s2 = str(surname_draws_b[i]) if surname_draws_b is not None else ''
            surname = self._assemble_surname(
                s1,
                s2,
                raw=raw,
                with_only_one_surname=with_only_one_surname,
            )
            results.append(NameComponents(first_names[i], middle_names[i], surname))
        return results

    def _draw_middle_names(
        self,
        n: int,
        *,
        raw: bool,
        always_middle: bool,
        rng: np.random.Generator,
    ) -> list[str | None]:
        middle_names: list[str | None] = [None] * n
        if not self.middle_names_data:
            return middle_names
        table = self._middle_names_table()
        if table is None:
            return middle_names

        if always_middle:
            draws = table.sample(n, rng)
            for i, name in enumerate(draws):
                s = str(name)
                middle_names[i] = s.upper() if raw else s
            return middle_names

        threshold = float(self.middle_names_data['percentage_with_second']) / 100.0
        decisions = [random.random() < threshold for _ in range(n)]
        need = sum(decisions)
        if need == 0:
            return middle_names
        draws = table.sample(need, rng)
        j = 0
        for i in range(n):
            if decisions[i]:
                s = str(draws[j])
                middle_names[i] = s.upper() if raw else s
                j += 1
        return middle_names

    # ------------------------------------------------------------------
    # Surname assembly
    # ------------------------------------------------------------------

    def _assemble_surname(
        self,
        surname1: str,
        surname2: str,
        *,
        raw: bool,
        with_only_one_surname: bool,
    ) -> str:
        s1 = surname1.upper() if raw else surname1
        s1 = self._apply_prefix(s1, allow_prefix=True)
        if with_only_one_surname:
            return s1
        s2 = surname2.upper() if raw else surname2
        if s2.upper() in ('JUNIOR', 'JR'):
            s2 = 'JR' if raw else 'Jr.'
        else:
            s2 = self._apply_prefix(s2, allow_prefix=False)
        return f'{s1} {s2}'

    def _apply_prefix(self, surname: str, allow_prefix: bool = True) -> str:
        """Apply prefix to surname based on complex rules and probabilities.

        Uses ``random.random`` to stay compatible with tests that seed the
        standard library RNG. The alias tables produce the surname stems;
        this pass only decorates them.
        """
        if not allow_prefix:
            return surname
        is_raw = surname.isupper()
        surname_upper = surname.upper()

        if surname_upper in self.SURNAME_PREFIXES:
            if surname_upper in ['SANTOS', 'SILVA']:
                compound_chance = random.random()
                if compound_chance < 0.05:
                    compound_prefix = 'E' if is_raw else 'e'
                    return f'{surname} {compound_prefix}'
                if compound_chance < 0.15:
                    compound_prefix = (
                        ('DA' if random.random() < 0.7 else 'DO')
                        if is_raw
                        else ('da' if random.random() < 0.7 else 'do')
                    )
                    return f'{surname} {compound_prefix}'

            prefix_options = self.SURNAME_PREFIXES[surname_upper]
            total_weight = sum(weight for _, weight in prefix_options)
            rand = random.random() * total_weight

            cumulative = 0
            for candidate_prefix, weight in prefix_options:
                cumulative += weight
                if rand <= cumulative:
                    final_prefix = candidate_prefix
                    if final_prefix in ['da', 'do'] and random.random() < 0.08:
                        final_prefix = (
                            ('DOS' if final_prefix == 'do' else 'DAS')
                            if is_raw
                            else ('dos' if final_prefix == 'do' else 'das')
                        )
                    elif (
                        final_prefix == 'de'
                        and surname[0].lower() in 'aeiou'
                        and random.random() < 0.7
                    ):
                        final_prefix = "D'" if is_raw else "d'"
                        return f'{final_prefix}{surname}'
                    else:
                        final_prefix = final_prefix.upper() if is_raw else final_prefix

                    return f'{final_prefix} {surname}'

        return surname

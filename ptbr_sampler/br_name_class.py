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
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore, alias_from_mapping

_DEFAULT_PARQUET_ROOT = Path(__file__).resolve().parent / 'data' / 'parquet'


def _alias_draw(table: AliasTable, n: int, rng: np.random.Generator, *, random_mode: bool) -> np.ndarray:
    """``n`` indices from ``table``: uniform over its support in random mode, else weighted."""
    return table.sample_uniform(n, rng) if random_mode else table.sample(n, rng)


class TimePeriod(StrEnum):
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
    SURNAME_PREFIXES: ClassVar[dict[str, list[tuple[str, float]]]] = {
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

    @classmethod
    def from_bundled_parquet(
        cls,
        middle_names_path: str | Path | None = None,
        surnames_path: str | Path | None = None,
        names_path: str | Path | None = None,
        lru_size: int = 32,
    ) -> 'BrazilianNameSampler':
        """Construct a sampler wired to the bundled partitioned Parquet tree.

        The JSON files are still used to seed ``surname_data`` /
        ``name_data`` / ``middle_names_data`` dicts (the public attributes
        a couple of tests introspect), but every alias table comes from
        Parquet via :class:`PartitionStore`. This is what
        :func:`ptbr_sampler.sampler.sample` uses by default.
        """
        data_dir = Path(__file__).resolve().parent / 'data'
        surnames_file = Path(surnames_path) if surnames_path else data_dir / 'surnames_data.json'
        names_file = Path(names_path) if names_path else data_dir / 'names_data.json'
        middle_file = Path(middle_names_path) if middle_names_path else data_dir / 'middle_names.json'

        with surnames_file.open(encoding='utf-8') as f:
            surnames_payload = json.load(f)
        with names_file.open(encoding='utf-8') as f:
            names_payload = json.load(f)

        combined = {'surnames': surnames_payload['surnames']}
        combined.update(names_payload)

        return cls(
            combined,
            middle_names_path=middle_file if middle_file.exists() else None,
            names_path=None,
            parquet_root=_DEFAULT_PARQUET_ROOT,
            lru_size=lru_size,
        )

    def __init__(
        self,
        json_file_path: str | Path | dict,
        middle_names_path: str | Path | None = None,
        names_path: str | Path | None = None,
        parquet_root: str | Path | None = None,
        lru_size: int = 32,
    ):
        """Initialize the name sampler with population data.

        The alias tables can be served from **either**:

        * the partitioned Parquet layout under ``parquet_root`` (preferred
          for production — see :meth:`from_bundled_parquet` and
          ``docs/architecture.md``), or
        * the legacy in-memory dicts (used by unit tests that pass bespoke
          mock data and by callers that haven't migrated).

        When ``parquet_root`` is given and the partition file for a
        requested condition exists, it takes precedence. Otherwise the JSON
        dict is consulted. This keeps every ``mock_name_data`` test working
        without forcing Parquet on callers that didn't ask for it.

        Args:
            json_file_path: Path to JSON file or pre-loaded data dictionary
                with surname data.
            middle_names_path: Path to middle names JSON file.
            names_path: Path to first names JSON file.
            parquet_root: Root of the partitioned Parquet layout. ``None``
                disables Parquet entirely and forces the JSON path.
            lru_size: Upper bound on how many Parquet partitions are kept
                resident in the alias-table cache.
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

        self.middle_names_data = self._load_middle_names(middle_names_path) if middle_names_path else None
        self._validate_data()

        # Alias-table caches. Built lazily on first use so construction
        # cost (~a few ms per period) is paid only if the period is drawn.
        self._first_name_alias: dict[str, AliasTable | None] = {}
        # UF x period x sex caches: distinct from the period-only cache because
        # the on-disk partition path differs and keys are (uf, period, sex).
        self._first_name_uf_sex_alias: dict[tuple[str, str, str], AliasTable | None] = {}
        # Period x sex caches (national, full long tail). Populated when the
        # parquet/first_names/period=<P>/sex=<S>/ partitions exist (built from
        # IBGE Nomes percentages * brasil.io/genero-nomes sex prior; see
        # docs/data-origins.md).
        self._first_name_period_sex_alias: dict[tuple[str, str], AliasTable | None] = {}
        self._surname_alias: AliasTable | None = None
        self._top_40_alias: AliasTable | None = None
        self._middle_name_alias: AliasTable | None = None

        # Wire the partitioned Parquet store. The store is consulted before
        # the legacy JSON path — this is the change that actually puts the
        # Parquet layout on the critical path of every draw. Opt-in: pass
        # ``parquet_root`` explicitly (or use :meth:`from_bundled_parquet`).
        self.parquet_root: Path | None = None
        self._partition_store: PartitionStore | None = None
        if parquet_root is not None:
            candidate_root = Path(parquet_root)
            if candidate_root.exists():
                self.parquet_root = candidate_root
                self._partition_store = PartitionStore(max_entries=lru_size)

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
                raise TypeError(f'Invalid names data format for time period: {period.value}')

        if not isinstance(self.surname_data, dict):
            raise TypeError('Invalid surname data format')

        if self.middle_names_data:
            required_keys = {'second_names', 'percentage_with_second'}
            if not required_keys.issubset(self.middle_names_data.keys()):
                raise ValueError('Invalid middle names data structure. Missing required keys.')

            second_names = self.middle_names_data['second_names']
            if not isinstance(second_names, dict):
                raise TypeError("Invalid middle names data structure. 'second_names' must be a dictionary")

            if not second_names:
                raise ValueError("Middle names data contains no entries in 'second_names'")

            for name, data in second_names.items():
                required_keys = {'count', 'percentage'}
                if not required_keys.issubset(data.keys()):
                    raise ValueError(f'Invalid middle name entry structure for {name}. Missing required keys.')

    # ------------------------------------------------------------------
    # Lazy alias-table builders
    # ------------------------------------------------------------------

    def _load_from_parquet(self, spec: PartitionSpec) -> AliasTable | None:
        """Load an alias table from a Parquet partition if the store is live."""
        if self._partition_store is None:
            return None
        try:
            return self._partition_store.get(spec)
        except (FileNotFoundError, ValueError):
            # Partition missing from disk — fall back to the JSON path.
            return None
        except RuntimeError as err:
            if 'pyarrow is required to load partitions' not in str(err):
                raise
            return None

    def _first_names_table(
        self,
        time_period: TimePeriod,
        uf: str | None = None,
        sex: str | None = None,
    ) -> AliasTable:
        """Return the first-name alias table for a given conditioning tuple.

        Resolution order (most-specific wins, falls back on partition miss):

        1. ``parquet_root/first_names/uf=<UF>/period=<P>/sex=<S>/`` — used
           when both ``uf`` and ``sex`` are provided AND the partition
           file exists. Built from the IBGE Nomes v2 ranking endpoint
           (top-20 only); narrow but UF-realistic.
        2. ``parquet_root/first_names/period=<P>/sex=<S>/`` — period-x-sex
           national, full long tail. Built from
           ``names_data.json`` percentages * brasil.io/genero-nomes
           sex prior. Used when ``sex`` is provided alone, or as the
           back-fill when (1) is missing.
        3. ``parquet_root/first_names/period=<P>/`` — the existing
           period-only Parquet partition, populated from
           ``names_data.json`` by ``scripts.ingest_to_parquet``.
        4. The legacy in-memory ``names_data.json`` mapping — exercised
           only by unit tests that override the distribution.
        """
        period_key = time_period.value

        if uf is not None and sex is not None and self.parquet_root is not None:
            cache_key = (uf, period_key, sex)
            cached_uf = self._first_name_uf_sex_alias.get(cache_key)
            if cached_uf is not None:
                return cached_uf
            spec = PartitionSpec.of(
                self.parquet_root / 'first_names',
                uf=uf,
                period=period_key,
                sex=sex,
            )
            table = self._load_from_parquet(spec)
            if table is not None:
                self._first_name_uf_sex_alias[cache_key] = table
                return table
            # Cache the negative result — there's no point re-stat'ing the
            # same missing partition for every draw of this period.
            self._first_name_uf_sex_alias[cache_key] = None

        if sex is not None and self.parquet_root is not None:
            ps_key = (period_key, sex)
            cached_ps = self._first_name_period_sex_alias.get(ps_key)
            if cached_ps is not None:
                return cached_ps
            spec = PartitionSpec.of(
                self.parquet_root / 'first_names',
                period=period_key,
                sex=sex,
            )
            table = self._load_from_parquet(spec)
            if table is not None:
                self._first_name_period_sex_alias[ps_key] = table
                return table
            self._first_name_period_sex_alias[ps_key] = None

        cached = self._first_name_alias.get(period_key)
        if cached is not None:
            return cached

        if self.parquet_root is not None:
            spec = PartitionSpec.of(self.parquet_root / 'first_names', period=period_key)
            table = self._load_from_parquet(spec)
            if table is not None:
                self._first_name_alias[period_key] = table
                return table

        # JSON fallback — the legacy path, still exercised by tests that pass
        # bespoke ``mock_name_data`` dictionaries without a Parquet tree.
        period_data = self.name_data[period_key]
        table = alias_from_mapping(period_data['names'])
        self._first_name_alias[period_key] = table
        return table

    def _surnames_table(self) -> AliasTable:
        if self._surname_alias is not None:
            return self._surname_alias

        if self.parquet_root is not None:
            spec = PartitionSpec.of(self.parquet_root / 'surnames', scope='national')
            table = self._load_from_parquet(spec)
            if table is not None:
                self._surname_alias = table
                return table

        source = {k: v for k, v in self.surname_data.items() if k != 'top_40'}
        self._surname_alias = alias_from_mapping(source)
        return self._surname_alias

    def _top_40_table(self) -> AliasTable:
        if self._top_40_alias is not None:
            return self._top_40_alias
        # No Parquet partition for ``top_40`` — it's a convenience subset that
        # lives alongside the JSON data.
        if not self.top_40_surnames:
            return self._surnames_table()
        self._top_40_alias = alias_from_mapping(self.top_40_surnames)
        return self._top_40_alias

    def _middle_names_table(self) -> AliasTable | None:
        if self._middle_name_alias is not None:
            return self._middle_name_alias

        if self.parquet_root is not None:
            spec = PartitionSpec(root=self.parquet_root / 'middle_names', filters=())
            table = self._load_from_parquet(spec)
            if table is not None:
                self._middle_name_alias = table
                return table

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

    def _get_random_middle_name(self, random_mode: bool = False) -> str:
        """Return one middle name draw using the cached alias table.

        Kept as a compatibility shim so callers and tests that reach into
        this method continue to work.
        """
        if not self.middle_names_data or 'second_names' not in self.middle_names_data:
            return ''
        try:
            table = self._middle_names_table()
        except (KeyError, ValueError, TypeError) as err:
            raise ValueError(f'Error processing middle names data: {err}') from err
        if table is None:
            return ''
        rng = _rng_from_python_random()
        draws = _alias_draw(table, 1, rng, random_mode=random_mode)
        return str(draws[0])

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
        random_mode: bool = False,
        uf: str | None = None,
        sex: str | None = None,
    ) -> str | NameComponents:
        """Get a single random name. Delegates to the unified batch path
        with ``k=1`` so the batch and single-sample code paths share one
        vectorised alias lookup.

        Args:
            random_mode: When ``True``, draw uniformly from the support
                instead of honouring the empirical frequency weights. This is
                the explicit-random escape hatch documented in the README.
                Default ``False`` keeps the realism-by-default behaviour.
            uf: Federation Unit abbreviation (e.g. ``'SP'``). When passed
                together with ``sex`` and a matching Parquet partition
                exists, the first-name draw is conditioned on
                ``(uf, period, sex)``. When the partition is missing, the
                sampler falls back to the period-only table — so this
                argument is safe to pass even when the IBGE Nomes v2 raw
                data has not been ingested yet.
            sex: Either ``'M'`` or ``'F'``. Same fallback behaviour as
                ``uf``.
        """
        if only_middle:
            middle_name = self._get_random_middle_name(random_mode=random_mode)
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
            random_mode=random_mode,
            uf=uf,
            sex=sex,
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
        random_mode: bool = False,
        ufs: list[str] | tuple[str, ...] | None = None,
        sexes: list[str] | tuple[str, ...] | None = None,
    ) -> list[NameComponents]:
        """Draw ``n`` name components with one vectorised alias lookup per
        independent draw (first names, middle names, two surnames).

        The only difference between ``batch_sample_names(1)`` and
        ``get_random_name(..., return_components=True)`` is the return type
        (a one-element list vs. a single ``NameComponents``).

        Args:
            random_mode: When ``True``, draw uniformly from each table
                instead of honouring the empirical frequencies. Default
                ``False`` keeps the realism-by-default behaviour.
            ufs: Per-row UF list. When provided alongside ``sexes`` (and
                with matching ``(uf, period, sex)`` Parquet partitions on
                disk), each first-name draw is conditioned on its row's
                UF / sex. Falls back to the period-only table when a
                partition is missing.
            sexes: Per-row sex list (``'M'``/``'F'``). Used together with
                ``ufs``.
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
            random_mode=random_mode,
            ufs=ufs,
            sexes=sexes,
        )

    def get_random_surname(
        self,
        top_40: bool = False,
        raw: bool = False,
        with_only_one_surname: bool = False,
        random_mode: bool = False,
    ) -> str:
        """Get random surname(s), optionally from top 40 only.

        Args:
            random_mode: When ``True``, draw surnames uniformly across the
                table instead of using empirical frequencies.
        """
        rng = _rng_from_python_random()
        table = self._top_40_table() if top_40 else self._surnames_table()
        draws = _alias_draw(table, 2, rng, random_mode=random_mode)
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
        random_mode: bool = False,
        uf: str | None = None,
        sex: str | None = None,
        ufs: list[str] | tuple[str, ...] | None = None,
        sexes: list[str] | tuple[str, ...] | None = None,
    ) -> list[NameComponents]:
        rng = _rng_from_python_random()

        # Normalise the per-row UF / sex inputs. Accepts either scalar
        # ``uf``/``sex`` (broadcast to every row) or per-row ``ufs`` / ``sexes``.
        first_names = self._draw_first_names_conditioned(
            n,
            time_period=time_period,
            raw=raw,
            random_mode=random_mode,
            rng=rng,
            uf=uf,
            sex=sex,
            ufs=ufs,
            sexes=sexes,
        )

        middle_names: list[str | None] = self._draw_middle_names(
            n,
            raw=raw,
            always_middle=always_middle,
            rng=rng,
            random_mode=random_mode,
        )

        if not include_surname:
            return [NameComponents(first_names[i], middle_names[i], '') for i in range(n)]

        surname_table = self._top_40_table() if top_40 else self._surnames_table()
        surname_draws_a = _alias_draw(surname_table, n, rng, random_mode=random_mode)
        if with_only_one_surname:
            surname_draws_b: np.ndarray | None = None
        else:
            surname_draws_b = _alias_draw(surname_table, n, rng, random_mode=random_mode)

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

    def _draw_first_names_conditioned(
        self,
        n: int,
        *,
        time_period: TimePeriod,
        raw: bool,
        random_mode: bool,
        rng: np.random.Generator,
        uf: str | None,
        sex: str | None,
        ufs: list[str] | tuple[str, ...] | None,
        sexes: list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        """Draw ``n`` first names, optionally conditioned on per-row UF / sex.

        When neither per-row nor scalar UF / sex are provided (or no
        Parquet partition matches), every draw goes through the unconditioned
        period table — this is the legacy fast path and matches the
        existing behaviour bit-for-bit on the bundled (period-only) data.
        """
        per_row_ufs: list[str | None] | None
        per_row_sexes: list[str | None] | None
        if ufs is None and uf is None and sexes is None and sex is None:
            per_row_ufs = None
            per_row_sexes = None
        else:
            per_row_ufs = list(ufs) if ufs is not None else [uf] * n
            per_row_sexes = list(sexes) if sexes is not None else [sex] * n
            if len(per_row_ufs) != n or len(per_row_sexes) != n:
                raise ValueError('ufs/sexes must have length n')

        # Fast path — single unconditioned table for every row.
        if per_row_ufs is None or per_row_sexes is None:
            table = self._first_names_table(time_period)
            draws = _alias_draw(table, n, rng, random_mode=random_mode)
            return [(str(name).upper() if raw else str(name)) for name in draws]

        # Conditional path — bucket by (uf, sex) and draw per bucket so we
        # still amortise per-call overhead. Rows with missing partitions
        # silently fall back to the period-only table inside
        # ``_first_names_table`` — that's the no-data-yet behaviour.
        from collections import defaultdict  # noqa: PLC0415 - keep imports local to the conditional path

        buckets: dict[tuple[str | None, str | None], list[int]] = defaultdict(list)
        for i in range(n):
            buckets[per_row_ufs[i], per_row_sexes[i]].append(i)

        names_out: list[str] = [''] * n
        for (bucket_uf, bucket_sex), indices in buckets.items():
            table = self._first_names_table(time_period, uf=bucket_uf, sex=bucket_sex)
            count = len(indices)
            draws = _alias_draw(table, count, rng, random_mode=random_mode)
            for j, row_idx in enumerate(indices):
                s = str(draws[j])
                names_out[row_idx] = s.upper() if raw else s
        return names_out

    def _draw_middle_names(
        self,
        n: int,
        *,
        raw: bool,
        always_middle: bool,
        rng: np.random.Generator,
        random_mode: bool = False,
    ) -> list[str | None]:
        middle_names: list[str | None] = [None] * n
        if not self.middle_names_data:
            return middle_names
        table = self._middle_names_table()
        if table is None:
            return middle_names

        def _draw_n(k: int) -> np.ndarray:
            return _alias_draw(table, k, rng, random_mode=random_mode)

        if always_middle:
            draws = _draw_n(n)
            for i, name in enumerate(draws):
                s = str(name)
                middle_names[i] = s.upper() if raw else s
            return middle_names

        # In random mode, the empirical 30.99% inclusion rate is replaced by
        # a flat coin flip — that's the whole point of the escape hatch:
        # ``random=True`` drops realism-oriented assumptions, including the
        # ``percentage_with_second`` documented in the README.
        threshold = 0.5 if random_mode else float(self.middle_names_data['percentage_with_second']) / 100.0
        middle_name_flags = rng.random(n) < threshold
        need = int(np.count_nonzero(middle_name_flags))
        if need == 0:
            return middle_names
        draws = _draw_n(need)
        j = 0
        for i in range(n):
            if middle_name_flags[i]:
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
                    compound_prefix = ('DA' if random.random() < 0.7 else 'DO') if is_raw else ('da' if random.random() < 0.7 else 'do')
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
                        final_prefix = ('DOS' if final_prefix == 'do' else 'DAS') if is_raw else ('dos' if final_prefix == 'do' else 'das')
                    elif final_prefix == 'de' and surname[0].lower() in 'aeiou' and random.random() < 0.7:
                        final_prefix = "D'" if is_raw else "d'"
                        return f'{final_prefix}{surname}'
                    else:
                        final_prefix = final_prefix.upper() if is_raw else final_prefix

                    return f'{final_prefix} {surname}'

        return surname

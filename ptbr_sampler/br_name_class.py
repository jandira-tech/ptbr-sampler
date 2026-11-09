"""Brazilian name sampler backed by Walker/Vose alias tables.

The public API (``get_random_name``, ``get_random_surname``,
``batch_sample_names``) is unchanged. Internally, draws that previously
routed through ``random.choices`` now go through :class:`AliasTable`, giving
O(1) per-draw cost regardless of support size. The batch and single-sample
paths share one draw implementation — the only difference is ``k``.

Reproducibility: alias tables draw from a private NumPy ``Generator`` seeded
from the supplied ``random.Random``-compatible stream. With ``rng=None`` that
is the module-global Python stream, preserving ``random.seed(...)`` behavior.
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


class Cohort(StrEnum):
    """Derived first-name population/newborn distributions."""

    CURRENT = 'current'
    CENSUS2022 = 'census2022'
    NEWBORN2025 = 'newborn2025'


class TimePeriod(StrEnum):
    """Explicit historical first-name periods; ``None`` selects a cohort."""

    UNTIL_1930 = 'ate1930'
    UNTIL_1940 = 'ate1940'
    UNTIL_1950 = 'ate1950'
    UNTIL_1960 = 'ate1960'
    UNTIL_1970 = 'ate1970'
    UNTIL_1980 = 'ate1980'
    UNTIL_1990 = 'ate1990'
    UNTIL_2000 = 'ate2000'
    UNTIL_2010 = 'ate2010'
    UNTIL_2020 = 'ate2020'
    AFTER_2010 = 'after2010'


class TimePeriod2022(StrEnum):
    """Additional national IBGE historical periods (runtime consumers opt in)."""

    UNTIL_2020 = 'until2020'
    AFTER_2010 = 'after2010'


@dataclass(slots=True)
class NameComponents:
    """Structure to hold the components of a Brazilian name."""

    first_name: str
    middle_name: str | None
    surname: str


def _rng_from_python_random(rng: random.Random | None = None) -> np.random.Generator:
    """Seed a private NumPy generator from the selected Python random stream.

    ``None`` deliberately uses the module-global stream for backward-compatible
    ``random.seed(...)`` behavior. NumPy's global RNG is never read or advanced.
    """
    source = random if rng is None else rng
    return np.random.default_rng(source.getrandbits(64))


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

        When ``parquet_root`` is given, cohort and new-period tables are read
        from its Parquet layout regardless of whether it is the bundled root.
        Legacy periods retain their original JSON-compatible lookup order.
        JSON-only fixtures may use their legacy data only for default current
        draws; an explicitly requested modern cohort must be present.

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
        self._cohort_first_name_alias: dict[tuple[str, str, str | None], AliasTable | None] = {}
        self._historical_first_name_alias: dict[tuple[str, str | None], AliasTable | None] = {}
        self._surname_uf_alias: dict[str | None, AliasTable] = {}
        self._top_40_uf_alias: dict[str | None, AliasTable] = {}
        # UF x period x sex caches retained for JSON-era/custom-root compatibility.
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
        self._require_modern_data = False
        if parquet_root is not None:
            candidate_root = Path(parquet_root)
            self._require_modern_data = candidate_root.resolve() == _DEFAULT_PARQUET_ROOT.resolve()
            if self._require_modern_data and not candidate_root.exists():
                raise FileNotFoundError(f'bundled parquet root missing: {candidate_root}')
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
            if period in (TimePeriod.UNTIL_2020, TimePeriod.AFTER_2010):
                continue
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
            if self._require_modern_data:
                # Bundled modern data is contractual: never silently substitute
                # the stale JSON distribution for a missing/corrupt artifact.
                raise
            return None
        except RuntimeError as err:
            if self._require_modern_data or 'pyarrow is required to load partitions' not in str(err):
                raise
            return None

    def _first_names_table(
        self,
        time_period: TimePeriod | str | None = None,
        uf: str | None = None,
        sex: str | None = None,
        cohort: Cohort | str = Cohort.CURRENT,
    ) -> AliasTable:
        """Resolve a cohort or an explicit historical period exactly once.

        Cohort tables are precomputed national/UF marginals, optionally with
        the national IBGE sex prior already applied. Any explicit Parquet root
        supplies these tables; only JSON-only default-current requests retain
        the legacy fallback. Missing selected modern artifacts raise clearly.
        """
        selected_cohort = Cohort(cohort)
        selected_period = TimePeriod(time_period) if time_period is not None else None
        if selected_period is not None and selected_cohort is not Cohort.CURRENT:
            raise ValueError('cohort census2022/newborn2025 cannot be combined with an explicit time_period')
        normalized_sex = sex.upper() if sex is not None else None
        if normalized_sex not in (None, 'M', 'F'):
            raise ValueError("sex must be 'M', 'F', or None")
        normalized_uf = uf.upper() if uf is not None else None

        if selected_period is None:
            period_key = TimePeriod.UNTIL_2010.value
            if self.parquet_root is not None:
                key = (selected_cohort.value, normalized_uf or 'BR', normalized_sex)
                if key in self._cohort_first_name_alias:
                    table = self._cohort_first_name_alias[key]
                    if table is not None:
                        return table
                filters: dict[str, str] = {'cohort': selected_cohort.value}
                filters['scope'] = 'national'
                if normalized_uf:
                    filters = {'cohort': selected_cohort.value, 'uf': normalized_uf}
                    if normalized_sex:
                        filters['sex'] = normalized_sex
                    spec = PartitionSpec.of(self.parquet_root / 'cohorts', **filters)
                else:
                    if normalized_sex:
                        filters['sex'] = normalized_sex
                    spec = PartitionSpec.of(self.parquet_root / 'cohorts', **filters)
                table = self._load_from_parquet(spec)
                self._cohort_first_name_alias[key] = table
                if table is not None:
                    return table
                raise FileNotFoundError(f'missing modern cohort table: cohort={selected_cohort.value}')
        else:
            period_key = selected_period.value
            modern_period = selected_period in (TimePeriod.UNTIL_2020, TimePeriod.AFTER_2010)
            if self._require_modern_data or (self.parquet_root is not None and modern_period):
                historical_key = (period_key, normalized_sex)
                if historical_key in self._historical_first_name_alias:
                    cached = self._historical_first_name_alias[historical_key]
                    if cached is not None:
                        return cached
                historical_period = 'until2020' if selected_period is TimePeriod.UNTIL_2020 else period_key.removeprefix('ate')
                if normalized_sex and selected_period in (TimePeriod.UNTIL_2020, TimePeriod.AFTER_2010):
                    spec = PartitionSpec.of(self.parquet_root / 'ibge2022' / 'historical', period=historical_period, sex=normalized_sex)
                elif normalized_sex:
                    spec = PartitionSpec.of(self.parquet_root / 'first_names', period=period_key, sex=normalized_sex)
                else:
                    spec = PartitionSpec.of(self.parquet_root / 'ibge2022' / 'historical', period=historical_period)
                table = self._load_from_parquet(spec)
                self._historical_first_name_alias[historical_key] = table
                if table is not None:
                    return table
                raise FileNotFoundError(f'missing modern historical table: period={period_key}')

        if selected_period is None and selected_cohort is not Cohort.CURRENT:
            raise ValueError(f'cohort={selected_cohort.value} requires parquet_root with the selected cohort artifact')

        # Legacy periods and custom JSON/Parquet fixtures retain their original
        # condition-specific lookup order. This path never serves bundled data.
        if normalized_uf is not None and normalized_sex is not None and self.parquet_root is not None:
            cache_key = (normalized_uf, period_key, normalized_sex)
            cached_uf = self._first_name_uf_sex_alias.get(cache_key)
            if cached_uf is not None:
                return cached_uf
            spec = PartitionSpec.of(self.parquet_root / 'first_names', uf=normalized_uf, period=period_key, sex=normalized_sex)
            table = self._load_from_parquet(spec)
            if table is not None:
                self._first_name_uf_sex_alias[cache_key] = table
                return table
            self._first_name_uf_sex_alias[cache_key] = None
        if normalized_sex is not None and self.parquet_root is not None:
            ps_key = (period_key, normalized_sex)
            cached_ps = self._first_name_period_sex_alias.get(ps_key)
            if cached_ps is not None:
                return cached_ps
            table = self._load_from_parquet(PartitionSpec.of(self.parquet_root / 'first_names', period=period_key, sex=normalized_sex))
            if table is not None:
                self._first_name_period_sex_alias[ps_key] = table
                return table
            self._first_name_period_sex_alias[ps_key] = None
        cached = self._first_name_alias.get(period_key)
        if cached is not None:
            return cached
        if self.parquet_root is not None:
            table = self._load_from_parquet(PartitionSpec.of(self.parquet_root / 'first_names', period=period_key))
            if table is not None:
                self._first_name_alias[period_key] = table
                return table
        table = alias_from_mapping(self.name_data[period_key]['names'])
        self._first_name_alias[period_key] = table
        return table

    def _surnames_table(self, uf: str | None = None) -> AliasTable:
        normalized_uf = uf.upper() if uf is not None else None
        if normalized_uf in self._surname_uf_alias:
            return self._surname_uf_alias[normalized_uf]
        if self.parquet_root is not None:
            root = self.parquet_root / 'ibge2022' / 'surnames' if self._require_modern_data else self.parquet_root / 'surnames'
            filters = {'uf': normalized_uf} if normalized_uf else {'scope': 'national'}
            table = self._load_from_parquet(PartitionSpec.of(root, **filters))
            if table is None and normalized_uf:
                table = self._load_from_parquet(PartitionSpec.of(root, scope='national'))
            if table is not None:
                self._surname_uf_alias[normalized_uf] = table
                if normalized_uf is None:
                    self._surname_alias = table
                return table
        source = {k: v for k, v in self.surname_data.items() if k != 'top_40'}
        table = alias_from_mapping(source)
        self._surname_uf_alias[normalized_uf] = table
        self._surname_alias = table
        return table

    def _top_40_table(self, uf: str | None = None) -> AliasTable:
        normalized_uf = uf.upper() if uf is not None else None
        if normalized_uf in self._top_40_uf_alias:
            return self._top_40_uf_alias[normalized_uf]
        if self._require_modern_data or (normalized_uf is not None and self.parquet_root is not None):
            full = self._surnames_table(normalized_uf)
            # Stable descending sort preserves source order for tied weights.
            indices = sorted(range(len(full)), key=lambda index: -float(full.weights[index]))[:40]
            table = AliasTable.from_weights([str(full.labels[index]) for index in indices], full.weights[indices])
            self._top_40_uf_alias[normalized_uf] = table
            return table
        if self._top_40_alias is not None:
            return self._top_40_alias
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

    def _should_add_middle_name(self, rng: random.Random | None = None) -> bool:
        if not self.middle_names_data:
            return False
        rng = random if rng is None else rng
        return rng.random() < (self.middle_names_data['percentage_with_second'] / 100)

    def _get_random_middle_name(self, random_mode: bool = False, rng: random.Random | None = None) -> str:
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
        alias_rng = _rng_from_python_random(rng)
        draws = _alias_draw(table, 1, alias_rng, random_mode=random_mode)
        return str(draws[0])

    # ------------------------------------------------------------------
    # Public draw API
    # ------------------------------------------------------------------

    def get_random_name(
        self,
        time_period: TimePeriod | str | None = None,
        cohort: Cohort | str = Cohort.CURRENT,
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
        rng: random.Random | None = None,
    ) -> str | NameComponents:
        """Get a single random name. Delegates to the unified batch path
        with ``k=1`` so the batch and single-sample code paths share one
        vectorised alias lookup.

        Args:
            random_mode: When ``True``, draw uniformly from the support
                instead of honouring the empirical frequency weights. This is
                the explicit-random escape hatch documented in the README.
                Default ``False`` keeps the realism-by-default behaviour.
            time_period: Optional legacy IBGE period, or the new national
                ``UNTIL_2020`` / ``AFTER_2010`` historical distributions.
                The default draws from the cohort selected by ``cohort``.
            cohort: ``current`` blends census2022 and newborn2025;
                ``census2022`` and ``newborn2025`` require no explicit period.
            uf: Federation Unit abbreviation (e.g. ``'SP'``) for a cohort's
                precomputed UF distribution. Historical or JSON-only lookups
                retain their documented legacy sex/UF condition order.
                Missing explicitly selected modern artifacts raise clearly.
            sex: Either ``'M'`` or ``'F'`` for cohort sex conditionals;
                legacy and new national historical periods also accept it.
        """
        if only_middle:
            middle_name = self._get_random_middle_name(random_mode=random_mode, rng=rng)
            if return_components:
                return NameComponents('', middle_name, '')
            return middle_name.upper() if raw else middle_name

        components = self._draw(
            1,
            time_period=time_period,
            cohort=cohort,
            raw=raw,
            include_surname=include_surname,
            top_40=top_40,
            with_only_one_surname=with_only_one_surname,
            always_middle=always_middle,
            random_mode=random_mode,
            uf=uf,
            sex=sex,
            rng=rng,
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
        time_period: TimePeriod | str | None = None,
        cohort: Cohort | str = Cohort.CURRENT,
        raw: bool = False,
        include_surname: bool = True,
        top_40: bool = False,
        with_only_one_surname: bool = False,
        always_middle: bool = False,
        random_mode: bool = False,
        ufs: list[str] | tuple[str, ...] | None = None,
        sexes: list[str] | tuple[str, ...] | None = None,
        rng: random.Random | None = None,
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
            cohort: Selected modern cohort (default ``current``) when no
                explicit ``time_period`` is supplied.
            ufs: Per-row UF list selecting a cohort's precomputed UF
                distribution. Legacy periods retain their custom Parquet
                sex/UF lookup and JSON fallback behavior.
            sexes: Per-row sex list (``'M'``/``'F'``), usable with cohorts,
                legacy periods, and new national historical conditionals.
        """
        if n <= 0:
            return []
        return self._draw(
            n,
            time_period=time_period,
            cohort=cohort,
            raw=raw,
            include_surname=include_surname,
            top_40=top_40,
            with_only_one_surname=with_only_one_surname,
            always_middle=always_middle,
            random_mode=random_mode,
            ufs=ufs,
            sexes=sexes,
            rng=rng,
        )

    def get_random_surname(
        self,
        top_40: bool = False,
        raw: bool = False,
        with_only_one_surname: bool = False,
        random_mode: bool = False,
        uf: str | None = None,
        rng: random.Random | None = None,
    ) -> str:
        """Get random surname(s), optionally from top 40 only.

        Args:
            random_mode: When ``True``, draw surnames uniformly across the
                table instead of using empirical frequencies.
        """
        alias_rng = _rng_from_python_random(rng)
        table = self._top_40_table(uf) if top_40 else self._surnames_table(uf)
        draws = _alias_draw(table, 1 if with_only_one_surname else 2, alias_rng, random_mode=random_mode)
        surname1 = str(draws[0])
        surname2 = '' if with_only_one_surname else str(draws[1])
        return self._assemble_surname(
            surname1,
            surname2,
            raw=raw,
            with_only_one_surname=with_only_one_surname,
            rng=rng,
        )

    # ------------------------------------------------------------------
    # Unified draw
    # ------------------------------------------------------------------

    def _draw(
        self,
        n: int,
        *,
        time_period: TimePeriod | str | None,
        cohort: Cohort | str,
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
        rng: random.Random | None = None,
    ) -> list[NameComponents]:
        alias_rng = _rng_from_python_random(rng)

        # Normalise the per-row UF / sex inputs. Accepts either scalar
        # ``uf``/``sex`` (broadcast to every row) or per-row ``ufs`` / ``sexes``.
        first_names = self._draw_first_names_conditioned(
            n,
            time_period=time_period,
            cohort=cohort,
            raw=raw,
            random_mode=random_mode,
            rng=alias_rng,
            uf=uf,
            sex=sex,
            ufs=ufs,
            sexes=sexes,
        )

        middle_names: list[str | None] = self._draw_middle_names(
            n,
            raw=raw,
            always_middle=always_middle,
            rng=alias_rng,
            random_mode=random_mode,
        )

        if not include_surname:
            return [NameComponents(first_names[i], middle_names[i], '') for i in range(n)]

        row_ufs = list(ufs) if ufs is not None else [uf] * n
        if len(row_ufs) != n:
            raise ValueError('ufs must have length n')
        from collections import defaultdict  # noqa: PLC0415 - only conditional UF batching needs it

        buckets: dict[str | None, list[int]] = defaultdict(list)
        for index, row_uf in enumerate(row_ufs):
            buckets[row_uf.upper() if row_uf is not None else None].append(index)
        surnames_out: list[tuple[str, str | None]] = [('', None)] * n
        for bucket_uf, indices in buckets.items():
            table = self._top_40_table(bucket_uf) if top_40 else self._surnames_table(bucket_uf)
            count = len(indices)
            draws_a = _alias_draw(table, count, alias_rng, random_mode=random_mode)
            draws_b = None if with_only_one_surname else _alias_draw(table, count, alias_rng, random_mode=random_mode)
            for draw_index, row_index in enumerate(indices):
                surnames_out[row_index] = (
                    str(draws_a[draw_index]),
                    str(draws_b[draw_index]) if draws_b is not None else None,
                )

        results: list[NameComponents] = []
        for i in range(n):
            surname1, surname2 = surnames_out[i]
            surname = self._assemble_surname(
                surname1,
                surname2 or '',
                raw=raw,
                with_only_one_surname=with_only_one_surname,
                rng=rng,
            )
            results.append(NameComponents(first_names[i], middle_names[i], surname))
        return results

    def _draw_first_names_conditioned(
        self,
        n: int,
        *,
        time_period: TimePeriod | str | None,
        cohort: Cohort | str,
        raw: bool,
        random_mode: bool,
        rng: np.random.Generator,
        uf: str | None,
        sex: str | None,
        ufs: list[str] | tuple[str, ...] | None,
        sexes: list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        """Draw ``n`` first names, optionally conditioned on per-row UF / sex.

        Unconditioned draws use the selected national cohort/period table.
        Conditional draws resolve their requested partitions explicitly;
        missing bundled modern artifacts raise instead of silently substituting
        a different distribution. Custom historical fixtures retain their
        documented condition-specific resolution order.
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
            table = self._first_names_table(time_period, cohort=cohort)
            draws = _alias_draw(table, n, rng, random_mode=random_mode)
            return [(str(name).upper() if raw else str(name)) for name in draws]

        # Conditional path — bucket by (uf, sex) and draw per bucket so we
        # still amortise per-call overhead. Modern missing partitions raise;
        # custom historical fixtures follow their explicit resolution order.
        from collections import defaultdict  # noqa: PLC0415 - keep imports local to the conditional path

        buckets: dict[tuple[str | None, str | None], list[int]] = defaultdict(list)
        for i in range(n):
            buckets[per_row_ufs[i], per_row_sexes[i]].append(i)

        names_out: list[str] = [''] * n
        for (bucket_uf, bucket_sex), indices in buckets.items():
            table = self._first_names_table(time_period, uf=bucket_uf, sex=bucket_sex, cohort=cohort)
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

        # random=True flattens the selected name support, but does not invent a
        # different incidence model: the corpus-derived 30.99% rate is stable.
        threshold = float(self.middle_names_data['percentage_with_second']) / 100.0
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
        rng: random.Random | None = None,
    ) -> str:
        s1 = surname1.upper() if raw else surname1
        s1 = self._apply_prefix(s1, allow_prefix=True, rng=rng)
        if with_only_one_surname:
            return s1
        s2 = surname2.upper() if raw else surname2
        if s2.upper() in ('JUNIOR', 'JR'):
            s2 = 'JR' if raw else 'Jr.'
        else:
            s2 = self._apply_prefix(s2, allow_prefix=False)
        return f'{s1} {s2}'

    def _apply_prefix(self, surname: str, allow_prefix: bool = True, rng: random.Random | None = None) -> str:
        """Decorate an alias-drawn surname using the selected random stream."""
        if not allow_prefix:
            return surname
        rng = random if rng is None else rng
        is_raw = surname.isupper()
        surname_upper = surname.upper()

        if surname_upper in self.SURNAME_PREFIXES:
            if surname_upper in ['SANTOS', 'SILVA']:
                compound_chance = rng.random()
                if compound_chance < 0.05:
                    compound_prefix = 'E' if is_raw else 'e'
                    return f'{surname} {compound_prefix}'
                if compound_chance < 0.15:
                    compound_prefix = ('DA' if rng.random() < 0.7 else 'DO') if is_raw else ('da' if rng.random() < 0.7 else 'do')
                    return f'{surname} {compound_prefix}'

            prefix_options = self.SURNAME_PREFIXES[surname_upper]
            total_weight = sum(weight for _, weight in prefix_options)
            rand = rng.random() * total_weight

            cumulative = 0
            for candidate_prefix, weight in prefix_options:
                cumulative += weight
                if rand <= cumulative:
                    final_prefix = candidate_prefix
                    if final_prefix in ['da', 'do'] and rng.random() < 0.08:
                        final_prefix = ('DOS' if final_prefix == 'do' else 'DAS') if is_raw else ('dos' if final_prefix == 'do' else 'das')
                    elif final_prefix == 'de' and surname[0].lower() in 'aeiou' and rng.random() < 0.7:
                        final_prefix = "D'" if is_raw else "d'"
                        return f'{final_prefix}{surname}'
                    else:
                        final_prefix = final_prefix.upper() if is_raw else final_prefix

                    return f'{final_prefix} {surname}'

        return surname

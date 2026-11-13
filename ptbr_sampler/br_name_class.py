"""Brazilian name sampler backed by Walker/Vose alias tables.

Supports both IBGE Censo 2022 Nomes no Brasil (default ``census_year=2022``)
and the historical 2010 vintage (``census_year=2010``). Draws route through
:class:`AliasTable` and :class:`PartitionStore`, giving O(1) per-draw cost
regardless of support size and sharing one unified vectorised draw path
across single-sample and batch APIs.

Reproducibility: the alias tables draw from a NumPy ``Generator`` seeded
from Python's ``random`` module on each call, so callers that rely on
``random.seed(...)`` continue to get deterministic output.
"""

import contextlib
import json
import math
import os
import random
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Literal

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ptbr_sampler.datasets import (
    PACKAGE_DATA_DIR,
    ensure_data_file,
    ensure_parquet_root,
    get_revision_cache_dir,
    resolve_partition_path,
)
from ptbr_sampler.sampling.alias import AliasTable
from ptbr_sampler.sampling.store import PartitionSpec, PartitionStore, alias_from_mapping

_DEFAULT_PARQUET_ROOT = Path(__file__).resolve().parent / 'data' / 'parquet'
CENSUS_2022_OBSERVED_MALE_SHARE: float = 92_287_140 / 190_041_904  # 0.4856151515825794
_SEX_PRIOR_FILE_CACHE_MAX = 4
_SEX_PRIOR_FILE_CACHE: OrderedDict[tuple[str, int, int], tuple[pa.Array, np.ndarray, np.ndarray]] = OrderedDict()
_SEX_PRIOR_FILE_CACHE_LOCK = threading.RLock()


def _alias_draw(table: AliasTable, n: int, rng: np.random.Generator, *, random_mode: bool) -> np.ndarray:
    """``n`` indices from ``table``: uniform over its support in random mode, else weighted."""
    return table.sample_uniform(n, rng) if random_mode else table.sample(n, rng)


def _surname_stem_key(surname: str) -> str:
    """Normalise a surname token so duplicate-stem rejection catches Jr./d' variants."""
    key = surname.casefold().lstrip()
    if key.startswith("d'"):
        key = key[2:]
    if key in {'jr', 'jr.'}:
        return 'junior'
    return key


class TimePeriod(StrEnum):
    """Time periods available across the 2022 and 2010 datasets."""

    ALL = 'all'
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
    PERIOD_2020_2022 = '2020_2022'


LEGACY_2010_PERIODS: tuple[TimePeriod, ...] = (
    TimePeriod.UNTIL_1930,
    TimePeriod.UNTIL_1940,
    TimePeriod.UNTIL_1950,
    TimePeriod.UNTIL_1960,
    TimePeriod.UNTIL_1970,
    TimePeriod.UNTIL_1980,
    TimePeriod.UNTIL_1990,
    TimePeriod.UNTIL_2000,
    TimePeriod.UNTIL_2010,
)

CENSUS_2022_SUPPORTED_PERIODS: frozenset[TimePeriod] = frozenset(
    {
        TimePeriod.ALL,
        TimePeriod.UNTIL_1940,
        TimePeriod.UNTIL_1950,
        TimePeriod.UNTIL_1960,
        TimePeriod.UNTIL_1970,
        TimePeriod.UNTIL_1980,
        TimePeriod.UNTIL_1990,
        TimePeriod.UNTIL_2000,
        TimePeriod.UNTIL_2010,
        TimePeriod.UNTIL_2020,
        TimePeriod.PERIOD_2020_2022,
    }
)


def resolve_time_period(time_period: TimePeriod | str | None, census_year: int) -> TimePeriod:
    """Resolve ``None`` to the vintage default and validate supported periods."""
    if census_year == 2010:
        resolved = TimePeriod.UNTIL_2010 if time_period is None else TimePeriod(time_period)
        if resolved not in LEGACY_2010_PERIODS:
            raise ValueError(
                f'time_period={resolved.value!r} is not supported for census_year=2010; '
                f'choose one of {[p.value for p in LEGACY_2010_PERIODS]} or census_year=2022.'
            )
        return resolved
    if census_year == 2022:
        resolved = TimePeriod.ALL if time_period is None else TimePeriod(time_period)
        if resolved not in CENSUS_2022_SUPPORTED_PERIODS:
            raise ValueError(
                f'time_period={resolved.value!r} is not supported for census_year=2022 '
                '(IBGE 2022 merges pre-1930 survivors into decade=1930 / ate1940).'
            )
        return resolved
    raise ValueError(f'census_year must be 2022 or 2010; got {census_year!r}')


@dataclass(slots=True)
class NameComponents:
    """Structure to hold the components of a Brazilian name."""

    first_name: str
    middle_name: str | None
    surname: str


def _rng_from_python_random(py_rng: random.Random | None = None) -> np.random.Generator:
    """Return a NumPy ``Generator`` seeded from ``py_rng`` (or global ``random``)."""
    source = py_rng if py_rng is not None else random
    return np.random.default_rng(source.getrandbits(64))


def _allowed_json_roots() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                os.path.realpath(Path(__file__).resolve().parents[1]),
                os.path.realpath(Path.cwd()),
                os.path.realpath(Path.home()),
                os.path.realpath(tempfile.gettempdir()),
                os.path.realpath(get_revision_cache_dir().parent),
            )
        )
    )


def _validate_local_json_path(raw: str | Path) -> Path:
    """Confine local JSON file paths to allowed roots and reject traversal or non-JSON targets."""
    raw_str = os.fspath(raw)
    if '\x00' in raw_str:
        raise ValueError('Null byte in JSON file path is not allowed')
    raw_path = Path(raw_str)
    if '..' in raw_path.parts:
        raise ValueError(f'Parent-directory traversal ("..") is not allowed in JSON file path: {raw_str}')
    if raw_path.suffix.lower() != '.json':
        raise ValueError(f'Local JSON file path must end with .json: {raw_str}')
    resolved = os.path.realpath(raw_str)
    for root in _allowed_json_roots():
        in_root = resolved == root or resolved.startswith(root + os.sep)
        if not in_root:
            continue
        try:
            if os.path.commonpath([root, resolved]) == root:
                return Path(resolved)
        except ValueError:
            continue
    raise ValueError(f'JSON file path resolves outside allowed roots: {raw_str}')


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
    def from_parquet_root(
        cls,
        parquet_root: str | Path,
        *,
        census_year: int = 2022,
        conditioning_mode: Literal['strict', 'estimated'] = 'strict',
        middle_names_path: str | Path | None = None,
        lru_size: int = 64,
        path_resolver: Callable[[Path], Path] | None = None,
    ) -> 'BrazilianNameSampler':
        """Construct a Parquet-only sampler rooted at ``parquet_root``."""
        root = Path(parquet_root)
        if not root.exists():
            raise FileNotFoundError(f'Parquet root not found: {root}')
        return cls(
            None,
            middle_names_path=middle_names_path,
            names_path=None,
            parquet_root=root,
            lru_size=lru_size,
            census_year=census_year,
            conditioning_mode=conditioning_mode,
            path_resolver=path_resolver,
            preloaded_data={'surnames': {'top_40': {}}, 'common_names_percentage': {}},
        )

    @classmethod
    def from_parquet(
        cls,
        *,
        include_middle_names: bool = True,
        census_year: int = 2022,
        conditioning_mode: Literal['strict', 'estimated'] = 'strict',
        middle_names_path: str | Path | None = None,
        surnames_path: str | Path | None = None,
        lru_size: int = 64,
    ) -> 'BrazilianNameSampler':
        """Construct a sampler backed by runtime-resolved Parquet partitions."""
        resolved_middle: Path | None
        if middle_names_path is not None:
            resolved_middle = _validate_local_json_path(middle_names_path)
        elif include_middle_names:
            resolved_middle = ensure_data_file('middle_names.json')
        else:
            resolved_middle = None

        if census_year == 2022:
            if surnames_path is not None:
                raise ValueError(
                    'surnames_path is supported only with census_year=2010; pass census_year=2010 to use a custom surname file'
                )
            root_2022 = ensure_parquet_root(census_year=2022)
            return cls.from_parquet_root(
                root_2022,
                census_year=2022,
                conditioning_mode=conditioning_mode,
                middle_names_path=resolved_middle,
                lru_size=lru_size,
                path_resolver=resolve_partition_path,
            )
        if census_year != 2010:
            raise ValueError(f'census_year must be 2022 or 2010; got {census_year!r}')
        surnames_file = _validate_local_json_path(surnames_path) if surnames_path else ensure_data_file('surnames_data.json')
        surnames_payload = json.loads(surnames_file.read_text(encoding='utf-8'))
        root_2010 = ensure_parquet_root(census_year=2010)
        return cls(
            None,
            middle_names_path=resolved_middle,
            names_path=None,
            parquet_root=root_2010,
            lru_size=lru_size,
            census_year=2010,
            conditioning_mode=conditioning_mode,
            path_resolver=resolve_partition_path,
            preloaded_data={'surnames': surnames_payload['surnames'], 'common_names_percentage': {}},
        )

    @classmethod
    def from_bundled_parquet(
        cls,
        middle_names_path: str | Path | None = None,
        surnames_path: str | Path | None = None,
        names_path: str | Path | None = None,
        lru_size: int = 64,
        *,
        include_middle_names: bool = True,
        census_year: int = 2022,
        conditioning_mode: Literal['strict', 'estimated'] = 'strict',
    ) -> 'BrazilianNameSampler':
        """Compatibility constructor; defaults to Census 2022 Parquet in ``0.3.0+``."""
        del names_path
        return cls.from_parquet(
            include_middle_names=include_middle_names,
            census_year=census_year,
            conditioning_mode=conditioning_mode,
            middle_names_path=middle_names_path,
            surnames_path=surnames_path,
            lru_size=lru_size,
        )

    def __init__(
        self,
        json_file_path: str | Path | dict[str, Any] | None = None,
        middle_names_path: str | Path | None = None,
        names_path: str | Path | None = None,
        parquet_root: str | Path | None = None,
        lru_size: int = 32,
        *,
        census_year: int = 2010,
        conditioning_mode: Literal['strict', 'estimated'] = 'strict',
        path_resolver: Callable[[Path], Path] | None = resolve_partition_path,
        preloaded_data: dict[str, Any] | None = None,
    ):
        """Initialize the name sampler with population data."""
        if census_year not in {2010, 2022}:
            raise ValueError(f'census_year must be 2022 or 2010; got {census_year!r}')
        if conditioning_mode not in {'strict', 'estimated'}:
            raise ValueError(f"conditioning_mode must be 'strict' or 'estimated'; got {conditioning_mode!r}")

        self.census_year = census_year
        self.conditioning_mode: Literal['strict', 'estimated'] = conditioning_mode
        self._path_resolver: Callable[[Path], Path] | None = path_resolver

        if preloaded_data is not None:
            data = preloaded_data
        elif isinstance(json_file_path, dict):
            data = json_file_path
        elif isinstance(json_file_path, (str, Path)):
            validated_json_path = _validate_local_json_path(json_file_path)
            with validated_json_path.open(encoding='utf-8') as file:
                data = json.load(file)
        else:
            raise TypeError('json_file_path must be a path or dict when preloaded_data is not supplied')

        if names_path:
            validated_names_path = _validate_local_json_path(names_path)
            with validated_names_path.open(encoding='utf-8') as file:
                names_data = json.load(file)
                self.name_data = names_data['common_names_percentage']
        else:
            self.name_data = data['common_names_percentage']

        if 'surnames' not in data:
            raise ValueError("Missing 'surnames' data")

        self.surname_data = data['surnames']
        self.top_40_surnames = data['surnames'].get('top_40', {})

        self.parquet_root: Path | None = None
        self._partition_store: PartitionStore | None = None
        if parquet_root is not None:
            candidate_root = Path(parquet_root)
            if candidate_root.exists():
                self.parquet_root = candidate_root
                self._partition_store = PartitionStore(
                    max_entries=lru_size,
                    path_resolver=path_resolver,
                )

        self._use_shared_middle_parquet = False
        validated_middle_path: Path | None = None
        if middle_names_path is not None:
            validated_middle_path = _validate_local_json_path(middle_names_path)
            default_candidates = {(PACKAGE_DATA_DIR / 'middle_names.json').resolve()}
            env_data_dir = os.environ.get('PTBR_SAMPLER_DATA_DIR')
            if env_data_dir:
                default_candidates.add((Path(env_data_dir).expanduser() / 'middle_names.json').resolve())
            with contextlib.suppress(FileNotFoundError, ValueError):
                default_candidates.add((get_revision_cache_dir() / 'middle_names.json').resolve())
            self._use_shared_middle_parquet = validated_middle_path in default_candidates

        self.middle_names_data = self._load_middle_names(validated_middle_path) if validated_middle_path else None
        self._validate_data()

        # Lazy alias-table caches.
        self._cache_lock = threading.RLock()
        self._first_name_alias: dict[str, AliasTable | None] = {}
        self._first_name_uf_alias: dict[str, AliasTable] = {}
        self._first_name_sex_alias_2022: dict[str, AliasTable] = {}
        self._first_name_uf_sex_alias: dict[tuple[str, str, str], AliasTable | None] = {}
        self._first_name_period_sex_alias: dict[tuple[str, str], AliasTable | None] = {}
        self._estimated_2022_alias: dict[tuple[str, str | None, str], AliasTable] = {}
        self._sex_prior_2022: tuple[pa.Array, np.ndarray, np.ndarray] | None = None
        self._surname_alias: AliasTable | None = None
        self._surname_uf_alias: dict[str, AliasTable] = {}
        self._top_40_alias: AliasTable | None = None
        self._top_40_uf_alias: dict[str, AliasTable] = {}
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
        if self.parquet_root is None or self.name_data:
            for period in LEGACY_2010_PERIODS:
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
        """Load an alias table from a Parquet partition if the store is live (2010 fallback helper)."""
        if self._partition_store is None:
            return None
        try:
            return self._partition_store.get(spec)
        except FileNotFoundError as err:
            if 'PTBR_SAMPLER_OFFLINE' in str(err):
                raise
            return None
        except ValueError:
            return None
        except RuntimeError as err:
            if 'pyarrow is required to load partitions' not in str(err):
                raise
            return None

    def _require_parquet_table(self, spec: PartitionSpec) -> AliasTable:
        """Load a required Census 2022 partition without swallowing errors."""
        if self._partition_store is None:
            raise RuntimeError('Census 2022 sampling requires a Parquet partition store')
        return self._partition_store.get(spec)

    def _load_sex_prior_2022(self) -> tuple[pa.Array, np.ndarray, np.ndarray]:
        with self._cache_lock:
            if self._sex_prior_2022 is not None:
                return self._sex_prior_2022
            if self.parquet_root is None:
                raise RuntimeError('Census 2022 sex prior requires parquet_root')
            raw_path = self.parquet_root / 'sex_prior' / 'scope=national' / 'part.parquet'
            prior_path = (self._path_resolver(raw_path) if self._path_resolver is not None else raw_path).resolve()
            st = prior_path.stat()
            file_key = (str(prior_path), st.st_mtime_ns, st.st_size)
            with _SEX_PRIOR_FILE_CACHE_LOCK:
                cached_prior = _SEX_PRIOR_FILE_CACHE.get(file_key)
                if cached_prior is not None:
                    _SEX_PRIOR_FILE_CACHE.move_to_end(file_key)
                    self._sex_prior_2022 = cached_prior
                    return cached_prior

            tbl = pq.ParquetFile(prior_path).read(columns=['name', 'p_male', 'p_female'], use_threads=False)
            prior_names_pa = tbl['name'].combine_chunks()
            pm_arr = tbl['p_male'].to_numpy(zero_copy_only=False).astype(np.float64, copy=False)
            pf_arr = tbl['p_female'].to_numpy(zero_copy_only=False).astype(np.float64, copy=False)
            loaded = (prior_names_pa, pm_arr, pf_arr)
            with _SEX_PRIOR_FILE_CACHE_LOCK:
                _SEX_PRIOR_FILE_CACHE[file_key] = loaded
                _SEX_PRIOR_FILE_CACHE.move_to_end(file_key)
                while len(_SEX_PRIOR_FILE_CACHE) > _SEX_PRIOR_FILE_CACHE_MAX:
                    _SEX_PRIOR_FILE_CACHE.popitem(last=False)
            self._sex_prior_2022 = loaded
            return loaded

    def _first_names_table_2022(
        self,
        time_period: TimePeriod,
        uf: str | None = None,
        sex: str | None = None,
    ) -> AliasTable:
        resolved = resolve_time_period(time_period, 2022)
        if self.parquet_root is None:
            raise RuntimeError('Census 2022 sampling requires parquet_root')

        if uf is not None and resolved != TimePeriod.ALL:
            raise ValueError(
                'Census 2022 does not provide UF x cohort joint distributions '
                f'(requested uf={uf!r}, time_period={resolved.value!r}). '
                'Use time_period=TimePeriod.ALL for UF conditioning.'
            )

        # 4 directly observed 1D marginals:
        if uf is None and sex is None:
            cached = self._first_name_alias.get(resolved.value)
            if cached is not None:
                return cached
            spec = (
                PartitionSpec.of(self.parquet_root / 'first_names', scope='national')
                if resolved == TimePeriod.ALL
                else PartitionSpec.of(self.parquet_root / 'first_names', period=resolved.value)
            )
            table = self._require_parquet_table(spec)
            self._first_name_alias[resolved.value] = table
            return table

        if uf is None and sex is not None and resolved == TimePeriod.ALL:
            cached_s = self._first_name_sex_alias_2022.get(sex)
            if cached_s is not None:
                return cached_s
            spec = PartitionSpec.of(self.parquet_root / 'first_names', sex=sex)
            table = self._require_parquet_table(spec)
            self._first_name_sex_alias_2022[sex] = table
            return table

        if uf is not None and sex is None and resolved == TimePeriod.ALL:
            cached_u = self._first_name_uf_alias.get(uf)
            if cached_u is not None:
                return cached_u
            spec = PartitionSpec.of(self.parquet_root / 'first_names', uf=uf)
            table = self._require_parquet_table(spec)
            self._first_name_uf_alias[uf] = table
            return table

        # Joint requests (UF x sex or cohort x sex):
        if self.conditioning_mode == 'strict':
            raise ValueError(
                'Census 2022 has no observed joint partition for '
                f'(time_period={resolved.value!r}, uf={uf!r}, sex={sex!r}); '
                "pass conditioning_mode='estimated' to opt into national-sex-prior Bayes reweighting."
            )

        if sex not in {'M', 'F'}:
            raise ValueError(f'Unsupported conditioning combination: time_period={resolved!r}, uf={uf!r}, sex={sex!r}')
        est_key = (resolved.value, uf, sex)
        cached_est = self._estimated_2022_alias.get(est_key)
        if cached_est is not None:
            return cached_est

        base_spec = (
            PartitionSpec.of(self.parquet_root / 'first_names', uf=uf)
            if uf is not None
            else (
                PartitionSpec.of(self.parquet_root / 'first_names', scope='national')
                if resolved == TimePeriod.ALL
                else PartitionSpec.of(self.parquet_root / 'first_names', period=resolved.value)
            )
        )
        cached_base = self._first_name_uf_alias.get(uf) if uf is not None else self._first_name_alias.get(resolved.value)
        if cached_base is None and self._partition_store is not None and base_spec in self._partition_store:
            cached_base = self._partition_store.get(base_spec)

        base_names_pa: pa.Array | None = None
        base_labels: np.ndarray | None = None
        if cached_base is not None:
            base_labels = cached_base.labels
            base_weights = cached_base.weights
        else:
            raw_base = base_spec.path()
            base_path = self._path_resolver(raw_base) if self._path_resolver is not None else raw_base
            if not base_path.exists():
                raise FileNotFoundError(f'partition missing: {base_path}')
            pf_base = pq.ParquetFile(base_path)
            cols_base = set(pf_base.schema_arrow.names)
            want_base = ['name'] + [c for c in ('count', 'weight') if c in cols_base]
            tbl_base = pf_base.read(columns=want_base, use_threads=False)
            base_names_pa = tbl_base.column('name').combine_chunks()
            if 'count' in cols_base:
                counts_f = tbl_base.column('count').to_numpy(zero_copy_only=False).astype(np.float64)
                total_c = math.fsum(counts_f.tolist())
                if total_c > 0.0:
                    base_weights = counts_f / total_c
                elif 'weight' in cols_base:
                    w_raw = tbl_base.column('weight').to_numpy(zero_copy_only=False).astype(np.float64)
                    base_weights = w_raw / math.fsum(w_raw.tolist())
                else:
                    raise ValueError(f'partition at {base_path} has non-positive counts')
            elif 'weight' in cols_base:
                w_raw = tbl_base.column('weight').to_numpy(zero_copy_only=False).astype(np.float64)
                base_weights = w_raw / math.fsum(w_raw.tolist())
            else:
                raise ValueError(f'partition at {base_path} has neither count nor weight column')

        prior_names_pa, pm_arr, pf_arr = self._load_sex_prior_2022()
        p_col = pm_arr if sex == 'M' else pf_arr
        lookup_pa = base_names_pa if base_names_pa is not None else pa.array(base_labels, type=pa.string())
        idx_pa = pc.index_in(lookup_pa, value_set=prior_names_pa)
        valid = ~idx_pa.is_null().to_numpy(zero_copy_only=False)
        idx_arr = pc.fill_null(idx_pa, 0).to_numpy(zero_copy_only=False)
        p_vals = np.where(valid, p_col[idx_arr], 0.0)
        keep = valid & np.isfinite(p_vals) & (p_vals > 0.0)
        if not np.any(keep):
            raise ValueError(f'Empty estimated conditional support for {est_key}')
        kept_labels = (
            pc.filter(base_names_pa, pa.array(keep)).to_numpy(zero_copy_only=False) if base_names_pa is not None else base_labels[keep]  # type: ignore[index]
        )
        est_table = AliasTable.from_weights(kept_labels, base_weights[keep] * p_vals[keep])
        self._estimated_2022_alias[est_key] = est_table
        return est_table

    def _first_names_table(
        self,
        time_period: TimePeriod,
        uf: str | None = None,
        sex: str | None = None,
    ) -> AliasTable:
        """Return the first-name alias table for a given conditioning tuple."""
        with self._cache_lock:
            if self.census_year == 2022:
                return self._first_names_table_2022(time_period, uf=uf, sex=sex)

            resolve_time_period(time_period, 2010)
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

            period_data = self.name_data[period_key]
            table = alias_from_mapping(period_data['names'])
            self._first_name_alias[period_key] = table
            return table

    def _surnames_table(self, uf: str | None = None) -> AliasTable:
        with self._cache_lock:
            if self.census_year == 2022 and uf is not None:
                cached_uf = self._surname_uf_alias.get(uf)
                if cached_uf is not None:
                    return cached_uf
                if self.parquet_root is None:
                    raise RuntimeError('Census 2022 UF surname sampling requires parquet_root')
                spec = PartitionSpec.of(self.parquet_root / 'surnames', uf=uf)
                table = self._require_parquet_table(spec)
                self._surname_uf_alias[uf] = table
                return table

            if self._surname_alias is not None:
                return self._surname_alias

            if self.parquet_root is not None:
                spec = PartitionSpec.of(self.parquet_root / 'surnames', scope='national')
                if self.census_year == 2022:
                    table = self._require_parquet_table(spec)
                    self._surname_alias = table
                    return table
                table_2010 = self._load_from_parquet(spec)
                if table_2010 is not None:
                    self._surname_alias = table_2010
                    return table_2010

            source = {k: v for k, v in self.surname_data.items() if k != 'top_40'}
            self._surname_alias = alias_from_mapping(source)
            return self._surname_alias

    def _top_40_table(self, uf: str | None = None) -> AliasTable:
        with self._cache_lock:
            if self.census_year == 2022 and self.parquet_root is not None and not self.top_40_surnames:
                if uf is not None:
                    cached_uf = self._top_40_uf_alias.get(uf)
                    if cached_uf is not None:
                        return cached_uf
                    top_uf = self._surnames_table(uf=uf).top_k(40)
                    self._top_40_uf_alias[uf] = top_uf
                    return top_uf
                if self._top_40_alias is not None:
                    return self._top_40_alias
                self._top_40_alias = self._surnames_table().top_k(40)
                return self._top_40_alias

            if self._top_40_alias is not None:
                return self._top_40_alias
            if not self.top_40_surnames:
                return self._surnames_table()
            self._top_40_alias = alias_from_mapping(self.top_40_surnames)
            return self._top_40_alias

    def _middle_names_table(self) -> AliasTable | None:
        with self._cache_lock:
            if self._middle_name_alias is not None:
                return self._middle_name_alias

            if self.parquet_root is not None:
                spec = PartitionSpec(root=self.parquet_root / 'middle_names', filters=())
                table = self._load_from_parquet(spec)
                if table is None and self.census_year == 2022 and self._use_shared_middle_parquet:
                    spec_shared = PartitionSpec(root=self.parquet_root.parent / 'middle_names', filters=())
                    table = self._load_from_parquet(spec_shared)
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

    def _should_add_middle_name(
        self,
        *,
        rng: random.Random | None = None,
    ) -> bool:
        if not self.middle_names_data:
            return False
        r = rng if rng is not None else random
        return r.random() < (self.middle_names_data['percentage_with_second'] / 100)

    def _get_random_middle_name(
        self,
        random_mode: bool = False,
        *,
        rng: random.Random | None = None,
    ) -> str:
        """Return one middle name draw using the cached alias table."""
        if not self.middle_names_data or 'second_names' not in self.middle_names_data:
            return ''
        try:
            table = self._middle_names_table()
        except (KeyError, ValueError, TypeError) as err:
            raise ValueError(f'Error processing middle names data: {err}') from err
        if table is None:
            return ''
        np_rng = _rng_from_python_random(rng)
        draws = _alias_draw(table, 1, np_rng, random_mode=random_mode)
        return str(draws[0])

    # ------------------------------------------------------------------
    # Public draw API
    # ------------------------------------------------------------------

    def get_random_name(
        self,
        time_period: TimePeriod | None = None,
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
        *,
        include_middle: bool = True,
        rng: random.Random | None = None,
    ) -> str | NameComponents:
        """Get a single random name via the unified vectorised draw path."""
        if only_middle:
            middle_name = self._get_random_middle_name(random_mode=random_mode, rng=rng)
            if return_components:
                return NameComponents('', middle_name, '')
            return middle_name.upper() if raw else middle_name

        resolved_period = resolve_time_period(time_period, self.census_year)
        components = self._draw(
            1,
            time_period=resolved_period,
            raw=raw,
            include_surname=include_surname,
            include_middle=include_middle,
            top_40=top_40,
            with_only_one_surname=with_only_one_surname,
            always_middle=always_middle,
            random_mode=random_mode,
            uf=uf,
            sex=sex,
            py_rng=rng,
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
        time_period: TimePeriod | None = None,
        raw: bool = False,
        include_surname: bool = True,
        top_40: bool = False,
        with_only_one_surname: bool = False,
        always_middle: bool = False,
        random_mode: bool = False,
        ufs: list[str] | tuple[str, ...] | None = None,
        sexes: list[str] | tuple[str, ...] | None = None,
        *,
        rng: random.Random | None = None,
    ) -> list[NameComponents]:
        """Draw ``n`` name components with vectorised alias lookups."""
        if n <= 0:
            return []
        resolved_period = resolve_time_period(time_period, self.census_year)
        return self._draw(
            n,
            time_period=resolved_period,
            raw=raw,
            include_surname=include_surname,
            top_40=top_40,
            with_only_one_surname=with_only_one_surname,
            always_middle=always_middle,
            random_mode=random_mode,
            ufs=ufs,
            sexes=sexes,
            py_rng=rng,
        )

    def get_random_surname(
        self,
        top_40: bool = False,
        raw: bool = False,
        with_only_one_surname: bool = False,
        random_mode: bool = False,
        uf: str | None = None,
        *,
        rng: random.Random | None = None,
    ) -> str:
        """Get random surname(s), optionally from top 40 or conditioned on UF (2022)."""
        np_rng = _rng_from_python_random(rng)
        table = self._top_40_table(uf=uf) if top_40 else self._surnames_table(uf=uf)
        s1_list, s2_list = self._draw_surname_pairs_from_table(
            table,
            1,
            rng=np_rng,
            random_mode=random_mode,
            with_only_one_surname=with_only_one_surname,
        )
        return self._assemble_surname(
            s1_list[0],
            s2_list[0],
            raw=raw,
            with_only_one_surname=with_only_one_surname,
            py_rng=rng,
        )

    # ------------------------------------------------------------------
    # Unified draw
    # ------------------------------------------------------------------

    def _draw_surname_pairs_from_table(
        self,
        table: AliasTable,
        count: int,
        *,
        rng: np.random.Generator,
        random_mode: bool,
        with_only_one_surname: bool,
    ) -> tuple[list[str], list[str]]:
        draws_a = [str(x) for x in _alias_draw(table, count, rng, random_mode=random_mode)]
        if with_only_one_surname:
            return draws_a, [''] * count

        draws_b = [str(x) for x in _alias_draw(table, count, rng, random_mode=random_mode)]
        if self.census_year == 2022 and len(table) > 1:
            dup_indices = [j for j in range(count) if _surname_stem_key(draws_a[j]) == _surname_stem_key(draws_b[j])]
            rounds = 0
            while dup_indices and rounds < 32:
                redraw = _alias_draw(table, len(dup_indices), rng, random_mode=random_mode)
                for k, j in enumerate(dup_indices):
                    draws_b[j] = str(redraw[k])
                dup_indices = [j for j in dup_indices if _surname_stem_key(draws_a[j]) == _surname_stem_key(draws_b[j])]
                rounds += 1
            if dup_indices:
                for j in dup_indices:
                    key_a = _surname_stem_key(draws_a[j])
                    for candidate in table.labels.tolist():
                        cand_str = str(candidate)
                        if _surname_stem_key(cand_str) != key_a:
                            draws_b[j] = cand_str
                            break
        return draws_a, draws_b

    def _draw(
        self,
        n: int,
        *,
        time_period: TimePeriod,
        raw: bool,
        include_surname: bool,
        include_middle: bool = True,
        top_40: bool,
        with_only_one_surname: bool,
        always_middle: bool,
        random_mode: bool = False,
        uf: str | None = None,
        sex: str | None = None,
        ufs: list[str] | tuple[str, ...] | None = None,
        sexes: list[str] | tuple[str, ...] | None = None,
        py_rng: random.Random | None = None,
    ) -> list[NameComponents]:
        rng = _rng_from_python_random(py_rng)

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

        middle_names: list[str | None] = (
            self._draw_middle_names(
                n,
                raw=raw,
                always_middle=always_middle,
                rng=rng,
                random_mode=random_mode,
            )
            if include_middle
            else [None] * n
        )

        if not include_surname:
            return [NameComponents(first_names[i], middle_names[i], '') for i in range(n)]

        per_row_surname_ufs: list[str | None] | None = None
        if self.census_year == 2022 and (ufs is not None or uf is not None):
            per_row_surname_ufs = list(ufs) if ufs is not None else [uf] * n

        surname_s1 = [''] * n
        surname_s2 = [''] * n
        if per_row_surname_ufs is None:
            surname_table = self._top_40_table() if top_40 else self._surnames_table()
            surname_s1, surname_s2 = self._draw_surname_pairs_from_table(
                surname_table,
                n,
                rng=rng,
                random_mode=random_mode,
                with_only_one_surname=with_only_one_surname,
            )
        else:
            from collections import defaultdict  # noqa: PLC0415

            uf_buckets: dict[str | None, list[int]] = defaultdict(list)
            for i, row_uf in enumerate(per_row_surname_ufs):
                uf_buckets[row_uf].append(i)
            for bucket_uf, indices in sorted(uf_buckets.items(), key=lambda kv: kv[0] or ''):
                surname_table = self._top_40_table(uf=bucket_uf) if top_40 else self._surnames_table(uf=bucket_uf)
                b_s1, b_s2 = self._draw_surname_pairs_from_table(
                    surname_table,
                    len(indices),
                    rng=rng,
                    random_mode=random_mode,
                    with_only_one_surname=with_only_one_surname,
                )
                for j, row_idx in enumerate(indices):
                    surname_s1[row_idx] = b_s1[j]
                    surname_s2[row_idx] = b_s2[j]

        results: list[NameComponents] = []
        for i in range(n):
            surname = self._assemble_surname(
                surname_s1[i],
                surname_s2[i],
                raw=raw,
                with_only_one_surname=with_only_one_surname,
                py_rng=py_rng,
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
        """Draw ``n`` first names, optionally conditioned on per-row UF / sex."""
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

        if per_row_ufs is None or per_row_sexes is None:
            table = self._first_names_table(time_period)
            draws = _alias_draw(table, n, rng, random_mode=random_mode)
            return [(str(name).upper() if raw else str(name)) for name in draws]

        from collections import defaultdict  # noqa: PLC0415

        buckets: dict[tuple[str | None, str | None], list[int]] = defaultdict(list)
        for i in range(n):
            buckets[per_row_ufs[i], per_row_sexes[i]].append(i)

        names_out: list[str] = [''] * n
        for (bucket_uf, bucket_sex), indices in sorted(
            buckets.items(),
            key=lambda kv: (kv[0][0] or '', kv[0][1] or ''),
        ):
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
        py_rng: random.Random | None = None,
    ) -> str:
        s1 = surname1.upper() if raw else surname1
        s1 = self._apply_prefix(s1, allow_prefix=True, py_rng=py_rng)
        if with_only_one_surname:
            return s1
        s2 = surname2.upper() if raw else surname2
        if s2.upper() in ('JUNIOR', 'JR'):
            s2 = 'JR' if raw else 'Jr.'
        else:
            s2 = self._apply_prefix(s2, allow_prefix=False, py_rng=py_rng)
        return f'{s1} {s2}'

    def _apply_prefix(
        self,
        surname: str,
        allow_prefix: bool = True,
        *,
        py_rng: random.Random | None = None,
    ) -> str:
        """Apply prefix to surname based on complex rules and probabilities."""
        if not allow_prefix:
            return surname
        r = py_rng if py_rng is not None else random
        is_raw = surname.isupper()
        surname_upper = surname.upper()

        if surname_upper in self.SURNAME_PREFIXES:
            if surname_upper in ['SANTOS', 'SILVA']:
                compound_chance = r.random()
                if compound_chance < 0.05:
                    compound_prefix = 'E' if is_raw else 'e'
                    return f'{surname} {compound_prefix}'
                if compound_chance < 0.15:
                    compound_prefix = ('DA' if r.random() < 0.7 else 'DO') if is_raw else ('da' if r.random() < 0.7 else 'do')
                    return f'{surname} {compound_prefix}'

            prefix_options = self.SURNAME_PREFIXES[surname_upper]
            total_weight = sum(weight for _, weight in prefix_options)
            rand = r.random() * total_weight

            cumulative = 0.0
            for candidate_prefix, weight in prefix_options:
                cumulative += weight
                if rand <= cumulative:
                    final_prefix = candidate_prefix
                    if final_prefix in ['da', 'do'] and r.random() < 0.08:
                        final_prefix = ('DOS' if final_prefix == 'do' else 'DAS') if is_raw else ('dos' if final_prefix == 'do' else 'das')
                    elif final_prefix == 'de' and surname[0].lower() in 'aeiou' and r.random() < 0.7:
                        final_prefix = "D'" if is_raw else "d'"
                        return f'{final_prefix}{surname}'
                    else:
                        final_prefix = final_prefix.upper() if is_raw else final_prefix

                    return f'{final_prefix} {surname}'

        return surname

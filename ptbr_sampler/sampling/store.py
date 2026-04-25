"""Partitioned Parquet store with bounded-LRU alias-table cache.

Population is concentrated — SP/MG/RJ alone cover ~40% of state draws — so
most ``(uf, period, sex)`` tuples are rarely hit. This module wraps partition
loading in a bounded LRU keyed on the conditioning tuple. Hot conditions stay
resident; cold ones page from disk and build their alias tables on first
touch.

A partition on disk is a directory such as::

    first_names/uf=SP/decade=1990/sex=F/part.parquet

with columns ``name`` (dictionary-encoded string), ``count`` (uint32) and,
optionally, ``weight`` (float32). If ``weight`` is absent it is derived from
``count`` at ingestion time.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .alias import AliasTable


@dataclass(slots=True, frozen=True)
class PartitionSpec:
    """A conditioning tuple identifying a single partition on disk.

    ``root`` is the root of the partitioned dataset (for example
    ``ptbr_sampler/data/parquet/first_names``). ``filters`` is the ordered mapping of
    partition keys to their values (``{'uf': 'SP', 'decade': '1990',
    'sex': 'F'}``). The on-disk path is ``root/<k1>=<v1>/<k2>=<v2>/.../part.parquet``.
    """

    root: Path
    filters: tuple[tuple[str, str], ...]

    @classmethod
    def of(cls, root: str | Path, **filters: str) -> PartitionSpec:
        items = tuple((str(k), str(v)) for k, v in filters.items())
        return cls(root=Path(root), filters=items)

    def path(self) -> Path:
        parts: list[str] = []
        for k, v in self.filters:
            parts.append(f'{k}={v}')
        return Path(self.root, *parts, 'part.parquet')

    def key(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        return (str(self.root), self.filters)


class PartitionStore:
    """Bounded-LRU cache of :class:`AliasTable` instances keyed by partition.

    The store is deliberately small and synchronous; it exists to make the
    cost structure of sampling explicit rather than to be a general-purpose
    data frame layer. For ad-hoc analytics, query the same Parquet files
    through DuckDB directly.
    """

    def __init__(self, max_entries: int = 64) -> None:
        if max_entries < 1:
            raise ValueError('max_entries must be >= 1')
        self._max = max_entries
        self._cache: OrderedDict[tuple, AliasTable] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, spec: PartitionSpec) -> AliasTable:
        """Return the alias table for ``spec``, loading on miss."""
        key = spec.key()
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        table = self._load(spec)
        self._cache[key] = table
        self._cache.move_to_end(key)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return table

    def register(self, spec: PartitionSpec, table: AliasTable) -> None:
        """Pre-seed the cache with an in-memory table (used by tests)."""
        key = spec.key()
        self._cache[key] = table
        self._cache.move_to_end(key)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()

    def __contains__(self, spec: PartitionSpec) -> bool:
        return spec.key() in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _load(self, spec: PartitionSpec) -> AliasTable:
        path = spec.path()
        if not path.exists():
            raise FileNotFoundError(f'partition missing: {path}')
        try:
            import pyarrow.dataset as ds  # noqa: PLC0415 - keep pyarrow optional until partitions are loaded.
        except ImportError as err:  # pragma: no cover - exercised only without pyarrow
            raise RuntimeError('pyarrow is required to load partitions; install pyarrow') from err

        dataset = ds.dataset(path, format='parquet')
        columns = [f.name for f in dataset.schema]
        want = ['name'] + [c for c in ('count', 'weight') if c in columns]
        table = dataset.to_table(columns=want)
        names = table.column('name').to_pylist()
        counts = (
            table.column('count').to_numpy(zero_copy_only=False).astype(np.int64)
            if 'count' in columns
            else np.zeros(len(names), dtype=np.int64)
        )
        if int(counts.sum()) > 0:
            return AliasTable.from_counts(names, counts)
        # Fall back to stored weights when the source only carries percentages.
        if 'weight' not in columns:
            raise ValueError(f'partition at {path} has neither positive counts nor weight column')
        weights = table.column('weight').to_numpy(zero_copy_only=False).astype(np.float64)
        return AliasTable.from_weights(names, weights)


def alias_from_mapping(mapping: Mapping[str, Any]) -> AliasTable:
    """Build an alias table from the legacy nested-dict JSON format.

    Accepts mappings of the form ``{label: {'count': int, 'percentage': float}}``
    as used by ``names_data.json``, ``surnames_data.json``, and
    ``middle_names.json``. Missing counts fall back to ``percentage``.
    """
    labels: list[str] = []
    counts: list[int] = []
    weights: list[float] = []
    have_counts = True
    for label, info in mapping.items():
        if not isinstance(info, Mapping):
            continue
        pct = info.get('percentage')
        cnt = info.get('count')
        if cnt is None:
            have_counts = False
        try:
            pct_f = float(pct) if pct is not None else 0.0
        except (TypeError, ValueError):
            pct_f = 0.0
        try:
            cnt_i = int(cnt) if cnt is not None else 0
        except (TypeError, ValueError):
            cnt_i = 0
        if pct_f <= 0.0 and (pct is not None or cnt_i <= 0):
            continue
        labels.append(str(label))
        weights.append(pct_f)
        counts.append(cnt_i)
    if not labels:
        raise ValueError('mapping contains no positive-weight entries')
    if have_counts and any(c > 0 for c in counts):
        return AliasTable.from_counts(labels, counts)
    return AliasTable.from_weights(labels, weights)

"""Vectorised sampling primitives for ptbr-sampler.

The modules in this package implement the architecture described in
``docs/architecture.md``:

* :mod:`alias`       — Walker/Vose alias method, O(1)/draw after O(m) build.
* :mod:`store`       — bounded LRU partition cache over ``pyarrow.dataset``.
* :mod:`vocabulary`  — given-name whitelist used to clean middle-name tokens.
"""

from .alias import AliasTable, build_alias, draw
from .store import PartitionSpec, PartitionStore
from .vocabulary import GivenNameVocabulary

__all__ = [
    'AliasTable',
    'GivenNameVocabulary',
    'PartitionSpec',
    'PartitionStore',
    'build_alias',
    'draw',
]

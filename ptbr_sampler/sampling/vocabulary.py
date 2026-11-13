"""Given-name whitelist used to clean middle-name tokens.

``ptbr_sampler/data/middle_names.json`` mixes second given names with surnames such as
``Araújo``, ``Borges``, ``Bezerra``; administrative artifacts such as
``Cancelado``; and a bare hyphen ``-``. No alias table fixes dirty tokens.
This module builds a whitelist from the repository's first-name file and
exposes :meth:`GivenNameVocabulary.filter` so ingestion and on-the-fly cleaning
share the same filter.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_RE = re.compile('^[A-Za-zÀ-ÖØ-öø-ÿ\\u0027\\u2019\\- ]+$')


def _fold(token: str) -> str:
    """Case-fold and strip diacritics so ``'João'`` matches ``'joao'``."""
    nfkd = unicodedata.normalize('NFKD', token)
    without_marks = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return without_marks.casefold().strip()


# Canonical Brazilian surnames drawn from the IBGE 2022 Census "Nomes no
# Brasil" release and cross-checked against the sampler's own
# ``surnames_data.json``. These folded tokens must never be accepted as
# given names, even if a given-name file erroneously lists them (which the
# deep-research audit documents for ``middle_names.json``).
CANONICAL_SURNAMES: frozenset[str] = frozenset(
    _fold(s)
    for s in (
        'Silva',
        'Santos',
        'Oliveira',
        'Souza',
        'Sousa',
        'Lima',
        'Pereira',
        'Ferreira',
        'Rodrigues',
        'Alves',
        'Costa',
        'Ribeiro',
        'Martins',
        'Almeida',
        'Carvalho',
        'Gomes',
        'Barbosa',
        'Rocha',
        'Araújo',
        'Araujo',
        'Dias',
        'Nascimento',
        'Lopes',
        'Monteiro',
        'Cardoso',
        'Teixeira',
        'Moreira',
        'Correia',
        'Mendes',
        'Ramos',
        'Vieira',
        'Nunes',
        'Marques',
        'Machado',
        'Freitas',
        'Cavalcanti',
        'Cavalcante',
        'Cunha',
        'Pinto',
        'Moura',
        'Castro',
        'Campos',
        'Cardozo',
        'Melo',
        'Mello',
        'Borges',
        'Bezerra',
        'Batista',
        'Duarte',
        'Fonseca',
        'Fernandes',
        'Figueiredo',
        'Franco',
        'Freire',
        'Gonçalves',
        'Guimarães',
        'Guimaraes',
        'Leal',
        'Leite',
        'Macedo',
        'Magalhães',
        'Magalhaes',
        'Maia',
        'Medeiros',
        'Miranda',
        'Moraes',
        'Neves',
        'Novais',
        'Pacheco',
        'Paiva',
        'Paula',
        'Peixoto',
        'Peres',
        'Pimentel',
        'Pinheiro',
        'Pires',
        'Prado',
        'Queiroz',
        'Reis',
        'Rezende',
        'Rosa',
        'Sales',
        'Salgado',
        'Sampaio',
        'Sarmento',
        'Saraiva',
        'Sequeira',
        'Serra',
        'Silveira',
        'Simões',
        'Simoes',
        'Siqueira',
        'Soares',
        'Tavares',
        'Torres',
        'Valente',
        'Vasconcelos',
        'Ventura',
        'Viana',
        'Xavier',
    )
    if _fold(s)
)


@dataclass(slots=True)
class GivenNameVocabulary:
    """Accepted-given-names whitelist.

    Tokens are stored folded (diacritics stripped, casefolded) so variants
    like ``João`` / ``Joao`` / ``JOÃO`` all resolve to the same entry.

    The optional ``surname_blocklist`` holds folded tokens that must **never**
    be accepted as given names even if they also appear in the given-name
    table. This is how the IBGE legacy first-name file is disambiguated from
    its surname-contaminated neighbour: if a token appears in both tables
    but shows up in the surname blocklist, it is rejected.
    """

    folded: frozenset[str]
    surname_blocklist: frozenset[str] = frozenset()

    @classmethod
    def from_names_data(
        cls,
        names_data_path: str | Path,
        surnames_data_path: str | Path | None = None,
        surname_top_n: int = 1_000,
    ) -> GivenNameVocabulary:
        """Build a vocabulary from the repository's ``names_data.json``.

        All period buckets contribute, so a name that ever appeared in any
        IBGE decade is accepted. When ``surnames_data_path`` is given, the
        top-``surname_top_n`` surnames are added to the blocklist so that
        obvious surname leakage (``Araújo``, ``Borges``, ``Bezerra``) is
        rejected even if the first-name file erroneously lists them.
        """
        with Path(names_data_path).open(encoding='utf-8') as f:
            data = json.load(f)
        periods = data.get('common_names_percentage', {})
        folded: set[str] = set()
        for period_payload in periods.values():
            names = period_payload.get('names', {})
            for name in names:
                folded.add(_fold(str(name)))
        folded.discard('')
        if not folded:
            raise ValueError('no given names found in names_data payload')

        blocklist: frozenset[str] = frozenset()
        if surnames_data_path is not None:
            with Path(surnames_data_path).open(encoding='utf-8') as f:
                surname_payload = json.load(f)
            surnames = surname_payload.get('surnames', {})
            ordered = sorted(
                ((k, v) for k, v in surnames.items() if k != 'top_40' and isinstance(v, Mapping)),
                key=lambda kv: float(kv[1].get('percentage', 0.0) or 0.0),
                reverse=True,
            )
            blocked = {_fold(k) for k, _ in ordered[:surname_top_n]}
            blocked.discard('')
            blocklist = frozenset(blocked | CANONICAL_SURNAMES)
        else:
            blocklist = CANONICAL_SURNAMES

        return cls(folded=frozenset(folded), surname_blocklist=blocklist)

    @classmethod
    def from_iterable(cls, names: Iterable[str], surnames: Iterable[str] | None = None) -> GivenNameVocabulary:
        """
        Create a GivenNameVocabulary from iterables of given names and optional surnames.

        Parameters:
            names (Iterable[str]): Iterable of given-name tokens to include in the vocabulary; tokens are normalized and folded.
            surnames (Iterable[str] | None): Optional iterable of surname tokens whose folded forms will be added to
                the surname blocklist in addition to the canonical surnames.

        Returns:
            GivenNameVocabulary: Instance whose `folded` set contains the folded given names and whose
                `surname_blocklist` contains the canonical surnames plus any provided folded surnames.

        Raises:
            ValueError: If `names` contains no valid names after folding.
        """
        folded = frozenset(_fold(n) for n in names if _fold(n))
        if not folded:
            raise ValueError('GivenNameVocabulary requires at least one name')
        # Always seed the blocklist with canonical surnames so this constructor
        # cannot accidentally accept tokens like ``Silva`` as given names.
        block = set(CANONICAL_SURNAMES)
        if surnames is not None:
            block.update(_fold(s) for s in surnames if _fold(s))
        return cls(folded=folded, surname_blocklist=frozenset(block))

    def __contains__(self, token: str) -> bool:  # type: ignore[override] - Accepts str instead of object to match internal folded-key usage
        """
        Determine whether a token is an accepted given-name in this vocabulary.

        Parameters:
            token (str): Input token to test; it will be normalized (folded) before membership checks.

        Returns:
            `True` if the folded token is in the vocabulary's accepted given-name set and not present in
            the surname blocklist, `False` otherwise.
        """
        folded = _fold(str(token))
        if folded in self.surname_blocklist:
            return False
        return folded in self.folded

    def __len__(self) -> int:
        return len(self.folded)

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_clean(token: str) -> bool:
        """Reject obvious non-name artifacts before consulting the whitelist."""
        if not token or token.strip() in {'', '-', '--', 'Cancelado', 'CANCELADO', 'cancelado'}:
            return False
        if len(token.strip()) < 2:
            return False
        return bool(_ALLOWED_RE.fullmatch(token))

    def is_given_name(self, token: str) -> bool:
        """Return True only if ``token`` passes the syntactic filter *and* the whitelist."""
        if not self._looks_clean(token):
            return False
        return token in self

    def filter(self, tokens: Iterable[str]) -> list[str]:
        """Return the subset of ``tokens`` that looks like clean given names."""
        return [t for t in tokens if self.is_given_name(t)]

    def filter_mapping(self, mapping: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
        """Filter a ``{token: {count, percentage}}`` mapping by the whitelist.

        Returns a new mapping containing only tokens that pass
        :meth:`is_given_name`. Percentages are **not** renormalised here —
        callers that need a clean distribution should renormalise downstream.
        """
        kept: dict[str, dict[str, float]] = {}
        for token, info in mapping.items():
            if not self.is_given_name(token):
                continue
            if not isinstance(info, Mapping):
                continue
            kept[str(token)] = {
                'count': int(info.get('count', 0)),
                'percentage': float(info.get('percentage', 0.0)),
            }
        return kept

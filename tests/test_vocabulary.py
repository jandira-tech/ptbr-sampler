"""Given-name vocabulary filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ptbr_sampler.sampling.vocabulary import CANONICAL_SURNAMES, GivenNameVocabulary, _fold


def _write(tmp_path: Path, body: dict, name: str) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(body), encoding='utf-8')
    return p


class TestFold:
    def test_strips_diacritics(self):
        assert _fold('João') == 'joao'
        assert _fold('JOÃO') == 'joao'

    def test_strips_whitespace(self):
        assert _fold('  Ana  ') == 'ana'


class TestBuildFromNamesData:
    def test_basic(self, tmp_path: Path):
        names = _write(
            tmp_path,
            {
                'common_names_percentage': {
                    'ate2010': {
                        'names': {
                            'Miguel': {'percentage': 1.0},
                            'Clara': {'percentage': 1.0},
                        },
                        'total': 100,
                    }
                }
            },
            'names.json',
        )
        v = GivenNameVocabulary.from_names_data(names)
        assert 'Miguel' in v
        assert 'Clara' in v
        # Canonical blocklist is always applied.
        assert 'Silva' not in v

    def test_empty_names_rejected(self, tmp_path: Path):
        names = _write(tmp_path, {'common_names_percentage': {}}, 'empty.json')
        with pytest.raises(ValueError):
            GivenNameVocabulary.from_names_data(names)

    def test_surnames_blocklist_extends_canonical(self, tmp_path: Path):
        names = _write(
            tmp_path,
            {
                'common_names_percentage': {
                    'ate2010': {
                        'names': {
                            # Surname leaked into given names — must still be rejected.
                            'Banana': {'percentage': 1.0},
                            'Miguel': {'percentage': 1.0},
                        },
                        'total': 100,
                    }
                }
            },
            'names.json',
        )
        surnames = _write(
            tmp_path,
            {'surnames': {'Banana': {'percentage': 99.0}}},
            'surnames.json',
        )
        v = GivenNameVocabulary.from_names_data(names, surnames, surname_top_n=10)
        assert 'Miguel' in v
        assert 'Banana' not in v


class TestFromIterable:
    def test_basic(self):
        v = GivenNameVocabulary.from_iterable(['Alice', 'Bob'])
        assert 'alice' in v
        assert 'Charlie' not in v

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            GivenNameVocabulary.from_iterable([])

    def test_with_surname_blocklist(self):
        v = GivenNameVocabulary.from_iterable(['Alice', 'Silva'], surnames=['Silva'])
        assert 'Alice' in v
        assert 'Silva' not in v


class TestIsGivenName:
    def test_cleanliness_checks(self):
        v = GivenNameVocabulary.from_iterable(['Alice'])
        assert v.is_given_name('Alice')
        assert not v.is_given_name('')
        assert not v.is_given_name('-')
        assert not v.is_given_name('Cancelado')
        assert not v.is_given_name('A')  # too short
        assert not v.is_given_name('Al1ce')  # digits rejected

    def test_honours_canonical_blocklist(self):
        # A surname like "Silva" is in the canonical set; even if the
        # vocabulary is built to contain it, it should still be rejected.
        v = GivenNameVocabulary(folded=frozenset({_fold('Silva')}), surname_blocklist=CANONICAL_SURNAMES)
        assert not v.is_given_name('Silva')


class TestFilterMapping:
    def test_filters_contaminated_entries(self):
        v = GivenNameVocabulary.from_iterable(['Miguel', 'Clara'])
        mapping = {
            'Miguel': {'count': 100, 'percentage': 10.0},
            'Clara': {'count': 80, 'percentage': 8.0},
            # Canonical surname — rejected even though we also added it.
            'Silva': {'count': 50, 'percentage': 5.0},
            '-': {'count': 1, 'percentage': 0.01},
        }
        kept = v.filter_mapping(mapping)
        assert set(kept) == {'Miguel', 'Clara'}
        assert kept['Miguel']['count'] == 100

    def test_rejects_non_mapping_values(self):
        v = GivenNameVocabulary.from_iterable(['Alice'])
        mapping = {'Alice': 'not-a-dict'}
        kept = v.filter_mapping(mapping)  # type: ignore[arg-type]
        assert kept == {}

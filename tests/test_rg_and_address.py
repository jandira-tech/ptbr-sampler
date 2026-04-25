"""Tests for src.br_rg_class and src.utils.address_for_offline."""

import json
import random
from pathlib import Path

import pytest

from ptbr_sampler.br_rg_class import BrazilianRG
from ptbr_sampler.utils.address_for_offline import AddressProvider_for_offline


class TestBrazilianRG:
    def test_default_state_sp_with_issuer(self):
        # ``generate`` reads ``self.include_issuer``, so set it via init.
        rg = BrazilianRG(state='SP', include_issuer=True)
        assert 'SSP-SP' in rg.generate()

    def test_default_no_issuer(self):
        rg = BrazilianRG()
        generated = rg.generate()
        # Default include_issuer is False on init, so issuer isn't rendered.
        assert 'SSP-SP' not in generated

    def test_unknown_state_raises(self):
        with pytest.raises(ValueError, match='Unknown or unsupported state code'):
            BrazilianRG(state='XX')

    def test_only_rg_returns_pattern_without_issuer(self):
        rg = BrazilianRG(state='SP', only_rg=True)
        generated = rg.generate()
        assert 'SSP' not in generated
        assert 'SP ' not in generated  # no prefix, just raw pattern

    def test_mg_random_prefix_both_branches(self, seeded_random):
        rg = BrazilianRG(state='MG')
        seen_prefix = set()
        for _ in range(50):
            out = rg.generate()
            seen_prefix.add(out.startswith('MG '))
        # Ensure the random coin-flip actually exercised both sides.
        assert seen_prefix == {True, False}

    def test_include_state_prefix_non_mg(self):
        rg = BrazilianRG(state='SP', include_state_prefix=True)
        out = rg.generate()
        assert out.startswith('SP ')

    def test_issuer_included_for_rj(self):
        rg = BrazilianRG(state='RJ', include_issuer=True)
        assert 'DETRAN-RJ' in rg.generate()


class TestAddressProviderOffline:
    def test_street_prefix_returns_string(self, seeded_random):
        ap = AddressProvider_for_offline()
        assert ap.street_prefix() in AddressProvider_for_offline.street_prefixes

    def test_bairro_returns_string(self, seeded_random):
        ap = AddressProvider_for_offline()
        assert ap.bairro() in AddressProvider_for_offline.bairros

    def test_neighborhood_alias(self, seeded_random):
        ap = AddressProvider_for_offline()
        assert ap.neighborhood() in AddressProvider_for_offline.bairros

    def test_building_number_is_digits(self, seeded_random):
        ap = AddressProvider_for_offline()
        for _ in range(20):
            n = ap.building_number()
            assert n.isdigit()
            assert 1 <= int(n) <= 999

    def test_last_name_from_list(self, seeded_random):
        ap = AddressProvider_for_offline()
        assert isinstance(ap.last_name(), str)

    def test_non_weighted_random_name_returns_fallback_when_missing_file(self):
        ap = AddressProvider_for_offline()
        assert ap.non_weighted_random_name('nonexistent_path.json') == 'Maria'

    def test_non_weighted_random_name_returns_default_when_empty(self, tmp_path: Path):
        """When the names file has no name entries, the 'João' fallback fires."""
        p = tmp_path / 'names.json'
        p.write_text(json.dumps({'only_meta': {'total': 0}}), encoding='utf-8')
        ap = AddressProvider_for_offline()
        assert ap.non_weighted_random_name(str(p)) == 'João'

    def test_first_name_returns_string(self, tmp_path: Path, monkeypatch, seeded_random):
        # Feed a synthetic names file via the non_weighted_random_name default.
        p = tmp_path / 'names.json'
        p.write_text(
            json.dumps({'ate2010': {'names': [['Alice', 1.0]]}}),
            encoding='utf-8',
        )
        ap = AddressProvider_for_offline()
        assert ap.non_weighted_random_name(str(p)) == 'Alice'

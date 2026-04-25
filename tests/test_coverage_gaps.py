"""Targeted tests to close specific coverage gaps."""

import random

from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import BrazilianNameSampler
from ptbr_sampler.utils import cei as cei_mod
from ptbr_sampler.utils import cnpj as cnpj_mod
from ptbr_sampler.utils import cpf as cpf_mod
from ptbr_sampler.utils import phone as phone_mod
from ptbr_sampler.utils import pis as pis_mod
from ptbr_sampler.utils import util as util_mod


class TestMiddleNameZeroWeightBranch:
    def test_all_zero_weights_returns_empty(self, mock_name_data):
        """When every middle-name entry has zero weight, _get_random_middle_name returns ''."""
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 100.0,
            'second_names': {
                'A': {'count': 0, 'percentage': 0.0},
                'B': {'count': 0, 'percentage': 0.0},
            },
        }
        assert sampler._get_random_middle_name() == ''

    def test_count_only_middle_name_mapping_is_supported(self, mock_name_data):
        """Count-only alias mappings remain usable in mutated test fixtures."""
        sampler = BrazilianNameSampler(mock_name_data)
        sampler.middle_names_data = {
            'percentage_with_second': 50.0,
            'second_names': {'X': {'count': 1}},
        }
        assert sampler._get_random_middle_name() == 'X'


class TestGetRandomLocationDefaultBranch:
    def test_default_full_location(self, mock_location_data):
        """No flags -> returns the full 'city, state (abbr), cep' string."""
        sampler = BrazilianLocationSampler(mock_location_data)
        random.seed(0)
        result = sampler.get_random_location()
        assert '(' in result and ')' in result
        assert ',' in result


class TestValidateDocumentShortRejection:
    """Auto-pad=False paths for each validator — covering the early False returns."""

    def test_cpf_short_no_autopad(self):
        assert cpf_mod.validate_cpf('1', autopad=False) is False

    def test_cpf_bad_second_check_returns_false(self):
        # CPF with correct first digit and wrong second digit.
        base = '123456789'
        d1, d2 = cpf_mod.cpf_check_digits(base)
        bad = f'{base}{d1}{(d2 + 1) % 10}'
        assert cpf_mod.validate_cpf(bad) is False

    def test_cpf_bad_first_check_returns_false(self):
        """Exercise the 'first check digit is not correct' branch (line 38)."""
        base = '123456789'
        d1, d2 = cpf_mod.cpf_check_digits(base)
        wrong_d1 = (d1 + 1) % 10
        bad = f'{base}{wrong_d1}{d2}'
        assert cpf_mod.validate_cpf(bad) is False

    def test_cnpj_short_no_autopad(self):
        assert cnpj_mod.validate_cnpj('1', autopad=False) is False

    def test_cnpj_second_check_false(self):
        # Make a CNPJ with a valid first check and intentionally wrong second.
        base = '123456780001'
        d1, d2 = cnpj_mod.cnpj_check_digits(base)
        bad = f'{base}{d1}{(d2 + 1) % 10}'
        assert cnpj_mod.validate_cnpj(bad) is False

    def test_cnpj_from_firm_id_formatted(self):
        formatted = cnpj_mod.cnpj_from_firm_id('12345678', formatted=True)
        assert '.' in formatted and '/' in formatted

    def test_cei_short_no_autopad(self):
        assert cei_mod.validate_cei('1', autopad=False) is False

    def test_cei_short_autopad_true(self):
        # With autopad=True, a too-short CEI is padded — still not valid, but
        # the autopad branch is exercised.
        assert cei_mod.validate_cei('1', autopad=True) is False

    def test_pis_short_no_autopad(self):
        assert pis_mod.validate_pis('1', autopad=False) is False

    def test_pis_short_autopad_true(self):
        assert pis_mod.validate_pis('1', autopad=True) is False

    def test_cnpj_short_autopad_true(self):
        assert cnpj_mod.validate_cnpj('1', autopad=True) is False

    def test_cpf_short_autopad_true(self):
        # CPF with autopad=True — exercises the padding branch, returns bool.
        assert cpf_mod.validate_cpf('1', autopad=True) is False


class TestAddressProviderFirstNameFallback:
    def test_first_name_returns_string(self, tmp_path, monkeypatch):
        """first_name delegates to non_weighted_random_name; cover line 683."""
        from ptbr_sampler.utils.address_for_offline import AddressProvider_for_offline

        # Point the default names path to something non-existent so the
        # fallback kicks in deterministically.
        monkeypatch.chdir(tmp_path)  # Ensure 'ptbr_sampler/data/names_data.json' doesn't exist
        ap = AddressProvider_for_offline()
        result = ap.first_name()
        assert isinstance(result, str)


class TestPhoneDummyClass:
    """The PhoneNumber helper class lives alongside the public helper."""

    def test_phone_number_class_constants(self):
        assert phone_mod.PhoneNumber.formats
        assert phone_mod.PhoneNumber.cellphone_formats

    def test_phone_class_instantiable(self):
        """The PhoneNumber helper can be instantiated (methods are stubs)."""
        assert isinstance(phone_mod.PhoneNumber(), phone_mod.PhoneNumber)


class TestUtilPadEmptyPath:
    def test_pad_empty_string(self):
        """pad_id with an already-empty string routes through the empty branch."""
        assert util_mod.pad_id('', '%0.05i') == '00000'

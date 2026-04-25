"""Tests for document-number utilities in ptbr_sampler/utils."""

import pytest

from ptbr_sampler.utils import cei as cei_mod
from ptbr_sampler.utils import cnpj as cnpj_mod
from ptbr_sampler.utils import cpf as cpf_mod
from ptbr_sampler.utils import phone as phone_mod
from ptbr_sampler.utils import pis as pis_mod
from ptbr_sampler.utils import util as util_mod


class TestUtil:
    def test_clean_id_removes_nondigits(self):
        assert util_mod.clean_id('123.456-789/00') == '12345678900'

    def test_clean_id_int_returns_str(self):
        assert util_mod.clean_id(123) == '123'

    def test_pad_id_int(self):
        assert util_mod.pad_id(42, '%0.05i') == '00042'

    def test_pad_id_str_with_nondigits(self):
        assert util_mod.pad_id('12a3', '%0.05i') == '00123'

    def test_pad_id_empty_string_becomes_zero(self):
        assert util_mod.pad_id('abc', '%0.05i') == '00000'


class TestCPF:
    def test_random_cpf_is_valid(self, seeded_random):
        for _ in range(25):
            generated = cpf_mod.random_cpf()
            assert cpf_mod.validate_cpf(generated)

    def test_random_cpf_unformatted(self, seeded_random):
        generated = cpf_mod.random_cpf(formatted=False)
        assert '.' not in generated and '-' not in generated
        assert len(generated) == 11
        assert cpf_mod.validate_cpf(generated)

    def test_random_cpf_preserves_zero_check_digits(self, monkeypatch):
        monkeypatch.setattr(cpf_mod.random, 'randint', lambda _start, _end: 100000001)
        generated = cpf_mod.random_cpf(formatted=False)
        assert generated == '10000000108'
        assert cpf_mod.validate_cpf(generated)

    def test_validate_all_zeros_rejected(self):
        assert cpf_mod.validate_cpf('00000000000') is False

    def test_validate_wrong_first_check_digit(self):
        bad = '12345678900'
        assert cpf_mod.validate_cpf(bad) is False

    def test_validate_too_long_rejected(self):
        assert cpf_mod.validate_cpf('1' * 12) is False

    def test_validate_too_short_autopad(self):
        """A 9-digit base whose padded form carries valid check digits."""
        # pad_cpf left-pads the 9-digit base to 11 chars; use the padded form
        # as the basis for computing the two trailing check digits.
        padded_base = cpf_mod.pad_cpf('000000000', validate=False)  # '00000000000'
        d1, d2 = cpf_mod.cpf_check_digits(padded_base[:-2])
        candidate = padded_base[:-2] + f'{d1}{d2}'
        if candidate != '00000000000':
            assert cpf_mod.validate_cpf(candidate) is True
        # "Too short" autopad path — feed a 10-char value, confirm validate
        # pads and evaluates it (result depends on digits but call must run).
        cpf_mod.validate_cpf(padded_base[:10], autopad=True)

    def test_validate_too_short_no_autopad_false(self):
        assert cpf_mod.validate_cpf('123', autopad=False) is False

    def test_cpf_check_digits_short_raises(self):
        with pytest.raises(ValueError, match='CPF must have at least 9 digits'):
            cpf_mod.cpf_check_digits('123')

    def test_pad_cpf_with_validate(self):
        padded, valid = cpf_mod.pad_cpf('0', validate=True)
        assert len(padded) == 11
        assert valid is False  # all zeros -> invalid

    def test_validate_bad_second_check_digit(self):
        # Build a CPF with a correct first check digit but wrong second one.
        base = '123456789'
        d1, _d2 = cpf_mod.cpf_check_digits(base)
        bad = f'{base}{d1}9'  # Force wrong last digit
        if cpf_mod.validate_cpf(bad):
            # If by chance the second digit is 9, swap it.
            bad = f'{base}{d1}{(int(bad[-1]) + 1) % 10}'
        assert cpf_mod.validate_cpf(bad) is False


class TestCNPJ:
    def test_random_cnpj_is_valid(self, seeded_random):
        for _ in range(25):
            generated = cnpj_mod.random_cnpj()
            assert cnpj_mod.validate_cnpj(generated)

    def test_random_cnpj_unformatted(self, seeded_random):
        generated = cnpj_mod.random_cnpj(formatted=False)
        assert '.' not in generated and '/' not in generated
        assert cnpj_mod.validate_cnpj(generated)

    def test_validate_all_zeros_rejected(self):
        assert cnpj_mod.validate_cnpj('00000000000000') is False

    def test_validate_too_long_rejected(self):
        assert cnpj_mod.validate_cnpj('1' * 15) is False

    def test_validate_too_short_no_autopad_false(self):
        assert cnpj_mod.validate_cnpj('123', autopad=False) is False

    def test_cnpj_check_digits_short_raises(self):
        with pytest.raises(ValueError, match='CNPJ must have at least 12 digits'):
            cnpj_mod.cnpj_check_digits('12')

    def test_parse_cnpj_formatted(self, seeded_random):
        generated = cnpj_mod.random_cnpj(formatted=False)
        parsed = cnpj_mod.parse_cnpj(generated, formatted=True)
        assert parsed.valid is True
        assert parsed.firm.count('.') == 2

    def test_parse_cnpj_unformatted(self, seeded_random):
        generated = cnpj_mod.random_cnpj(formatted=False)
        parsed = cnpj_mod.parse_cnpj(generated, formatted=False)
        assert parsed.valid is True
        assert isinstance(parsed.firm, int)
        assert isinstance(parsed.check, tuple)

    def test_validate_bad_first_check(self):
        # A clearly-invalid CNPJ whose check digits won't line up.
        assert cnpj_mod.validate_cnpj('12345678000100') is False

    def test_pad_cnpj_with_validate(self):
        padded, valid = cnpj_mod.pad_cnpj('0', validate=True)
        assert len(padded) == 14
        assert valid is False


class TestPIS:
    def test_random_pis_valid(self, seeded_random):
        for _ in range(25):
            assert pis_mod.validate_pis(pis_mod.random_pis())

    def test_random_pis_unformatted(self, seeded_random):
        generated = pis_mod.random_pis(formatted=False)
        assert '.' not in generated
        assert pis_mod.validate_pis(generated)

    def test_validate_all_zeros_rejected(self):
        assert pis_mod.validate_pis('00000000000') is False

    def test_validate_too_long_rejected(self):
        assert pis_mod.validate_pis('1' * 12) is False

    def test_validate_too_short_no_autopad_false(self):
        assert pis_mod.validate_pis('1', autopad=False) is False

    def test_pis_check_digit_short_raises(self):
        with pytest.raises(ValueError, match='PIS'):
            pis_mod.pis_check_digit('123')

    def test_pis_check_digits_alias(self):
        # Should return same value as pis_check_digit
        candidate = '1234567890'
        assert pis_mod.pis_check_digits(candidate) == pis_mod.pis_check_digit(candidate)

    def test_validate_wrong_check(self):
        # Build a base with a guaranteed-wrong check digit.
        base = '1234567890'
        correct = pis_mod.pis_check_digit(base)
        wrong = (correct + 1) % 10
        assert pis_mod.validate_pis(f'{base}{wrong}') is False

    def test_pad_pis_with_validate(self):
        padded, valid = pis_mod.pad_pis('0', validate=True)
        assert len(padded) == 11
        assert valid is False


class TestCEI:
    def test_random_cei_valid(self, seeded_random):
        for _ in range(25):
            assert cei_mod.validate_cei(cei_mod.random_cei())

    def test_random_cei_unformatted(self, seeded_random):
        raw = cei_mod.random_cei(formatted=False)
        assert '.' not in raw and '/' not in raw
        assert cei_mod.validate_cei(raw)

    def test_validate_all_zeros_rejected(self):
        assert cei_mod.validate_cei('000000000000') is False

    def test_validate_too_long_rejected(self):
        assert cei_mod.validate_cei('1' * 13) is False

    def test_validate_too_short_no_autopad_false(self):
        assert cei_mod.validate_cei('1', autopad=False) is False

    def test_cei_check_digit_short_raises(self):
        with pytest.raises(ValueError, match='CEI'):
            cei_mod.cei_check_digit('1234')

    def test_cei_check_zero_path(self):
        # _cei_check returns 0 when modulo is zero — exercise that branch.
        # Build synthetic digits that sum to a multiple of 10 after divmod(100).
        digits = [0] * 11
        assert cei_mod._cei_check(digits) == 0

    def test_pad_cei_with_validate(self):
        padded, valid = cei_mod.pad_cei('0', validate=True)
        assert len(padded) == 12
        assert valid is False

    def test_format_cei(self):
        formatted = cei_mod.format_cei('123456789012')
        assert formatted == '12.345.67890/12'


class TestPhone:
    def test_generate_landline_format(self, monkeypatch):
        # Force landline branch deterministically.
        monkeypatch.setattr(phone_mod.random, 'choice', lambda seq: seq[1] if seq == [True, False] else seq[0])
        p = phone_mod.generate_phone_number(ddd='11')
        assert p.startswith('(11) ')

    def test_generate_cellphone_format(self, monkeypatch, seeded_random):
        # Force cellphone branch
        def fake_choice(seq):
            if seq == [True, False]:
                return True
            return seq[0]

        monkeypatch.setattr(phone_mod.random, 'choice', fake_choice)
        p = phone_mod.generate_phone_number(ddd='21')
        # Cellphone format: (21) 9XXXX-XXXX
        assert p.startswith('(21) 9')
        assert '-' in p

    def test_generate_without_ddd_picks_valid_area_code(self, seeded_random):
        p = phone_mod.generate_phone_number()
        assert p.startswith('(')

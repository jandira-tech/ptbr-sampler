import random
import re

from .util import clean_id, pad_id

"""
Functions for working with Brazilian CPF identifiers.

"""

NONDIGIT = re.compile(r'[^0-9]')
CPF_WEIGHTS = [1, 2, 3, 4, 5, 6, 7, 8, 9]


def validate_cpf(cpf, autopad=True):
    """Check whether CPF is valid."""
    cpf = clean_id(cpf)

    # all complete CPF are 11 digits long
    if len(cpf) < 11:
        if not autopad:
            return False
        cpf = pad_cpf(cpf)

    elif len(cpf) > 11:
        return False

    if cpf == '00000000000':
        return False

    digits = [int(k) for k in cpf]  # identifier digits
    # validate the first check digit
    cs = (sum(w * k for w, k in zip(CPF_WEIGHTS, digits[:-2], strict=False)) % 11) % 10
    if cs != digits[-2]:
        return False  # first check digit is not correct
    # validate the second check digit
    cs = (sum(w * k for w, k in zip(CPF_WEIGHTS, digits[1:-1], strict=False)) % 11) % 10
    return cs == digits[-1]


def cpf_check_digits(cpf):
    """Find two check digits needed to make a CPF valid."""
    cpf = clean_id(cpf)
    if len(cpf) < 9:
        raise ValueError(f'CPF must have at least 9 digits: {cpf}')
    digits = [int(k) for k in cpf[:10]]
    # find the first check digit
    cs = (sum(w * k for w, k in zip(CPF_WEIGHTS, digits, strict=False)) % 11) % 10
    # find the second check digit
    digits.append(cs)
    return cs, (sum(w * k for w, k in zip(CPF_WEIGHTS, digits[1:], strict=False)) % 11) % 10


def format_cpf(cpf):
    """Applies typical 000.000.000-00 formatting to CPF."""
    cpf = pad_cpf(cpf)
    fmt = '{0}.{1}.{2}-{3}'
    return fmt.format(cpf[:3], cpf[3:6], cpf[6:9], cpf[9:])


def pad_cpf(cpf, validate=False):
    """Takes a CPF that probably had leading zeros and pads it."""
    padded = pad_id(cpf, '%0.011i')
    if validate:
        return padded, validate_cpf(padded)
    return padded


def random_cpf(formatted=True):
    """Create a random, valid CPF identifier."""
    stem = random.randint(100000000, 999999999)
    digits = cpf_check_digits(stem)
    check_digits = f'{digits[0]}{digits[1]}'
    cpf = f'{stem}{check_digits}'
    if formatted:
        return format_cpf(cpf)
    return cpf

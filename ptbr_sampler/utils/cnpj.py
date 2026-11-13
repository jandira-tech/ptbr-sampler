import random
from collections import namedtuple

from .util import clean_id, pad_id

"""
Functions for working with Brazilian company identifiers (CNPJ).

"""

CNPJ_FIRST_WEIGHTS = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ_SECOND_WEIGHTS = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ = namedtuple('CNPJ', ['cnpj', 'firm', 'establishment', 'check', 'valid'])


def validate_cnpj(cnpj, autopad=True):
    """Check whether CNPJ is valid. Optionally pad if too short."""
    cnpj = clean_id(cnpj)

    # all complete CNPJ are 14 digits long
    if len(cnpj) < 14:
        if not autopad:
            return False
        cnpj = pad_cnpj(cnpj)

    elif len(cnpj) > 14:
        return False

    # 0 is invalid; smallest valid CNPJ is 191
    if cnpj == '00000000000000':
        return False

    digits = [int(k) for k in cnpj[:13]]  # identifier digits
    # validate the first check digit
    cs = sum(w * k for w, k in zip(CNPJ_FIRST_WEIGHTS, digits[:-1], strict=False)) % 11
    cs = 0 if cs < 2 else 11 - cs
    if cs != int(cnpj[12]):
        return False  # first check digit is not correct
    # validate the second check digit
    cs = sum(w * k for w, k in zip(CNPJ_SECOND_WEIGHTS, digits, strict=False)) % 11
    cs = 0 if cs < 2 else 11 - cs
    return cs == int(cnpj[13])


def cnpj_check_digits(cnpj):
    """
    Compute the two check digits for a CNPJ using its first 12 digits.

    Parameters:
        cnpj (str|int): CNPJ value or fragment; non-digit characters will be removed before processing.

    Returns:
        (first_check, second_check) (tuple[int, int]): The first and second check digits as integers.

    Raises:
        ValueError: If the cleaned input contains fewer than 12 digits.
    """
    cnpj = clean_id(cnpj)
    if len(cnpj) < 12:
        raise ValueError(f'CNPJ must have at least 12 digits: {cnpj}')
    # Use exactly the 12 base digits so any extra input (e.g., already-attached
    # check digits) cannot influence the computed check digits.
    digits = [int(k) for k in cnpj[:12]]
    cs = sum(w * k for w, k in zip(CNPJ_FIRST_WEIGHTS, digits, strict=True)) % 11
    check = 0 if cs < 2 else 11 - cs
    digits.append(check)
    cs = sum(w * k for w, k in zip(CNPJ_SECOND_WEIGHTS, digits, strict=True)) % 11
    if cs < 2:
        return check, 0
    return check, 11 - cs


def cnpj_from_firm_id(firm, establishment='0001', formatted=False):
    """Takes first 8 digits of a CNPJ (firm identifier) and builds a valid,
    complete CNPJ by appending an establishment identifier and calculating
    necessary check digits.
    """
    cnpj = clean_id(f'{firm}{establishment}')
    checks = ''.join([str(k) for k in cnpj_check_digits(cnpj)])
    if not formatted:
        return cnpj + checks
    return format_cnpj(cnpj + checks)


def format_cnpj(cnpj):
    """Applies typical 00.000.000/0000-00 formatting to CNPJ."""
    cnpj = pad_cnpj(cnpj)
    fmt = '{0}.{1}.{2}/{3}-{4}'
    return fmt.format(cnpj[:2], cnpj[2:5], cnpj[5:8], cnpj[8:12], cnpj[12:])


def pad_cnpj(cnpj, validate=False):
    """Takes a CNPJ and pads it with leading zeros."""
    padded = pad_id(cnpj, '%0.014i')
    if validate:
        return padded, validate_cnpj(padded)
    return padded


def parse_cnpj(cnpj, formatted=True):
    """Split CNPJ into firm, establishment, and check digits, and validate."""
    cnpj, valid = pad_cnpj(cnpj, validate=True)
    estbl, check = cnpj[8:12], cnpj[12:]
    if formatted:
        cnpj = format_cnpj(cnpj)
        firm = cnpj[:10]
        return CNPJ(cnpj, firm, estbl, check, valid)
    firm = cnpj[:8]
    check = tuple(int(k) for k in check)
    return CNPJ(int(cnpj), int(firm), int(estbl), check, valid)


def random_cnpj(formatted: bool = True, rng: random.Random | None = None) -> str:
    """Create a random, valid CNPJ identifier."""
    r = rng if rng is not None else random
    firm = r.randint(10000000, 99999999)
    establishment = r.choice(['0001', '0002', '0003', '0004', '0005'])
    cnpj = cnpj_from_firm_id(firm, establishment)
    if formatted:
        return format_cnpj(cnpj)
    return cnpj

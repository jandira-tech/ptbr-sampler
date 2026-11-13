import random


class PhoneNumber:
    formats = (
        '(0##) #### ####',
        '## ####-####',
    )

    msisdn_formats = ('##9########',)

    cellphone_formats = (
        '## 9#### ####',
        '## 9 #### ####',
        '(0##) 9#### ####',
        '(##) 9#### ####',
        '(##) 9 #### ####',
    )

    commercial_phones_formats = (
        '0300 ### ####',
        '0800 ### ####',
        '0900 ### ####',
        '0500-###-####',
        '0800-###-####',
        '0900-###-####',
    )

    services_phones_formats = (
        '100',
        '128',
        '151',
        '152',
        '153',
        '156',
        '180',
        '181',
        '185',
        '188',
        '190',
        '191',
        '192',
        '193',
        '194',
        '197',
        '198',
        '199',
    )

    def cellphone_number(self) -> str:  # pragma: no cover - stub, relies on external generator
        pattern: str = self.random_element(self.cellphone_formats)
        return self.numerify(self.generator.parse(pattern))

    def service_phone_number(self) -> str:  # pragma: no cover - stub, relies on external generator
        pattern: str = self.random_element(self.services_phones_formats)
        return self.numerify(self.generator.parse(pattern))


def generate_phone_number(
    ddd: str | None = None,
    rng: random.Random | None = None,
) -> str:
    """
    Generate a random Brazilian phone number.
    Randomly returns either a landline (8 digits) or a cellphone (9 digits).

    Formats:
    - Landline: (XX) XXXX-XXXX
    - Cellphone: (XX) 9XXXX-XXXX

    Args:
        ddd (str, optional): The area code to use. If None, a random one will be selected.
        rng (random.Random, optional): Optional RNG instance; defaults to module ``random``.
    """
    r = rng if rng is not None else random
    # Brazilian area codes (DDD)
    area_codes = [
        '11',
        '12',
        '13',
        '14',
        '15',
        '16',
        '17',
        '18',
        '19',
        '21',
        '22',
        '24',
        '27',
        '28',
        '31',
        '32',
        '33',
        '34',
        '35',
        '37',
        '38',
        '41',
        '42',
        '43',
        '44',
        '45',
        '46',
        '47',
        '48',
        '49',
        '51',
        '53',
        '54',
        '55',
        '61',
        '62',
        '63',
        '64',
        '65',
        '66',
        '67',
        '68',
        '69',
        '71',
        '73',
        '74',
        '75',
        '77',
        '79',
        '81',
        '82',
        '83',
        '84',
        '85',
        '86',
        '87',
        '88',
        '89',
        '91',
        '92',
        '93',
        '94',
        '95',
        '96',
        '97',
        '98',
        '99',
    ]

    # Use provided DDD or generate a random area code
    area_code = ddd if ddd else r.choice(area_codes)

    # Randomly decide whether to generate a landline or cellphone
    is_cellphone = r.choice([True, False])

    if is_cellphone:
        # Cellphone: 9 digits starting with 9 -> (XX) 9XXXX-XXXX
        first_digit = '9'
        rest_first_part = ''.join(r.choices('0123456789', k=4))
    else:
        # Landline: 8 digits, first digit is never 0 -> (XX) XXXX-XXXX
        first_digit = r.choice('123456789')
        rest_first_part = ''.join(r.choices('0123456789', k=3))

    first_part = f'{first_digit}{rest_first_part}'
    second_part = ''.join(r.choices('0123456789', k=4))
    return f'({area_code}) {first_part}-{second_part}'

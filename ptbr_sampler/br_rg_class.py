import random


class BrazilianRG:
    """
    A class to simulate the generation of a realistic Brazilian RG (Registro Geral)
    number for each federative unit (26 states plus the Federal District). Each state has
    its own number format (using '#' as a placeholder for a digit) and a common issuing
    authority ("emissor"). For example, most states use "SSP-XX" (Secretaria de Segurança Pública)
    while Rio de Janeiro uses "DETRAN-RJ".

    In addition, when generating an RG for Minas Gerais ("MG"), the script randomly determines
    whether to include the "MG" prefix in the final output.
    """

    # Dictionary mapping state codes to state-specific RG patterns.
    # The '#' character represents a digit (0-9).
    STATE_PATTERNS = {
        'AC': '##.####-#',  # e.g., 12.3456-7
        'AL': '###.###-##',  # e.g., 123.456-78
        'AP': '##.###-##',  # e.g., 12.345-67
        'AM': '###.###-##',  # e.g., 123.456-78
        'BA': '###.###.###',  # e.g., 123.456.789
        'CE': '##.###.###-#',  # e.g., 12.345.678-9
        'DF': '##.###.###-#',  # e.g., 12.345.678-9
        'ES': '###.###-##',  # e.g., 123.456-78
        'GO': '###.###-##',  # e.g., 123.456-78
        'MA': '##.####-#',  # e.g., 12.3456-7
        'MT': '##.###-##',  # e.g., 12.345-67
        'MS': '##.###-##',  # e.g., 12.345-67
        'MG': '##.###-##',  # e.g., 11.222-04; note: prefix "MG" is randomly added.
        'PA': '###.###-#',  # e.g., 123.456-7
        'PB': '###.###-##',  # e.g., 123.456-78
        'PR': '##.###.###',  # e.g., 12.345.678
        'PE': '###.###-##',  # e.g., 123.456-78
        'PI': '##.###-##',  # e.g., 12.345-67
        'RJ': '###.####-#',  # e.g., 123.4567-8
        'RN': '##.###-##',  # e.g., 12.345-67
        'RS': '##.###.###',  # e.g., 12.345.678
        'RO': '##.####-##',  # e.g., 12.3456-78
        'RR': '##.###-##',  # e.g., 12.345-67
        'SC': '##.###-##',  # e.g., 12.345-67
        'SP': '##.###.###-#',  # e.g., 12.345.678-9
        'SE': '##.###-##',  # e.g., 12.345-67
        'TO': '##.###-##',  # e.g., 12.345-67
    }

    # Dictionary mapping state codes to the common issuing authority.
    ISSUERS = {
        'AC': 'SSP-AC',
        'AL': 'SSP-AL',
        'AP': 'SSP-AP',
        'AM': 'SSP-AM',
        'BA': 'SSP-BA',
        'CE': 'SSP-CE',
        'DF': 'SSP-DF',
        'ES': 'SSP-ES',
        'GO': 'SSP-GO',
        'MA': 'SSP-MA',
        'MT': 'SSP-MT',
        'MS': 'SSP-MS',
        'MG': 'SSP-MG',  # For MG, the issuer is SSP-MG.
        'PA': 'SSP-PA',
        'PB': 'SSP-PB',
        'PR': 'SSP-PR',
        'PE': 'SSP-PE',
        'PI': 'SSP-PI',
        'RJ': 'DETRAN-RJ',  # Rio de Janeiro typically uses DETRAN-RJ.
        'RN': 'SSP-RN',
        'RS': 'SSP-RS',
        'RO': 'SSP-RO',
        'RR': 'SSP-RR',
        'SC': 'SSP-SC',
        'SP': 'SSP-SP',
        'SE': 'SSP-SE',
        'TO': 'SSP-TO',
    }

    def __init__(self, state: str | None = 'SP', include_issuer: bool = False, include_state_prefix: bool = False, only_rg: bool = False):
        """
        Initialize the RG generator.

        Parameters:
            state (str | None): A two-letter state code (e.g., "MG", "RJ", "SP", etc.). Defaults to "SP".
            include_issuer (bool): If True, the final output will include the issuer's abbreviation.
            include_state_prefix (bool): If True (for non-MG states), the state code will be prefixed.
                                         For MG, this flag is ignored in favor of a random decision.
            only_rg (bool): If True, the final output will be a string of 10 digits representing the RG number.
        Raises:
            ValueError: If the state code is not recognized.
        """
        self.state = state.upper().strip()
        if self.state not in BrazilianRG.STATE_PATTERNS:
            raise ValueError(f'Unknown or unsupported state code: {self.state}')
        self.include_issuer = include_issuer
        self.include_state_prefix = include_state_prefix
        self.only_rg = only_rg

    def _generate_from_pattern(
        self,
        pattern: str,
        rng: random.Random | None = None,
    ) -> str:
        """
        Generate a string by replacing each '#' in the pattern with a random digit (0-9).
        """
        r = rng if rng is not None else random
        return ''.join(str(r.randint(0, 9)) if char == '#' else char for char in pattern)

    def generate(
        self,
        state: str | None = None,
        include_issuer: bool | None = None,
        include_state_prefix: bool | None = None,
        only_rg: bool | None = None,
        *,
        formatted: bool = True,
        rng: random.Random | None = None,
    ) -> str:
        """
        Generate a complete, realistic RG number string according to the state-specific pattern.

        Explicit arguments override the defaults configured in ``__init__`` without
        mutating ``self``.

        Returns:
            A string representing the final RG number, optionally prefixed with the issuer and/or state code.
        """
        r = rng if rng is not None else random
        eff_state = self.state if state is None else state.upper().strip()
        if eff_state not in BrazilianRG.STATE_PATTERNS:
            raise ValueError(f'Unknown or unsupported state code: {eff_state}')

        eff_include_issuer = self.include_issuer if include_issuer is None else include_issuer
        eff_include_state_prefix = self.include_state_prefix if include_state_prefix is None else include_state_prefix
        eff_only_rg = self.only_rg if only_rg is None else only_rg

        pattern = BrazilianRG.STATE_PATTERNS[eff_state]
        if not formatted:
            return ''.join(str(r.randint(0, 9)) for _ in range(pattern.count('#')))

        rg_number = self._generate_from_pattern(pattern, rng=r)

        if eff_only_rg:
            return rg_number

        parts = []
        # Include issuer if required.
        if eff_include_issuer:
            parts.append(BrazilianRG.ISSUERS[eff_state])

        # For MG, randomly decide to include the "MG" prefix (state code).
        if eff_state == 'MG':
            mg_prefix = r.choice([True, False])
            if mg_prefix:
                parts.append('MG')
        elif eff_include_state_prefix:
            parts.append(eff_state)

        parts.append(rg_number)
        return ' '.join(parts)

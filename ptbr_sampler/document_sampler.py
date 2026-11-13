"""Brazilian document number generator using utility functions."""

import random

from ptbr_sampler.br_rg_class import BrazilianRG
from ptbr_sampler.utils.cei import random_cei
from ptbr_sampler.utils.cnpj import random_cnpj
from ptbr_sampler.utils.cpf import random_cpf
from ptbr_sampler.utils.pis import random_pis


class DocumentSampler:
    """Class for generating various Brazilian documents."""

    def __init__(self, only_rg: bool = False):
        """Initialize the document sampler."""
        self.rg_generator = BrazilianRG(only_rg=only_rg)

    def generate_cpf(
        self,
        formatted: bool = True,
        rng: random.Random | None = None,
    ) -> str:
        """Generate a valid CPF number."""
        return random_cpf(formatted=formatted, rng=rng)

    def generate_pis(
        self,
        formatted: bool = True,
        rng: random.Random | None = None,
    ) -> str:
        """Generate a valid PIS number."""
        return random_pis(formatted=formatted, rng=rng)

    def generate_cnpj(
        self,
        formatted: bool = True,
        rng: random.Random | None = None,
    ) -> str:
        """Generate a valid CNPJ number."""
        return random_cnpj(formatted=formatted, rng=rng)

    def generate_cei(
        self,
        formatted: bool = True,
        rng: random.Random | None = None,
    ) -> str:
        """Generate a valid CEI number."""
        return random_cei(formatted=formatted, rng=rng)

    def generate_rg(
        self,
        state: str | None = None,
        include_issuer: bool = True,
        only_rg: bool | None = None,
        *,
        formatted: bool = True,
        rng: random.Random | None = None,
    ) -> str:
        """Generate a valid RG number for the given state."""
        return self.rg_generator.generate(
            state=state,
            include_issuer=include_issuer,
            only_rg=only_rg,
            formatted=formatted,
            rng=rng,
        )

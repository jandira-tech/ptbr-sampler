"""Brazilian Name and Location Generator.

This package provides tools for generating realistic Brazilian names and
locations based on population data and historical naming patterns.

Top-level exports:
    BrazilianLocationSampler — state/city/CEP sampler.
    BrazilianNameSampler     — alias-table-backed name sampler.
    TimePeriod               — birth-period buckets.
    NameComponents           — (first_name, middle_name, surname) triple.
    app, main                — Typer CLI (``ptbr`` entry point).

The CLI is installed as the ``ptbr`` console script; see ``pyproject.toml``.
"""

from ptbr_sampler.br_location_class import BrazilianLocationSampler
from ptbr_sampler.br_name_class import BrazilianNameSampler, NameComponents, TimePeriod
from ptbr_sampler.cli import app, main

__all__ = [
    'BrazilianLocationSampler',
    'BrazilianNameSampler',
    'NameComponents',
    'TimePeriod',
    'app',
    'main',
]

__version__ = '0.3.0'

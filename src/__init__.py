"""
Brazilian Name and Location Generator

This package provides tools for generating realistic Brazilian names and locations
based on population data and historical naming patterns.

Classes:
    TimePeriod: Enum for different historical time periods
    BrazilianNameSampler: Generator for Brazilian names
    BrazilianLocationSampler: Generator for Brazilian locations

The package requires JSON files containing population data and name statistics.
"""

from src.br_location_class import BrazilianLocationSampler
from src.br_name_class import BrazilianNameSampler, TimePeriod

# CLI module uses different import paths (ptbr_sampler.*) that may not be
# available in all environments. Import lazily to avoid breaking core imports.
try:
    from src.cli import app, main
except ImportError:
    app = None  # type: ignore[assignment]
    main = None  # type: ignore[assignment]

__all__ = ['TimePeriod', 'BrazilianNameSampler', 'BrazilianLocationSampler', 'app', 'main']

__version__ = '1.0.0'

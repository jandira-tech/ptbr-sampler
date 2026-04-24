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
# available in all environments. Import lazily to avoid breaking core imports
# and replace app/main with informative callables when the CLI isn't usable.
try:
    from src.cli import app, main
except ImportError as _cli_err:
    _cli_import_error = _cli_err

    def _cli_unavailable(*_args: object, **_kwargs: object) -> None:
        """Raised when the CLI is used without its optional dependencies."""
        raise ImportError(
            'The Claude Code CLI entrypoints (src.cli.app / src.cli.main) are not '
            'available in this environment. Install the CLI dependencies (typer, '
            'rich, richer) and ensure ptbr_sampler modules are importable before '
            'invoking app() or main().'
        ) from _cli_import_error

    app = _cli_unavailable  # type: ignore[assignment]
    main = _cli_unavailable  # type: ignore[assignment]

__all__ = ['BrazilianLocationSampler', 'BrazilianNameSampler', 'TimePeriod', 'app', 'main']

__version__ = '1.0.0'

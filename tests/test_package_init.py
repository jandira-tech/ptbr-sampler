"""Tests for the src package __init__: exports and CLI fallback."""

import pytest


def test_expected_exports():
    import src

    for name in ('TimePeriod', 'BrazilianNameSampler', 'BrazilianLocationSampler', 'app', 'main'):
        assert name in src.__all__
        assert hasattr(src, name)


def test_version_present():
    import src

    assert hasattr(src, '__version__')
    assert src.__version__


def test_cli_fallback_raises_descriptive_error():
    """When src.cli cannot be imported, app()/main() raise a clear ImportError.

    In this repo src.cli imports a separate ``ptbr_sampler`` package that
    isn't present, so ``from src.cli import app, main`` fails and the
    package-level proxy is installed.
    """
    import src

    # The proxy is a real callable, not None.
    assert src.app is not None
    assert src.main is not None

    with pytest.raises(ImportError, match='The Claude Code CLI entrypoints'):
        src.app()
    with pytest.raises(ImportError, match='The Claude Code CLI entrypoints'):
        src.main()

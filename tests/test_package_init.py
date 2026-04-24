"""Tests for the ptbr_sampler package __init__: exports and CLI entrypoints."""

import pytest


def test_expected_exports():
    import ptbr_sampler

    for name in (
        'TimePeriod',
        'BrazilianNameSampler',
        'BrazilianLocationSampler',
        'NameComponents',
        'app',
        'main',
    ):
        assert name in ptbr_sampler.__all__
        assert hasattr(ptbr_sampler, name)


def test_version_present():
    import ptbr_sampler

    assert hasattr(ptbr_sampler, '__version__')
    assert ptbr_sampler.__version__


def test_cli_entrypoints_callable():
    """``app`` and ``main`` are Typer callables now that the package rename
    has eliminated the legacy import fallback shim."""
    import ptbr_sampler

    assert callable(ptbr_sampler.app)
    assert callable(ptbr_sampler.main)


def test_help_runs_without_error():
    """Calling ``ptbr --help`` exits cleanly via ``python -m ptbr_sampler``."""
    import subprocess
    import sys

    run = subprocess.run(
        [sys.executable, '-m', 'ptbr_sampler', '--help'],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert 'generate' in run.stdout
    assert 'sample' in run.stdout

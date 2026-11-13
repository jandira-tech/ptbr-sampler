"""CLI integration tests for 0.3.0 Census 2022 default, 2010 opt-in, conditioning modes, and HF dataset commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ptbr_sampler.cli import app

runner = CliRunner()


def test_cli_generate_default_runs_census_2022() -> None:
    res = runner.invoke(app, ['generate', '-n', '2', '--format', 'json', '--quiet'])
    assert res.exit_code == 0, res.output
    assert '"name"' in res.output


def test_cli_generate_defaults_to_census_2022_and_supports_2010_opt_in() -> None:
    for extra in (
        (),
        ('--sex-conditioning', 'F'),
        ('--sex-conditioning', 'population'),
        ('--time-period', 'ate2020'),
        ('--time-period', '2020_2022'),
        ('--uf-conditioning',),
        ('--uf-conditioning', '--sex-conditioning', 'F', '--conditioning-mode', 'estimated'),
        ('--census-year', '2010'),
        ('--census-year', '2010', '--time-period', 'ate1930'),
    ):
        res = runner.invoke(app, ['generate', '--qty', '2', '--quiet', *extra])
        assert res.exit_code == 0, f'failed for {extra}: {res.output}'


def test_cli_generate_default_rejects_strict_joint_uf_and_sex_and_ate1930() -> None:
    bad_joint = runner.invoke(
        app,
        ['generate', '-n', '2', '--uf-conditioning', '--sex-conditioning', 'F'],
    )
    assert bad_joint.exit_code != 0
    assert 'estimated' in bad_joint.output

    bad_period = runner.invoke(app, ['generate', '-n', '2', '--time-period', 'ate1930'])
    assert bad_period.exit_code != 0
    assert 'ate1930' in bad_period.output

    ok_2010 = runner.invoke(
        app,
        ['generate', '-n', '2', '--census-year', '2010', '--time-period', 'ate1930', '--format', 'json', '--quiet'],
    )
    assert ok_2010.exit_code == 0, ok_2010.output

    ok_est = runner.invoke(
        app,
        [
            'generate',
            '-n',
            '2',
            '--uf-conditioning',
            '--sex-conditioning',
            'F',
            '--conditioning-mode',
            'estimated',
            '--format',
            'json',
            '--quiet',
        ],
    )
    assert ok_est.exit_code == 0, ok_est.output


def test_cli_sources_and_datasets_status_and_clear_cache(monkeypatch, tmp_path: Path) -> None:
    res_src = runner.invoke(app, ['sources', '--census-year', '2022'])
    assert res_src.exit_code == 0, res_src.output
    assert 'Census 2022' in res_src.output

    monkeypatch.setenv('PTBR_SAMPLER_CACHE_DIR', str(tmp_path / 'hf_cache'))
    status = runner.invoke(app, ['datasets', 'status', '--census-year', '2022'])
    assert status.exit_code == 0, status.output
    assert 'arthrod/ptbr-sampler-data' in status.output

    cleared = runner.invoke(app, ['datasets', 'clear-cache'])
    assert cleared.exit_code == 0, cleared.output


def test_cli_state_full_only_table_displays_state_name() -> None:
    res = runner.invoke(app, ['generate', '--qty', '2', '--state-full-only', '--uf', 'SP'])
    assert res.exit_code == 0, res.output
    assert 'São Paulo' in res.output


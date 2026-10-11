"""Contributor scripts under ``scripts/`` degrade gracefully on odd inputs."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import classify_unmatched_names_gemini as classify
from scripts import download_datasets


def test_second_names_report_tolerates_missing_percentage(tmp_path: Path):
    path = tmp_path / 'middle_names.json'
    path.write_text(json.dumps({'second_names': {'MARIA': {}}}), encoding='utf-8')

    assert download_datasets._validate_json_shape(path) == 'second_names: 1 rows; percentage_with_second=n/a'


def test_second_names_report_formats_numeric_percentage(tmp_path: Path):
    path = tmp_path / 'middle_names.json'
    path.write_text(json.dumps({'second_names': {}, 'percentage_with_second': 30.99}), encoding='utf-8')

    assert download_datasets._validate_json_shape(path) == 'second_names: 0 rows; percentage_with_second=30.9900%'


def test_unmatched_names_dedupe_against_the_given_output(tmp_path: Path):
    pending = classify.compute_unmatched_names(tmp_path / 'absent.jsonl', limit=1)
    assert len(pending) == 1

    done = tmp_path / 'custom.jsonl'
    done.write_text(json.dumps({'name': pending[0], 'gender': 'F'}) + '\n', encoding='utf-8')

    assert pending[0] not in classify.compute_unmatched_names(done, limit=1)


def test_existing_classifications_skip_non_object_lines(tmp_path: Path):
    path = tmp_path / 'c.jsonl'
    path.write_text('["MARIA"]\n{"name": "ana", "gender": "f"}\n', encoding='utf-8')

    assert classify._load_existing_classifications(path) == {'ANA': 'F'}


def test_dry_run_accepts_an_output_outside_the_repository(tmp_path: Path, capsys):
    output = tmp_path / 'elsewhere.jsonl'

    assert classify.main(['--dry-run', '--limit', '1', '--output', str(output)]) == 0
    assert f'Output: {output}' in capsys.readouterr().out

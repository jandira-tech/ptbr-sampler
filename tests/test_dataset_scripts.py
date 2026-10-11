"""Contributor scripts under ``scripts/`` degrade gracefully on odd inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


@pytest.fixture
def tiny_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Four names, one covered by genero-nomes, one in the shipped Gemini file."""
    names = tmp_path / 'names_data.json'
    names.write_text(
        json.dumps({'common_names_percentage': {'ate2010': {'names': {'ANA': 1, 'BIA': 1, 'CAU': 1, 'DUDA': 1}}}}),
        encoding='utf-8',
    )
    genero = tmp_path / 'nomes.csv'
    genero.write_text('first_name,classification\nANA,F\n', encoding='utf-8')
    canonical = tmp_path / 'canonical.jsonl'
    canonical.write_text(json.dumps({'name': 'BIA', 'gender': 'F'}) + '\n', encoding='utf-8')
    monkeypatch.setattr(classify, '_NAMES_DATA_JSON', names)
    monkeypatch.setattr(classify, '_GENERO_NOMES_CSV', genero)
    monkeypatch.setattr(classify, '_GEMINI_JSONL', canonical)
    return tmp_path


def test_unmatched_names_skip_the_shipped_classifications_for_a_fresh_output(tiny_corpus: Path):
    assert classify.compute_unmatched_names(tiny_corpus / 'fresh.jsonl') == ['CAU', 'DUDA']


def test_unmatched_names_resume_from_the_given_output(tiny_corpus: Path):
    output = tiny_corpus / 'run.jsonl'
    output.write_text(json.dumps({'name': 'CAU', 'gender': 'M'}) + '\n', encoding='utf-8')

    assert classify.compute_unmatched_names(output) == ['DUDA']
    assert classify.compute_unmatched_names(output, limit=0) == []


def test_existing_classifications_skip_non_object_lines(tmp_path: Path):
    path = tmp_path / 'c.jsonl'
    path.write_text(
        '["MARIA"]\n{"name": 123, "gender": "F"}\n{"name": "BIA", "gender": 1}\n{"name": "ana", "gender": "f"}\n', encoding='utf-8'
    )

    assert classify._load_existing_classifications(path) == {'ANA': 'F'}


def test_dry_run_accepts_an_output_outside_the_repository(tmp_path: Path, capsys):
    output = tmp_path / 'elsewhere.jsonl'

    assert classify.main(['--dry-run', '--limit', '1', '--output', str(output)]) == 0
    assert f'Output: {output.resolve()}' in capsys.readouterr().out


def test_dataset_requests_refuse_anything_but_https():
    with pytest.raises(ValueError, match='non-HTTPS'):
        download_datasets._https_request('file:///etc/passwd', 'ua')
    assert download_datasets._https_request('https://example.org/x', 'ua').full_url == 'https://example.org/x'


def test_second_names_report_rejects_boolean_percentage(tmp_path: Path):
    path = tmp_path / 'middle_names.json'
    path.write_text(json.dumps({'second_names': {}, 'percentage_with_second': True}), encoding='utf-8')

    assert download_datasets._validate_json_shape(path).endswith('percentage_with_second=n/a')

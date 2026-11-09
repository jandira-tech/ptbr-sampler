"""Keyed POP2026 updates over the authoritative 5,570-municipality CEP base."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ptbr_sampler.data_pipeline.io import write_json
from ptbr_sampler.data_pipeline.registry import STATE_NAMES, UF_CODES


def read_pop2026(path: Path) -> tuple[dict[int, int], dict[str, int], int, dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook['MUNICÍPIOS']
        municipalities: dict[int, int] = {}
        for row in sheet.iter_rows(min_row=3, values_only=True):
            uf, cod_uf, cod_munic, name, population, _ = row[:6]
            if uf is None or cod_uf is None or cod_munic is None:
                continue
            try:
                code = int(f'{int(cod_uf):02d}{int(cod_munic):05d}')
                value = int(population)
            except (TypeError, ValueError):
                continue
            if len(str(code)) == 7 and value >= 0:
                municipalities[code] = value
        states: dict[str, int] = {}
        national = 0
        state_sheet = workbook['BRASIL E UFS']
        for row in state_sheet.iter_rows(values_only=True):
            cells = list(row)
            if not cells or cells[0] is None:
                continue
            label = str(cells[0]).strip()
            numeric = next((cell for cell in reversed(cells) if isinstance(cell, (int, float))), None)
            if numeric is None:
                continue
            if label.upper().startswith('BRASIL'):
                national = int(numeric)
            else:
                for abbreviation, name in STATE_NAMES.items():
                    if label.upper() == name.upper():
                        states[abbreviation] = int(numeric)
        # POP2026 contains 5,570 historical municipalities plus Boa Esperança
        # do Norte (5101837), emancipated after the CEP base was assembled.
        if len(municipalities) not in {5_570, 5_571}:
            raise ValueError(f'POP2026 municipality count mismatch: {len(municipalities)}')
        totals = {
            'cities': len(municipalities),
            'states': len(states),
            'national_population': national,
            'municipal_population_sum': sum(municipalities.values()),
        }
        if not national:
            national = sum(municipalities.values())
            totals['national_population'] = national
        if sum(municipalities.values()) != national:
            raise ValueError(f'POP2026 total mismatch: cities={sum(municipalities.values())}, Brasil={national}')
        return municipalities, states, national, totals
    finally:
        workbook.close()


def rebuild_geography(
    base: dict[str, Any], population: dict[int, int], *, national_population: int, state_names: dict[str, str]
) -> dict[str, Any]:
    original = base.get('cities', {})
    if len(original) != len({str(info.get('uf_code', '')) + str(info.get('city_code', '')) for info in original.values()}):
        raise ValueError('CEP base contains duplicate IBGE municipality codes')
    cities: dict[str, dict[str, Any]] = {}
    state_totals = dict.fromkeys(state_names, 0)
    for key, old in original.items():
        code = f'{int(old["uf_code"]):02d}{int(old["city_code"]):05d}'
        if int(code) not in population:
            raise ValueError(f'POP2026 population join missing municipality {code} ({key})')
        item = dict(old)
        count = int(population[int(code)])
        item.update({'ibge_code': code, 'city_population': count})
        item.setdefault('cep_starts', item.get('cep_range_begins', ''))
        item.setdefault('cep_ends', item.get('cep_range_ends', ''))
        item.setdefault('cep_range_begins', item.get('cep_starts', ''))
        item.setdefault('cep_range_ends', item.get('cep_starts', ''))
        cities[key] = item
        state_totals[item['city_uf']] += count
    if len(cities) != len(original):
        raise ValueError('population join dropped municipalities')
    if sum(state_totals.values()) != national_population:
        raise ValueError(f'national reconciliation failed: {sum(state_totals.values())} != {national_population}')
    for item in cities.values():
        item['population_percentage_total'] = item['city_population'] * 100 / national_population
        item['population_percentage_state'] = item['city_population'] * 100 / state_totals[item['city_uf']]
    states = {
        name: {
            'state_abbr': abbreviation,
            'state_population': state_totals[abbreviation],
            'population_percentage': state_totals[abbreviation] * 100 / national_population,
            'uf_code': UF_CODES.get(abbreviation, ''),
        }
        for abbreviation, name in state_names.items()
        if state_totals[abbreviation] > 0
    }
    return {
        'cities': {'cities': cities, 'states': states},
        'locations': {'states': states, 'cities': cities},
        'table_totals': {'cities': len(cities), 'states': len(states), 'national_population': national_population},
    }


def rebuild_geography_files(base_path: Path, workbook_path: Path, cities_output: Path, locations_output: Path) -> dict[str, Any]:
    population, _, national, source_totals = read_pop2026(workbook_path)
    base = json.loads(base_path.read_text(encoding='utf-8'))
    base_codes = {int(f'{int(item["uf_code"]):02d}{int(item["city_code"]):05d}') for item in base['cities'].values()}
    unmatched = set(population) - base_codes
    matched_national = sum(population[code] for code in base_codes)
    result = rebuild_geography(base, population, national_population=matched_national, state_names=STATE_NAMES)
    if len(result['cities']['cities']) != 5_570 or len(result['locations']['states']) != 27:
        raise ValueError('geography must preserve 5,570 cities and all 27 UFs')
    write_json(cities_output, result['cities'])
    write_json(locations_output, result['locations'])
    provenance_totals = {
        'source_national_population': national,
        'unmatched_source_codes': sorted(unmatched),
        'unmatched_source_population': sum(population[code] for code in unmatched),
        'runtime_reconciled_population': matched_national,
    }
    return source_totals | result['table_totals'] | provenance_totals | {'source_municipalities': source_totals['cities']}

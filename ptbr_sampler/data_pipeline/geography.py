"""Keyed POP2026/DOU comparison over the 5,570-municipality CEP base."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ptbr_sampler.data_pipeline.io import file_metadata, write_json
from ptbr_sampler.data_pipeline.registry import SOURCES, STATE_NAMES, UF_CODES

# Only this documented source-only municipality may differ between the source
# UF totals and the legacy CEP-base join. Tolerance is exact, not a fudge factor.
DOCUMENTED_UNMATCHED = {'MT': {'ibge_code': 5_101_837, 'name': 'Boa Esperança do Norte', 'population': 5_983}}


def read_population_workbook(path: Path) -> tuple[dict[int, int], dict[str, int], int, dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        city_sheet = next((sheet for sheet in workbook if sheet.title.casefold() == 'municípios'), None)
        state_sheet = next((sheet for sheet in workbook if sheet.title.casefold() in {'brasil e ufs', 'br_uf'}), None)
        if city_sheet is None or state_sheet is None:
            raise ValueError(f'population workbook sheets missing in {path}')
        municipalities: dict[int, int] = {}
        city_ufs: dict[int, str] = {}
        for row in city_sheet.iter_rows(min_row=3, values_only=True):
            uf, cod_uf, cod_munic, _, population = row[:5]
            if uf is None or cod_uf is None or cod_munic is None:
                continue
            try:
                code = int(f'{int(cod_uf):02d}{int(cod_munic):05d}')
                value = int(population)
            except (TypeError, ValueError):
                continue
            if len(str(code)) == 7 and value >= 0:
                municipalities[code] = value
                city_ufs[code] = str(uf)
        states: dict[str, int] = {}
        national = 0
        for row in state_sheet.iter_rows(values_only=True):
            cells = list(row)
            if not cells or cells[0] is None:
                continue
            label = str(cells[0]).strip()
            numeric = next((cell for cell in reversed(cells) if isinstance(cell, (int, float))), None)
            if numeric is None:
                continue
            if label.casefold() == 'brasil':
                national = int(numeric)
            else:
                for abbreviation, name in STATE_NAMES.items():
                    if label.casefold() == name.casefold():
                        states[abbreviation] = int(numeric)
        if len(municipalities) not in {5_570, 5_571} or len(states) != 27:
            raise ValueError(f'population table coverage mismatch: cities={len(municipalities)}, states={len(states)}')
        if sum(states.values()) != national:
            raise ValueError(f'official UF populations do not reconcile to national: {sum(states.values())} != {national}')
        city_totals_by_uf = dict.fromkeys(UF_CODES, 0)
        for code, value in municipalities.items():
            city_totals_by_uf[city_ufs[code]] += value
        if city_totals_by_uf != states:
            wrong = {uf: (city_totals_by_uf[uf], states[uf]) for uf in UF_CODES if city_totals_by_uf[uf] != states[uf]}
            raise ValueError(f'official city-to-UF population mismatch: {wrong}')
        totals = {
            'cities': len(municipalities),
            'states': len(states),
            'national_population': national,
            'municipal_population_sum': sum(municipalities.values()),
        }
        return municipalities, states, national, totals
    finally:
        workbook.close()


def read_pop2026(path: Path) -> tuple[dict[int, int], dict[str, int], int, dict[str, Any]]:
    return read_population_workbook(path)


def compare_population_tables(pop2026: dict[int, int], dou2026: dict[int, int]) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    summary = {'added': 0, 'removed': 0, 'changed': 0, 'unchanged': 0}
    for code in sorted(set(pop2026) | set(dou2026)):
        corrected = pop2026.get(code)
        dou = dou2026.get(code)
        status = 'added' if dou is None else 'removed' if corrected is None else 'changed' if corrected != dou else 'unchanged'
        summary[status] += 1
        rows[str(code)] = {
            'status': status,
            'pop2026': corrected,
            'dou2026': dou,
            'delta': (corrected or 0) - (dou or 0),
        }
    return {'rows': rows, 'summary': summary}


def rebuild_geography(
    base: dict[str, Any],
    population: dict[int, int],
    *,
    national_population: int,
    state_names: dict[str, str],
    official_states: dict[str, int] | None = None,
) -> dict[str, Any]:
    original = base.get('cities', {})
    if len(original) != len({str(info.get('uf_code', '')) + str(info.get('city_code', '')) for info in original.values()}):
        raise ValueError('CEP base contains duplicate IBGE municipality codes')
    cities: dict[str, dict[str, Any]] = {}
    joined_totals = dict.fromkeys(state_names, 0)
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
        joined_totals[item['city_uf']] += count
    if len(cities) != len(original):
        raise ValueError('population join dropped municipalities')
    if official_states is None:
        if sum(joined_totals.values()) != national_population:
            raise ValueError(f'national reconciliation failed: {sum(joined_totals.values())} != {national_population}')
        official_states = joined_totals.copy()
    elif set(official_states) != set(state_names) or sum(official_states.values()) != national_population:
        raise ValueError('official UF sheet must contain exactly 27 UFs reconciling to national population')
    unmatched_by_uf = {uf: official_states[uf] - joined_totals[uf] for uf in state_names}
    for uf, unmatched in unmatched_by_uf.items():
        expected = DOCUMENTED_UNMATCHED.get(uf, {}).get('population', 0) if official_states is not joined_totals else 0
        if unmatched != expected:
            raise ValueError(f'undocumented city/UF population delta for {uf}: {unmatched} != {expected}')
    for item in cities.values():
        item['population_percentage_total'] = item['city_population'] * 100 / national_population
        item['population_percentage_state'] = item['city_population'] * 100 / official_states[item['city_uf']]
    states = {}
    reconciliation = {}
    for abbreviation, name in state_names.items():
        joined = joined_totals[abbreviation]
        official = official_states[abbreviation]
        unmatched = unmatched_by_uf[abbreviation]
        states[name] = {
            'state_abbr': abbreviation,
            'state_population': official,
            'joined_city_population': joined,
            'unmatched_source_population': unmatched,
            'population_percentage': official * 100 / national_population,
            'uf_code': UF_CODES.get(abbreviation, ''),
        }
        reconciliation[abbreviation] = {
            'official_population': official,
            'joined_population': joined,
            'unmatched_source_population': unmatched,
            'delta': joined - official,
            'tolerance': 0,
            'explanation': (
                'Boa Esperança do Norte (5101837), 5,983 residents, has no legacy CEP-base row and remains source-only.'
                if abbreviation == 'MT' and unmatched
                else 'Exact seven-digit-IBGE-code join; no delta permitted.'
            ),
        }
    return {
        'cities': {'cities': cities, 'states': states},
        'locations': {'states': states, 'cities': cities},
        'table_totals': {'cities': len(cities), 'states': len(states), 'national_population': national_population},
        'reconciliation': reconciliation,
    }


def rebuild_geography_files(
    base_path: Path,
    workbook_path: Path,
    cities_output: Path,
    locations_output: Path,
    *,
    comparison_workbook_path: Path | None = None,
) -> dict[str, Any]:
    population, official_states, national, source_totals = read_pop2026(workbook_path)
    base = json.loads(base_path.read_text(encoding='utf-8'))
    base_codes = {int(f'{int(item["uf_code"]):02d}{int(item["city_code"]):05d}') for item in base['cities'].values()}
    unmatched = set(population) - base_codes
    matched_national = sum(population[code] for code in base_codes)
    result = rebuild_geography(
        base,
        population,
        national_population=national,
        state_names=STATE_NAMES,
        official_states=official_states,
    )
    if len(result['cities']['cities']) != 5_570 or len(result['locations']['states']) != 27:
        raise ValueError('geography must preserve 5,570 cities and all 27 UFs')
    write_json(cities_output, result['cities'])
    write_json(locations_output, result['locations'])
    provenance_totals = {
        'source_national_population': national,
        'unmatched_source_codes': sorted(unmatched),
        'unmatched_source_population': sum(population[code] for code in unmatched),
        'runtime_reconciled_population': matched_national,
        'reconciliation': result['reconciliation'],
    }
    if comparison_workbook_path is None:
        raise ValueError('DOU comparison workbook is required for geography provenance')
    dou_population, dou_states, dou_national, _ = read_population_workbook(comparison_workbook_path)
    comparison = compare_population_tables(population, dou_population)
    comparison.update(
        {
            'source_url': SOURCES['estimativa_dou_2026'].url,
            'canonical_url': SOURCES['pop2026'].url,
            'sha256': file_metadata(comparison_workbook_path, url=SOURCES['estimativa_dou_2026'].url)['sha256'],
            'national_population_delta': national - dou_national,
            'state_population_deltas': {
                uf: official_states[uf] - dou_states[uf] for uf in UF_CODES if official_states[uf] != dou_states[uf]
            },
        }
    )
    comparison_path = locations_output.parent / 'sanitized' / 'geography' / 'pop2026_vs_dou2026.json'
    write_json(comparison_path, comparison)
    provenance_totals['comparison'] = comparison
    provenance_totals['comparison_path'] = comparison_path.relative_to(locations_output.parent).as_posix()
    return source_totals | result['table_totals'] | provenance_totals | {'source_municipalities': source_totals['cities']}

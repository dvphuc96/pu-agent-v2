"""Numeric evidence views; raw source text and offsets are never rewritten.

Calendar precision is compared per literal, not by joining numbers from
unrelated dates. Matching tokens is only a floor; semantic review still has
to establish the subject, attribution, period and meaning of a quantity.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache

NUMERIC_CONTRACT_VERSION = 'numeric-evidence-v2'
MAX_TEXT_CHARS = 200000
_NUMBER = re.compile(r'(?<!\w)\d+(?:[.,，．]\d+)*(?!\w)')
_CJK_DATE = re.compile(r'(?<![A-Za-z0-9_０-９])(?P<year>\d{4})\s*年(?:\s*(?P<month>\d{1,2})\s*月(?:\s*(?P<day>\d{1,2})\s*日)?)?')
_FULL_DATE = re.compile(r'(?<!\w)(?:\d{4}[-/.／．－]\d{1,2}[-/.／．－]\d{1,2}|\d{1,2}[-/.／．－]\d{1,2}[-/.／．－]\d{4})(?!\w)')
_MONTH_DATE = re.compile(r'(?<![\w/.-])(?:\d{4}[-/／－]\d{1,2}|\d{1,2}[/／]\d{4})(?![\w/.-])')
_VI_MONTH = re.compile(r'tháng\s*(\d{1,2})\s*(?:/|năm)\s*(\d{4})(?!\d)', re.IGNORECASE)
_UNHANDLED = re.compile(r'(?:令和|平成|昭和)\s*[\d元]+\s*年|[〇零一二三四五六七八九十百千]{2,}年')
_UNIT = re.compile(
    r'(?<!\w)(\d+(?:[.,，．]\d+)*)\s*(employees?|staff|people|người|nhân viên|'
    r'million|billion|triệu|tỷ|percent|%|usd|vnd|đồng|years?|năm|months?|tháng)(?!\w)', re.IGNORECASE,
)
_CJK_DURATION = re.compile(r'(?<![\w])([0-9０-９]{1,3})\s*(年|か月|ヶ月|箇月)(?!\d)')
_ALIASES = {
    'employee':'people', 'employees':'people', 'staff':'people', 'people':'people', 'người':'people', 'nhân viên':'people',
    'million':'million', 'triệu':'million', 'billion':'billion', 'tỷ':'billion', 'percent':'percent', '%':'percent',
    'usd':'usd', 'vnd':'vnd', 'đồng':'vnd', 'year':'years', 'years':'years', 'năm':'years',
    'month':'months', 'months':'months', 'tháng':'months', '年':'years', 'か月':'months', 'ヶ月':'months', '箇月':'months',
}


def canonical_number(raw: str) -> str:
    value = unicodedata.normalize('NFKC', str(raw or '')).replace(' ', '')
    if ',' in value and '.' in value:
        value = value.replace('.', '').replace(',', '.') if value.rfind(',') > value.rfind('.') else value.replace(',', '')
    elif ',' in value or '.' in value:
        separator = ',' if ',' in value else '.'
        groups = value.split(separator)
        if len(groups) > 2 or (len(groups[-1]) == 3 and len(groups[0]) <= 3):
            value = ''.join(groups)
        elif separator == ',':
            value = value.replace(',', '.')
    try:
        number = Decimal(value)
        if not number.is_finite():
            return value.casefold()
        normalized = format(number.normalize(), 'f')
    except (InvalidOperation, ValueError):
        return value.casefold()
    return (normalized.rstrip('0').rstrip('.') if '.' in normalized else normalized) or '0'


@dataclass(frozen=True)
class NumericLiteral:
    kind: str
    canonical_value: str
    raw_text: str
    start: int
    end: int
    notation: str
    precision: str = ''
    unit: str = ''
    qualifier: str = ''


@dataclass(frozen=True)
class NumericEvidence:
    literals: tuple[NumericLiteral, ...]
    numbers: frozenset[str]
    units: frozenset[tuple[str, str]]
    invalid_dates: tuple[str, ...] = ()
    unhandled: tuple[str, ...] = ()
    oversized: bool = False


def extract_numeric(text: str) -> NumericEvidence:
    if len(text) > MAX_TEXT_CHARS:
        return NumericEvidence((), frozenset(), frozenset(), oversized=True)
    return _extract_bounded(text)


@lru_cache(maxsize=128)
def _extract_bounded(text: str) -> NumericEvidence:
    unhandled = list(_UNHANDLED.finditer(text))
    literals, invalid, covered = [], [], [match.span() for match in unhandled]
    numbers, units = set(), set()

    def overlaps(start, end):
        return any(start < hi and end > lo for lo, hi in covered)

    def add_date(match, year, month=None, day=None, notation='date'):
        covered.append(match.span())
        try:
            date(year, month or 1, day or 1)
        except ValueError:
            invalid.append(match.group(0))
            return
        precision = 'day' if day is not None else 'month' if month is not None else 'year'
        value = f'{year:04d}' + (f'-{month:02d}' if month is not None else '') + (f'-{day:02d}' if day is not None else '')
        literals.append(NumericLiteral('calendar_date', value, match.group(0), *match.span(), notation, precision))
        numbers.update(str(part) for part in (year, month, day) if part is not None)

    for match in _CJK_DATE.finditer(text):
        if overlaps(*match.span()):
            continue
        parts = [int(unicodedata.normalize('NFKC', part)) if part else None for part in match.groups()]
        if re.match(r'\s*\d+\s*[月日]', text[match.end():]):
            covered.append(match.span())
            invalid.append(match.group(0))
        else:
            add_date(match, *parts, notation='cjk_calendar')
    for pattern, notation in ((_FULL_DATE, 'separated_date'), (_MONTH_DATE, 'separated_month'), (_VI_MONTH, 'vi_month')):
        for match in pattern.finditer(text):
            if overlaps(*match.span()):
                continue
            if notation == 'vi_month':
                month, year = map(int, match.groups())
                add_date(match, year, month, notation=notation)
            else:
                parts = re.split(r'[-/.]', unicodedata.normalize('NFKC', match.group(0)))
                values = list(map(int, parts))
                year_first = len(parts[0]) == 4
                if len(values) == 3:
                    year, month, day = values if year_first else (values[2], values[1], values[0])
                    add_date(match, year, month, day, notation=notation)
                else:
                    year, month = values if year_first else reversed(values)
                    add_date(match, year, month, notation=notation)
    for match in _NUMBER.finditer(text):
        if overlaps(*match.span()):
            continue
        value = canonical_number(match.group(0))
        prefix = text[max(0, match.start()-12):match.start()].strip().casefold()
        suffix = text[match.end():match.end()+1]
        qualifier = 'lower_bound' if suffix == '+' or re.search(r'(?:\bhơn|\bover|>)$', prefix) else 'approximate' if re.search(r'(?:\bkhoảng|\bgần|~)$', prefix) else ''
        literals.append(NumericLiteral('number', value, match.group(0), *match.span(), 'decimal', qualifier=qualifier))
        numbers.add(value)
    for pattern in (_UNIT, _CJK_DURATION):
        for match in pattern.finditer(text):
            if overlaps(*match.span()):
                continue
            raw_number, raw_unit = match.groups()
            value, unit = canonical_number(raw_number), _ALIASES[raw_unit.casefold()]
            units.add((value, unit))
            numbers.add(value)
            literals.append(NumericLiteral('duration' if unit in {'years', 'months'} else 'quantity', value, match.group(0), *match.span(), 'unit', unit=unit))
    return NumericEvidence(tuple(literals), frozenset(numbers), frozenset(units), tuple(invalid), tuple(match.group(0) for match in unhandled))


def compare_numeric(claim: str, excerpts: list[str]) -> dict:
    expected = extract_numeric(str(claim or ''))
    observed = [extract_numeric(str(excerpt or '')) for excerpt in excerpts]
    numbers = set().union(*(item.numbers for item in observed))
    units = set().union(*(item.units for item in observed))
    dates = [literal for item in observed for literal in item.literals if literal.kind == 'calendar_date']
    missing_numbers = sorted(expected.numbers - numbers)
    missing_units = sorted(expected.units - units)
    missing_dates = [literal.canonical_value for literal in expected.literals if literal.kind == 'calendar_date' and not any(
        other.canonical_value == literal.canonical_value or other.canonical_value.startswith(literal.canonical_value + '-') for other in dates
    ) and not (literal.precision == 'year' and literal.canonical_value in numbers)]
    limitation = expected.oversized or any(item.oversized for item in observed) or bool(expected.unhandled) or bool(
        (missing_numbers or missing_dates) and any(item.unhandled for item in observed)
    )
    reason = 'numeric_notation_unhandled' if limitation else 'numeric_or_date_mismatch' if missing_numbers or missing_dates or expected.invalid_dates else 'numeric_unit_mismatch' if missing_units else None
    return {'supported': reason is None, 'reason': reason, 'normalization_version': NUMERIC_CONTRACT_VERSION,
            'missing_numbers': missing_numbers, 'missing_dates': sorted(set(missing_dates)), 'missing_units': missing_units,
            'invalid_dates': list(expected.invalid_dates), 'unhandled_notations': sorted({token for item in (expected, *observed) for token in item.unhandled}),
            'input_limit_exceeded': expected.oversized or any(item.oversized for item in observed)}


def number_literals(text: str) -> set[str]:
    return set(extract_numeric(str(text or '')).numbers)


def date_literals(text: str) -> set[str]:
    return {item.canonical_value for item in extract_numeric(str(text or '')).literals if item.kind == 'calendar_date' and item.precision != 'year'}


def number_units(text: str) -> set[tuple[str, str]]:
    return set(extract_numeric(str(text or '')).units)

"""Calendar presentation helpers and structured availability attachment.

Legacy prose parsers remain for compatibility; reports never infer free time
from them. Only read_week_availability observations can authorize a slot claim.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

# pu/tools/calendar.py:        "- Title: 2026-07-14T09:00 → 2026-07-14T10:00 with a@b"
# pu/tools/google_calendar.py: "Title | 2026-07-14T09:00:00+07:00 | a@b" (or date-only)
_LOCAL_RE = re.compile(
    r":\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})(?::\d{2})?\s*→\s*"
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})(?::\d{2})?"
)
_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WEEKDAYS = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")


def _naive(value: str) -> datetime | None:
    from zoneinfo import ZoneInfo
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None)
    return dt


def parse_busy(text: str) -> list[tuple[datetime, datetime]]:
    """Extract busy intervals from ``list_events`` output text.

    Google's list output carries a start only (no end) — assume one hour,
    the common meeting length. A date-only entry is an all-day block.
    Prose lines ("No events found...", section headers) match nothing.
    """
    busy: list[tuple[datetime, datetime]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()
        local = _LOCAL_RE.search(line)
        if local:
            start, end = _naive(local.group(1)), _naive(local.group(2))
            if start is not None and end is not None and end > start:
                busy.append((start, end))
            continue
        if "|" in line:
            fields = [f.strip() for f in line.split("|")]
            if len(fields) < 2:
                continue
            start = _naive(fields[1])
            if start is None:
                continue
            if _DATE_ONLY_RE.fullmatch(fields[1]):
                busy.append((
                    start.replace(hour=0, minute=0, second=0, microsecond=0),
                    start.replace(hour=23, minute=59, second=0, microsecond=0),
                ))
            else:
                busy.append((start, start + timedelta(hours=1)))
    return busy


def _round_up_half_hour(dt: datetime) -> datetime:
    stamp = dt.replace(second=0, microsecond=0)
    if stamp.minute % 30:
        stamp += timedelta(minutes=30 - stamp.minute % 30)
    elif stamp < dt:  # seconds were dropped → still belongs to the next bucket
        stamp += timedelta(minutes=30)
    return stamp


def derive_free_slots(
    busy: list[tuple[datetime, datetime]],
    *,
    reference: datetime | None = None,
    days: int = 7,
    day_start: int = 9,
    day_end: int = 18,
    min_minutes: int = 45,
) -> list[dict]:
    """Free working-hour windows for the next ``days`` days (Mon–Fri).

    Today's already-elapsed hours are not offered as free time.
    """
    from zoneinfo import ZoneInfo

    reference = reference or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).replace(tzinfo=None)
    reference += timedelta(minutes=60)
    result: list[dict] = []
    intervals = sorted((s, e) for s, e in busy if e > s)
    for offset in range(days):
        day = (reference + timedelta(days=offset)).date()
        if day.weekday() >= 5:  # Sat/Sun are not working days
            continue
        window_start = datetime.combine(day, time(day_start))
        window_end = datetime.combine(day, time(17, 30) if day_end == 18 else time(day_end))
        lunch = (datetime.combine(day, time(12)), datetime.combine(day, time(13, 30)))
        if offset == 0:
            window_start = max(window_start, _round_up_half_hour(reference))
        overlap = sorted(
            (max(s, window_start), min(e, window_end))
            for s, e in [*intervals, lunch]
            if max(s, window_start) < min(e, window_end)
        )
        windows: list[tuple[datetime, datetime]] = []
        cursor = window_start
        for s, e in overlap:
            if s > cursor:
                windows.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < window_end:
            windows.append((cursor, window_end))
        windows = [(s, e) for s, e in windows if (e - s) >= timedelta(minutes=min_minutes)]
        if windows:
            result.append({
                "date": day.isoformat(),
                "label": f"{_WEEKDAYS[day.weekday()]} · {day.strftime('%d/%m')}",
                "windows": [f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}" for s, e in windows],
            })
    return result


def attach_free_slots(report, calendar_stage) -> bool:
    """Accept only a fresh structured observation, never start-only prose.

    list_events is context, not proof of complete coverage or event duration.
    The structured tool already computes slots from real start/end intervals.
    """
    import json

    from pu.reporting.availability import snapshot_is_current

    calls = getattr(calendar_stage, "tool_calls", None) or []
    for call in reversed(calls):
        if call.get("tool") != "read_week_availability" or not call.get("ok"):
            continue
        try:
            snapshot = json.loads(call.get("output") or "null")
            if not isinstance(snapshot, dict) or not snapshot_is_current(snapshot):
                return False
            slots = snapshot.get("slots", []) if snapshot.get("status") == "available" else []
            rendered = [{"date": slot["date"], "label": slot["label"], "windows": [slot["window"]]} for slot in slots]
        except (TypeError, ValueError, KeyError):
            return False
        report.metadata["availability"] = snapshot
        report.metadata["calendar_free_slots"] = rendered[:5]
        from pu.reporting.evidence import StructuredReportBuilder
        report.markdown = StructuredReportBuilder.render_markdown(report)
        return True
    return False

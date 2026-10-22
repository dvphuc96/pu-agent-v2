"""Availability from complete structured intervals, never inferred from prose."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pu.persistence.database import SQLiteDatabase
from pu.reporting.policy import AVAILABILITY_MAX_AGE_SECONDS


def empty_availability_lines(metadata: dict) -> list[str]:
    """Describe an empty observation without implying that an unchecked diary is free."""
    snapshot = metadata.get("availability")
    if not isinstance(snapshot, dict) or not snapshot or metadata.get("calendar_free_slots") or snapshot.get("slots"):
        return []
    if snapshot.get("status") == "available" and snapshot.get("checked_at"):
        result = ["Tại thời điểm kiểm tra, chưa tìm được khoảng trống đủ thời lượng trong phạm vi đã xem."]
    else:
        result = ["Chưa xác minh được lịch trống; cần kiểm tra trước khi đề xuất giờ họp."]
    if snapshot.get("checked_at"):
        result.append(f"Kiểm tra lúc {snapshot['checked_at']} · Múi giờ: {snapshot.get('timezone') or 'chưa xác định'}.")
    if snapshot.get("coverage") == "local_only":
        result.append("Chỉ kiểm tra lịch local; chưa kiểm tra Google Calendar và lịch đối tác.")
    else:
        result.append("Chưa kiểm tra lịch đối tác.")
    return result


def snapshot_is_current(snapshot: dict, *, reference: datetime | None = None) -> bool:
    """A report snapshot is an observation, never a reservation of a free slot."""
    try:
        stamp = datetime.fromisoformat(snapshot["checked_at"])
        if stamp.tzinfo is None:
            return False
        current = reference or datetime.now(UTC)
        age = (current - stamp).total_seconds()
        if not 0 <= age <= AVAILABILITY_MAX_AGE_SECONDS:
            return False
        for slot in snapshot.get("slots", []):
            start = datetime.fromisoformat(slot["start"])
            if start.tzinfo is None or start <= current:
                return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


def week_options(*, reference: datetime | None = None) -> dict:
    current = (reference or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
    return {"reference": current, "days": 7 - current.weekday(), "timezone": "Asia/Ho_Chi_Minh"}


@dataclass(frozen=True)
class AvailabilityPolicy:
    morning_start: time = time(9)
    morning_end: time = time(12)
    afternoon_start: time = time(13, 30)
    afternoon_end: time = time(17, 30)
    lead_minutes: int = 60
    max_slots: int = 3

    def __post_init__(self):
        if not (self.morning_start < self.morning_end <= self.afternoon_start < self.afternoon_end):
            raise ValueError("Cửa sổ làm việc không hợp lệ.")
        if not 0 <= self.lead_minutes <= 1440 or not 1 <= self.max_slots <= 20:
            raise ValueError("Giới hạn gợi ý lịch không hợp lệ.")


def free_windows(events: list[dict], *, start: datetime, days: int, duration: int,
                 policy: AvailabilityPolicy | None = None, allowed_dates: list[str] | None = None) -> list[dict]:
    policy = policy or AvailabilityPolicy()
    earliest = start + timedelta(minutes=policy.lead_minutes)
    busy = []
    for event in events:
        if event.get("cancelled") or event.get("transparent"):
            continue
        lo = datetime.fromisoformat(event["start"])
        hi = datetime.fromisoformat(event["end"])
        lo = lo.replace(tzinfo=start.tzinfo) if lo.tzinfo is None else lo.astimezone(start.tzinfo)
        hi = hi.replace(tzinfo=start.tzinfo) if hi.tzinfo is None else hi.astimezone(start.tzinfo)
        if hi <= lo:
            raise ValueError("Lịch có khoảng thời gian không hợp lệ.")
        busy.append((lo, hi))
    slots = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        if day.weekday() >= 5 or (allowed_dates is not None and day.isoformat() not in allowed_dates):
            continue
        lo = max(datetime.combine(day, policy.morning_start, tzinfo=start.tzinfo), earliest)
        lo = lo.replace(second=0, microsecond=0) + (
            timedelta(minutes=1) if lo.second or lo.microsecond else timedelta()
        )
        if lo.minute % 30:
            lo += timedelta(minutes=30 - lo.minute % 30)
        end = datetime.combine(day, policy.afternoon_end, tzinfo=start.tzinfo)
        breaks = [(datetime.combine(day, policy.morning_end, tzinfo=start.tzinfo),
                   datetime.combine(day, policy.afternoon_start, tzinfo=start.tzinfo))]
        intervals = sorted((max(s, lo), min(e, end)) for s, e in [*busy, *breaks] if max(s, lo) < min(e, end))
        cursor = lo
        windows = []
        for s, e in intervals:
            if s - cursor >= timedelta(minutes=duration):
                windows.append((cursor, s))
            cursor = max(cursor, e)
        if end - cursor >= timedelta(minutes=duration):
            windows.append((cursor, end))
        candidates = []
        for s, e in windows:
            while s + timedelta(minutes=duration) <= e:
                candidates.append((s, e))
                s += timedelta(minutes=((duration + 29) // 30) * 30)
        for s, e in candidates:
            candidate_end = s + timedelta(minutes=duration)
            slots.append(
                {
                    "start": s.isoformat(),
                    "end": candidate_end.isoformat(),
                    "free_until": e.isoformat(),
                    "date": day.isoformat(),
                    "label": day.strftime("%d/%m"),
                    "window": f"{s:%H:%M}–{candidate_end:%H:%M}",
                    "duration_minutes": duration,
                }
            )
    # One per day/session first, then fill spare capacity chronologically.
    selected, sessions = [], set()
    for slot in slots:
        key = (slot["date"], datetime.fromisoformat(slot["start"]).hour < 12)
        if key not in sessions:
            selected.append(slot)
            sessions.add(key)
        if len(selected) == policy.max_slots:
            break
    selected_starts = {slot["start"] for slot in selected}
    for slot in slots:
        if len(selected) >= policy.max_slots:
            break
        if slot["start"] not in selected_starts:
            selected.append(slot)
    return sorted(selected, key=lambda slot: slot["start"])


def read_availability(
    home,
    *,
    start_date: str = "",
    days: int = 7,
    duration: int = 45,
    timezone: str = "Asia/Ho_Chi_Minh",
    reference: datetime | None = None,
    policy: AvailabilityPolicy | None = None,
    allowed_dates: list[str] | None = None,
) -> dict:
    if not 1 <= days <= 30 or not 15 <= duration <= 480:
        raise ValueError("Khoảng xem lịch 1–30 ngày, thời lượng 15–480 phút.")
    if allowed_dates is not None:
        if not isinstance(allowed_dates, list) or len(allowed_dates) > 30:
            raise ValueError("Tối đa 30 ngày cụ thể.")
        for day in allowed_dates:
            if not isinstance(day, str) or datetime.fromisoformat(day).date().isoformat() != day:
                raise ValueError("Ngày cụ thể phải có dạng YYYY-MM-DD.")
    zone = ZoneInfo(timezone)
    current = (reference or datetime.now(UTC)).astimezone(zone)
    start = (
        datetime.combine(datetime.fromisoformat(start_date).date(), time(), tzinfo=zone)
        if start_date
        else current
    )
    start = max(start, current)
    end = datetime.combine((start + timedelta(days=days)).date(), time(), tzinfo=zone)
    database = SQLiteDatabase.from_home(home)
    with database.connection() as conn:
        rows = conn.execute(
            """SELECT id,title,start,"end",attendees FROM calendar_events
               WHERE owner_user_id = pu_current_owner()"""
        ).fetchall()
    events = [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "start": r["start"],
            "end": r["end"],
            "attendees": r["attendees"],
            "source": "Lịch local",
        }
        for r in rows
    ]
    checked = ["Lịch local"]
    warnings = []
    complete = True
    from pu.tools.google_calendar import is_connected

    if is_connected(home):
        try:
            events.extend(read_google_events(home, start, end))
            checked.append("Google Calendar (primary)")
        except Exception:
            complete = False
            warnings.append(
                "Chưa đọc được Google Calendar. Không thể xác nhận lịch trống; hãy kết nối lại rồi kiểm tra."
            )
    else:
        warnings.append("Chỉ kiểm tra lịch local. Kết nối Google Calendar để kiểm tra lịch Google.")
    try:
        slots = free_windows(events, start=start, days=days, duration=duration, policy=policy, allowed_dates=allowed_dates) if complete else []
    except (ValueError, KeyError, TypeError):
        slots, complete = [], False
        warnings.append("Một sự kiện thiếu start/end hợp lệ. Chưa thể xác nhận lịch trống.")
    relevant = []
    for ev in events:
        try:
            lo = datetime.fromisoformat(ev["start"])
            hi = datetime.fromisoformat(ev["end"])
            lo = lo.replace(tzinfo=zone) if lo.tzinfo is None else lo.astimezone(zone)
            hi = hi.replace(tzinfo=zone) if hi.tzinfo is None else hi.astimezone(zone)
            if lo < end and hi > start:
                relevant.append({**ev, "start": lo.isoformat(), "end": hi.isoformat()})
        except (ValueError, KeyError, TypeError):
            continue
    return {
        "status": "available" if complete else "unknown",
        "timezone": timezone,
        "checked_at": datetime.now(UTC).isoformat(),
        "checked_sources": checked,
        "coverage": "unknown" if not complete else "google_checked" if any("Google" in item for item in checked) else "local_only",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_minutes": duration,
        "allowed_dates": allowed_dates,
        "slots": slots,
        "events": sorted(relevant, key=lambda ev: ev["start"]),
        "warnings": warnings,
    }


def read_google_events(home, start: datetime, end: datetime) -> list[dict]:
    from googleapiclient.discovery import build

    from pu.tools.google_calendar import DEFAULT_SCOPES, _load_credentials

    credentials = _load_credentials(home, DEFAULT_SCOPES)
    if credentials is None:
        raise ValueError("Google credential không hợp lệ.")
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    events, token = [], None
    while True:
        response = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
                pageToken=token,
            )
            .execute()
        )
        for ev in response.get("items", []):
            if ev.get("status") == "cancelled" or ev.get("transparency") == "transparent":
                continue
            if any(a.get("self") and a.get("responseStatus") == "declined" for a in ev.get("attendees", [])):
                continue
            lo, hi = ev.get("start", {}), ev.get("end", {})
            events.append(
                {
                    "id": ev["id"],
                    "title": ev.get("summary", "Cuộc hẹn"),
                    "start": lo.get("dateTime") or lo.get("date"),
                    "end": hi.get("dateTime") or hi.get("date"),
                    "attendees": ", ".join(a.get("email", "") for a in ev.get("attendees", [])),
                    "source": "Google Calendar",
                }
            )
        token = response.get("nextPageToken")
        if not token:
            return events
        if len(events) > 5000:
            raise ValueError("Lịch vượt giới hạn đọc an toàn.")


def partner_availability(home, workspace, **options):
    """Compute against every busy interval, then show only partner meetings."""
    if not options:
        options = week_options()
    result = read_availability(home, **options)
    return filter_partner_events(result, workspace)


def requested_partner_availability(home, workspace, sources, *, reference=None):
    """Background research uses the same received-date week intent as chat."""
    from pu.reporting.scheduling import meeting_window, window_snapshot

    emails = [{'body_text': source.get('content', ''), 'internal_date': source.get('published_at')}
              for source in sources if source.get('source_type') == 'email' and source.get('enabled', True)]
    window = meeting_window(emails, reference=reference)
    if window['status'] == 'resolved':
        result = partner_availability(home, workspace, **window['arguments'], reference=reference)
    else:
        result = {'status':'unknown', 'slots':[], 'events':[], 'checked_sources':[], 'coverage':'unknown',
                  'timezone':'Asia/Ho_Chi_Minh', 'warnings':[window['warning']]}
    return window_snapshot(result, window)


def filter_partner_events(result, workspace):
    import re
    from email.utils import getaddresses
    from urllib.parse import urlparse
    result = {**result}
    domain = (urlparse(workspace["website"]).hostname or "").lower().removeprefix("www.")
    contact = workspace["contact"].lower()
    company = workspace["company"].lower()
    def matches(event):
        emails = {email.lower() for _, email in getaddresses([str(event.get("attendees", ""))])}
        if contact and contact in emails:
            return True
        if domain and any(email.rsplit("@", 1)[-1] == domain for email in emails):
            return True
        return len(company) >= 4 and bool(re.search(r"(?<!\w)" + re.escape(company) + r"(?!\w)", event["title"], re.IGNORECASE))
    result["events"] = [ev for ev in result["events"] if matches(ev)]
    result["scope"] = "Chỉ lịch của bạn; chưa kiểm tra lịch của đối tác."
    return result


def make_week_tool(home):
    import json

    from pu.tools.registry import Tool

    def read_week_availability(start_date="", days=None, duration=45, allowed_dates=None):
        options = {"start_date": start_date, "days": days if days is not None else 7, "duration": duration} if start_date or days is not None else {**week_options(), "duration": duration}
        if allowed_dates is not None:
            options["allowed_dates"] = allowed_dates
        result = read_availability(home, **options)
        result["scope"] = "Chỉ lịch của bạn trong phạm vi đã kiểm tra; chưa biết lịch của đối tác."
        return json.dumps(result, ensure_ascii=False)

    return Tool(name="read_week_availability", description="Read actual busy intervals and free appointments in a requested bounded date range; defaults to the remainder of the current Vietnam week. Explicit local/Google coverage and unknown failures.",
        input_schema={"type":"object","properties":{"start_date":{"type":"string"},"days":{"type":"integer","minimum":1,"maximum":30},"duration":{"type":"integer","minimum":15,"maximum":480},"allowed_dates":{"type":"array","items":{"type":"string"},"maxItems":30}},"additionalProperties":False}, fn=read_week_availability,
        capability="calendar:read", required_scope="calendar:read", side_effect=False, external=True)

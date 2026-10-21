"""Bounded meeting-week intent, independent of an LLM or calendar side effects."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
_MEETING = re.compile(r"họp|hẹn|trao đổi|buổi|thời gian dự kiến|meeting|appointment|reschedule|\bcall\b|\bdemo\b|\blịch\b|\brảnh\b|availability|calendar", re.IGNORECASE)


def _date(value):
    try:
        result = datetime.fromisoformat(str(value))
        return result.astimezone(ZONE) if result.tzinfo else result.replace(tzinfo=ZONE)
    except (ValueError, TypeError):
        return None


def _week_intents(text, *, require_meeting):
    lines = []
    for line in str(text or "")[:20000].splitlines():
        if re.search(r"^-*\s*(original message|forwarded message)|^on .+wrote:|^vào .+đã viết:", line.strip(), re.IGNORECASE):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    intents = set()
    for clause in re.split(r"[.!?;\n]", "\n".join(lines)):
        if require_meeting and not _MEETING.search(clause):
            continue
        if re.search(r"\b(tuần tới|tuần sau|next week)\b", clause, re.IGNORECASE):
            intents.add("next_week")
        if re.search(r"\b(tuần này|this week)\b", clause, re.IGNORECASE):
            intents.add("this_week")
        if re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{4})?\b|\b\d{4}-\d{2}-\d{2}\b|\b(ngày mai|tomorrow|thứ (?:[2-7]|hai|ba|tư|năm|sáu|bảy)|chủ nhật)\b", clause, re.IGNORECASE):
            intents.add("specific_date_unresolved")
    return intents


def meeting_window(emails=(), *, user_message="", reference=None):
    current = (reference or datetime.now(UTC)).astimezone(ZONE)
    anchor, basis, intents = current, "default", _week_intents(user_message, require_meeting=True)
    if intents:
        basis = "user"
    else:
        ranked = sorted(emails, key=lambda item: (_date(item.get("internal_date")) or datetime.min.replace(tzinfo=ZONE)), reverse=True)
        for email in ranked:
            found = _week_intents(email.get("body_text") or email.get("snippet"), require_meeting=True)
            if found:
                intents, basis = found, "email"
                anchor = _date(email.get("internal_date"))
                break
    if len(intents) > 1 or anchor is None or "specific_date_unresolved" in intents:
        return {"status": "needs_confirmation", "basis": basis, "label": "Chưa rõ tuần đề nghị họp", "timezone": str(ZONE),
                "warning": "Yêu cầu thời gian chưa rõ hoặc thiếu ngày nhận email; cần xác nhận tuần họp, chưa đề xuất giờ."}
    intent = next(iter(intents), "this_week")
    monday = anchor.date() - timedelta(days=anchor.weekday())
    if intent == "next_week":
        monday += timedelta(days=7)
    end = monday + timedelta(days=7)
    start = max(monday, current.date())
    result = {"status": "resolved" if start < end else "expired", "basis": basis, "intent": intent,
              "week_start": monday.isoformat(), "week_end": end.isoformat(), "timezone": str(ZONE), "duration_minutes": 45,
              "label": f"Lịch trống {monday:%d/%m}–{end - timedelta(days=1):%d/%m/%Y}"}
    if start < end:
        result["arguments"] = {"start_date": start.isoformat(), "days": (end - start).days, "duration": 45}
    else:
        result["warning"] = "Tuần đề nghị trong email đã qua; cần xác nhận lại thời gian, chưa tự chuyển sang tuần khác."
    return result


def window_snapshot(snapshot, window):
    """Copy an observation and attach the requested range without changing its coverage."""
    result = {**snapshot, "scheduling_window": {key: value for key, value in window.items() if key != "arguments"}}
    if window.get("requested_dates"):
        result["slots"] = [slot for slot in snapshot.get("slots", []) if slot.get("date") in window["requested_dates"]]
    return result


def briefing_window(emails=(), *, user_message="", reference=None):
    """Resolve explicit dates or offer clearly labelled alternatives to old mail.

    The original morning-worker policy stays conservative. An interactive
    assessment may research new alternatives, without pretending those were
    proposed or accepted by the sender. An unresolved USER constraint wins.
    """
    current = (reference or datetime.now(UTC)).astimezone(ZONE)
    window = meeting_window(emails, user_message=user_message, reference=current)
    ranked = sorted(emails, key=lambda item: (_date(item.get("internal_date")) or datetime.min.replace(tzinfo=ZONE)), reverse=True)
    duration = 45
    for text in [user_message, *[(email.get("body_text") or email.get("snippet") or "") for email in ranked]]:
        match = re.search(r"(?:thời lượng|duration|họp|meeting|buổi trao đổi)[^\n.!?]{0,50}?\b(\d{1,3})\s*(?:phút|minutes?|mins?)\b", text, re.IGNORECASE)
        if match and 15 <= int(match[1]) <= 480:
            duration = int(match[1])
            break
    window["duration_minutes"] = duration
    if "arguments" in window:
        window["arguments"] = {**window["arguments"], "duration": duration}
    dated_text = user_message if window["basis"] == "user" else ""
    anchor = current
    if not dated_text:
        for email in ranked:
            body = email.get("body_text") or email.get("snippet") or ""
            if _week_intents(body, require_meeting=True):
                dated_text, anchor = body, _date(email.get("internal_date"))
                break
    dates = []
    invalid = False
    for line in str(dated_text).splitlines():
        if re.search(r"^-*\s*(original message|forwarded message)|^on .+wrote:|^vào .+đã viết:", line.strip(), re.IGNORECASE):
            break
        if line.lstrip().startswith(">") or not re.search(r"họp|hẹn|buổi|trao đổi|meeting|appointment|lịch|thứ|thời gian|\bcall\b|\bdemo\b", line, re.IGNORECASE):
            continue
        for match in re.finditer(r"\b(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})/(\d{1,2})(?:/(\d{4}))?)\b", line):
            try:
                year = int(match[1] or match[6] or (anchor.year if anchor else 0))
                month, day = int(match[2] or match[5]), int(match[3] or match[4])
                dates.append(datetime(year, month, day, tzinfo=ZONE).date())
            except ValueError:
                invalid = True
    future = sorted({day for day in dates if day >= current.date()})
    if dates and not invalid and future:
        # Hour-specific requests require further resolution; do not claim any
        # time on the date meets an exact hour constraint.
        if re.search(r"\b\d{1,2}(?::\d{2}|h\d{0,2}|\s*giờ|\s*[ap]m)\b", dated_text, re.IGNORECASE):
            return {**window, "status": "needs_confirmation", "warning": "Thư có giờ hẹn cụ thể; cần xác nhận khung giờ và múi giờ trước khi đề xuất lựa chọn."}
        if (future[-1] - current.date()).days > 29:
            return {**window, "status": "needs_confirmation", "warning": "Ngày đề nghị ngoài phạm vi kiểm tra 30 ngày; cần thu hẹp khoảng lịch."}
        end = future[-1] + timedelta(days=1)
        return {"status": "resolved", "basis": window["basis"], "timezone": str(ZONE),
                "label": "Lịch trống vào ngày đề nghị", "duration_minutes": duration,
                "requested_dates": [day.isoformat() for day in future],
                "week_start": future[0].isoformat(), "week_end": end.isoformat(),
                "arguments": {"start_date": future[0].isoformat(), "days": (end - future[0]).days, "duration": duration,
                              "allowed_dates": [day.isoformat() for day in future]}}
    expired = window["status"] == "expired" or (dates and not invalid and not future)
    if window["basis"] == "user" and window["status"] != "resolved":
        return window
    if expired or (window["basis"] == "default" and not dates):
        end = current.date() + timedelta(days=10)
        return {"status": "resolved", "basis": "alternative" if expired else "suggested", "timezone": str(ZONE),
                "label": "Các lựa chọn lịch mới" if expired else "Các lựa chọn lịch trong 10 ngày tới",
                "duration_minutes": duration, "week_start": current.date().isoformat(), "week_end": end.isoformat(),
                "original_request": {k: v for k, v in window.items() if k != "arguments"},
                "warning": "Ngày/tuần hẹn trong thư đã qua. Đây là lựa chọn mới để anh cân nhắc, chưa được đối tác xác nhận." if expired else f"Kiểm tra cuộc họp {duration} phút trong giờ hành chính (mặc định 45 phút nếu chưa có thời lượng).",
                "arguments": {"start_date": current.date().isoformat(), "days": 10, "duration": duration}}
    return window

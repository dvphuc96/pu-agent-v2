"""User-facing invitation assessment: real orchestration, isolated providers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from evals.deterministic.test_inbox_chat import build
from pu.orchestration.partner_brief import is_partner_brief_request
from pu.reporting.chat_brief import render_partner_brief
from pu.reporting.identity import partner_identity
from pu.reporting.scheduling import briefing_window, window_snapshot
from pu.tools.gmail_research import GmailResearchReader

PROMPT = "Hoàn thành bản đánh giá lời mời hợp tác đang có trong Gmail: tìm email liên quan, xác định công ty từ nội dung thư, nghiên cứu thông tin công khai rồi kiểm tra Google Calendar. Không gửi thư hoặc tạo sự kiện nếu chưa được anh xác nhận."
REFERENCE = datetime(2026, 10, 20, 6, 20, tzinfo=UTC)


def invitation(name="Acme", domain="acme.example", mid="m1"):
    return {"gmail_id": mid, "thread_id": "t" + mid, "sender_name": "Receiver",
            "sender_email": "receiver@agency.example", "subject": "Hẹn buổi giới thiệu giải pháp hợp tác",
            "body_text": f"Tôi là Alex, Quản lý đối tác tại {name}.\n\nChúng tôi muốn hợp tác triển khai AI và hẹn họp.\nThời gian họp: 13/10/2026 hoặc 15/10/2026.\n\nTrân trọng\nAlex\nEmail: other@{domain}\nWebsite: https://{domain}",
            "snippet": "Lời mời hợp tác", "internal_date": "2026-10-12T07:08:00+00:00", "unread": 0,
            "display_url": f"https://mail.google.com/mail/u/0/#all/{mid}", "body_available": True}


@pytest.mark.parametrize("text", [PROMPT, "Trong inbox có thư mời hợp tác, nghiên cứu công ty và xem lịch giúp anh", "Review the partnership invitation in Gmail, don't send email.", "Tìm lời mời hợp tác trong Gmail; chưa gửi thư."])
def test_routes_existing_invitation_even_with_explicit_no_write_constraint(text):
    assert is_partner_brief_request(text)


@pytest.mark.parametrize("text", ["Hôm nay có email gì mới?", "Gửi email hợp tác cho Acme", "Viết code đọc email lời mời hợp tác", "Hướng dẫn tạo prompt nghiên cứu email", "Tìm thư hợp tác rồi gửi email cho họ", "Đừng đọc Gmail để tìm lời mời hợp tác", "Do not research the partnership email"])
def test_does_not_hijack_other_intents(text):
    assert not is_partner_brief_request(text)


def test_old_email_dates_become_labelled_new_options():
    window = briefing_window([invitation()], user_message=PROMPT, reference=REFERENCE)
    assert window["status"] == "resolved" and window["basis"] == "alternative"
    assert window["arguments"]["start_date"] == "2026-10-20"
    assert "đã qua" in window["warning"] and "chưa được đối tác xác nhận" in window["warning"]


def test_latest_reply_reschedules_old_invitation():
    reply = {**invitation(), "internal_date": "2026-10-20T04:00:00+00:00", "body_text": "Hẹn anh ngày 22/10/2026 nhé.\n> Họp ngày 13/10/2026"}
    window = briefing_window([invitation(), reply], reference=REFERENCE)
    assert window["requested_dates"] == ["2026-10-22"]
    assert window["basis"] == "email"


def test_future_dates_only_offer_matching_dates_and_never_override_user_uncertainty():
    window = briefing_window([invitation()], user_message="Xem lịch họp ngày 22/10/2026 hoặc 27/10/2026", reference=REFERENCE)
    assert window["requested_dates"] == ["2026-10-22", "2026-10-27"]
    observed = {"slots": [{"date": "2026-10-22"}, {"date": "2026-10-23"}]}
    assert window_snapshot(observed, window)["slots"] == [{"date": "2026-10-22"}]
    assert len(observed["slots"]) == 2
    unresolved = briefing_window([invitation()], user_message="Xem lịch họp ngày mai hoặc tuần tới", reference=REFERENCE)
    assert unresolved["status"] == "needs_confirmation"


def test_requested_dates_are_applied_before_slot_limit_and_duration_is_respected(tmp_path):
    from pu.db import connect
    from pu.reporting.availability import read_availability

    connect(tmp_path).close()
    result = read_availability(tmp_path, start_date="2026-10-22", days=6,
                               allowed_dates=["2026-10-27"], duration=60, reference=REFERENCE)
    assert result["slots"] and all(slot["date"] == "2026-10-27" for slot in result["slots"])
    assert all(slot["duration_minutes"] == 60 for slot in result["slots"])
    window = briefing_window([invitation()], user_message="Xem lịch họp 60 phút", reference=REFERENCE)
    assert window["arguments"]["duration"] == 60


def test_signature_and_sender_identity_remain_separate():
    identity = partner_identity(invitation())
    assert identity["name"] == "Acme" and identity["declared_contact"] == "Alex"
    warnings = " ".join(identity["affiliation_warnings"])
    assert "Receiver" in warnings and "Alex" in warnings
    assert "receiver@agency.example" in warnings and "other@acme.example" in warnings
    assert "chưa xác minh" in warnings.lower()


def fake_mail(monkeypatch, rows, *, thread_failure=False):
    calls = []
    def search(self, query, max_results=50):
        calls.append(("search", query))
        # The real reader stores the messages it just fetched before anyone
        # classifies them. An id that is still invisible stays a refusal.
        from pu.tools.gmail import upsert_messages

        upsert_messages(self.conn, rows)
        return json.dumps({"fresh": True, "messages": rows, "limited": False, "start": "2026-10-12T07:08:00+00:00", "end": datetime.now(UTC).isoformat()})
    def thread(self, thread_id, max_messages=30):
        calls.append(("thread", thread_id))
        if thread_failure:
            raise ValueError("offline")
        return json.dumps({"fresh": True, "messages": [row for row in rows if row["thread_id"] == thread_id], "limited": False})
    monkeypatch.setattr(GmailResearchReader, "search", search)
    monkeypatch.setattr(GmailResearchReader, "thread", thread)
    return calls


def test_chat_reads_old_invitation_and_returns_brief_without_proposals_or_writes(tmp_path, monkeypatch):
    calls = fake_mail(monkeypatch, [invitation()])
    app, _provider, collected = build(tmp_path, monkeypatch)
    result = app.respond(PROMPT, source="dashboard", stream=True)
    assert len(collected) == 1 and len(result.reports) == 1, result.reply
    assert calls[0][0] == "search" and "after:" not in calls[0][1]
    assert ("thread", "tm1") in calls
    assert "Thông tin công ty" in result.reply and "Câu hỏi còn thiếu" in result.reply
    assert "Receiver" in result.reply and "chưa kiểm tra Google Calendar" in result.reply
    assert "chưa gửi thư" in result.reply and "mail.google.com" in result.reply
    assert not any(call["tool"].startswith("propose_") for call in result.tool_calls)
    assert app.conn.execute("SELECT COUNT(*) FROM workspace_deliveries").fetchone()[0] == 0
    assert app.conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == 0
    assert not app.approval_service.list()
    # Exact read scope reaches the common tool harness and audit sink.
    assert {call["tool"] for call in result.tool_calls} >= {"search_gmail", "read_gmail_thread", "read_week_availability"}


def test_multiple_invitations_require_selection_before_public_research(tmp_path, monkeypatch):
    fake_mail(monkeypatch, [invitation(), invitation("OtherCorp", "other.example", "m2")])
    app, _provider, collected = build(tmp_path, monkeypatch)
    result = app.respond(PROMPT)
    assert not collected and not result.reports
    assert "nhiều lời mời" in result.reply and "OtherCorp" in result.reply


def test_named_company_is_selected_without_researching_other_candidates(tmp_path, monkeypatch):
    fake_mail(monkeypatch, [invitation(), invitation("OtherCorp", "other.example", "m2")])
    app, _provider, collected = build(tmp_path, monkeypatch)
    result = app.respond("Đánh giá lời mời hợp tác của Acme trong Gmail và xem lịch")
    assert [item["company"] for item in collected] == ["Acme"], result.reply


def test_failed_gmail_is_not_reported_as_an_empty_inbox(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("Gmail disconnected")
    monkeypatch.setattr(GmailResearchReader, "search", fail)
    app, _provider, collected = build(tmp_path, monkeypatch)
    result = app.respond(PROMPT)
    assert "Chưa tìm được" in result.reply and "disconnected" in result.reply
    assert not collected and not result.reports


def test_failed_thread_is_disclosed(tmp_path, monkeypatch):
    fake_mail(monkeypatch, [invitation()], thread_failure=True)
    app, _provider, _collected = build(tmp_path, monkeypatch)
    result = app.respond(PROMPT)
    assert "Chưa đọc được toàn bộ chuỗi thư" in result.reply


def test_renderer_keeps_questions_warnings_and_real_source_links():
    payload = {"title": "Acme", "executive_summary": "Cần xác minh người liên hệ trước khi chốt lịch.",
               "sections": {"company_context": "Acme có giải pháp OCR [S1].", "email_need": "Thư mời họp [S2]."},
               "sources": [{"id": "S1", "source_type": "web", "url": "https://acme.example", "title": "Company"},
                           {"id": "S2", "source_type": "email", "title": "Invitation", "metadata": {"gmail_url": "https://mail.google.com/mail/u/0/#all/m1"}}],
               "metadata": {"partner_identity": {"affiliation_warnings": ["Chưa rõ quyền đại diện."]},
                            "preparation_checklist": [{"key": "budget", "state": "unknown"}, {"key": "security_requirements", "state": "unknown"}]}}
    text = render_partner_brief(payload)
    assert "https://acme.example" in text and "https://mail.google.com" in text
    assert "Chi phí" in text and "Dữ liệu" in text and "quyền đại diện" in text
    assert "Đánh giá còn sơ bộ" in text


def test_calendar_stage_never_turns_start_only_prose_into_free_time():
    from evals.deterministic.test_calendar_slots import make_calendar_stage, make_report
    from pu.reporting.calendar_slots import attach_free_slots
    report = make_report()
    assert not attach_free_slots(report, make_calendar_stage(["No events found"]))
    assert "calendar_free_slots" not in report.metadata


def test_calendar_stage_uses_checked_structured_snapshot():
    from evals.deterministic.test_calendar_slots import make_calendar_stage, make_report
    from pu.reporting.calendar_slots import attach_free_slots
    now = datetime.now(UTC)
    future = now + timedelta(days=1)
    snapshot = {"status": "available", "checked_at": now.isoformat(), "slots": [{"date": future.date().isoformat(), "start": future.isoformat(), "label": "Ngày mai", "window": "09:00–09:45"}]}
    stage = make_calendar_stage([])
    stage.tool_calls.append({"tool": "read_week_availability", "ok": True, "output": json.dumps(snapshot)})
    report = make_report()
    assert attach_free_slots(report, stage)
    assert report.metadata["availability"] == snapshot

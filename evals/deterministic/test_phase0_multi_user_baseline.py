"""Phase 0 reproductions for static-analysis findings.

These tests encode the multi-user safety properties the current single-user
build does not provide. Each confirmed defect is marked xfail so the suite
stays green without changing product behavior. A strict xfail becomes an
error when the underlying defect is fixed and the marker should be removed.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from pu.approval.models import ApprovalStatus, ProposedAction
from pu.approval.repository import SQLiteApprovalRepository
from pu.config import Settings
from pu.core.interfaces.tools import ToolResult
from pu.db import connect
from pu.ops.agentops import AgentOpsHarness
from pu.ops.briefing import BriefingService
from pu.ops.tracing import Tracer
from pu.persistence import SQLiteAgentEventRepository, SQLiteDatabase
from pu.reporting.collection import CollectionConfig, collect_partner_sources
from pu.reporting.workspace import WorkspaceRepository
from pu.tools.calendar import make_list_tool

CANARY = "sk-phase0canarysecretxx"
GMAIL_TOOLS = {"read_gmail_today", "read_email_inbox", "search_gmail", "read_gmail_thread"}
CALENDAR_TOOLS = {"list_events", "read_week_availability"}
PAGE_TOOLS = {"read_web_page", "search_web"}


class _RecordingHarness:
    def __init__(self, state: dict):
        self.state = state

    def execute(self, name, arguments, context):
        self.state["harness"].append(name)
        self.state["in_harness"] = True
        try:
            if name in PAGE_TOOLS:
                page = {
                    "title": "Acme",
                    "url": arguments.get("url") or "https://acme.example",
                    "content": "Acme manufactures industrial widgets for business buyers.",
                    "source_type": "web",
                    "metadata": {"links": []},
                }
                if name == "search_web":
                    return ToolResult(ok=True, output=json.dumps({"results": []}))
                return ToolResult(ok=True, output=json.dumps(page))
            return ToolResult(ok=True, output="{}")
        finally:
            self.state["in_harness"] = False


def _app(state: dict):
    harness = _RecordingHarness(state)

    class _Publisher:
        def publish(self, *_args, **_kwargs):
            return None

    class _App:
        tool_harness = harness
        event_publisher = _Publisher()

    return _App()


def _mark_bypass(state: dict, label: str):
    def _wrapped(*_args, **_kwargs):
        if not state["in_harness"]:
            state["bypasses"].append(label)
        if label == "calendar":
            return {
                "status": "unknown",
                "slots": [],
                "events": [],
                "checked_sources": [],
                "warnings": ["stub"],
                "timezone": "Asia/Ho_Chi_Minh",
            }
        if label == "page":
            return {
                "title": "Acme",
                "url": "https://acme.example",
                "content": "Acme manufactures industrial widgets for business buyers.",
                "source_type": "web",
                "metadata": {"links": []},
            }
        return "ok"

    return _wrapped


def _fresh_state() -> dict:
    return {"harness": [], "in_harness": False, "bypasses": []}


class _CapturingOtel:
    def __init__(self):
        self.spans: list[dict] = []

    def start_span(self, name, attributes=None):
        self.spans.append({"name": name, "attributes": attributes or {}})
        return self

    def end(self):
        return None

    def start_as_current_span(self, name, attributes=None, context=None):
        self.spans.append({"name": name, "attributes": attributes or {}, "context": context is not None})
        return nullcontext(self)


def _action(action_id: str, principal: str) -> ProposedAction:
    stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    return ProposedAction(
        id=action_id,
        tool_name="send_message",
        arguments={"to": "person@example.com", "body": "hello"},
        action_hash="a" * 64,
        status=ApprovalStatus.EXECUTING,
        principal=principal,
        agent_id="report-agent",
        request_id="req-" + principal,
        workflow_id="wf-" + principal,
        tool_call_id="call-" + principal,
        capability="message:write",
        required_scope="message:write",
        side_effect=True,
        external=False,
        risk="medium",
        created_at=stamp,
        updated_at=stamp,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="milliseconds"),
        execution_id="exec-" + principal,
        metadata={"owner_user_id": principal},
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "AgentOps ghi SQLite agent_events đã redact, nhưng Tracer.event "
        "ghi nguyên payload vào JSONL và attribute OTel."
    ),
)
def test_agentops_redacts_canary_before_jsonl_and_otel(tmp_path):
    home = tmp_path / "home"
    settings = Settings(home=home, otel_endpoint="")
    settings.ensure_home()
    connect(home).close()
    repository = SQLiteAgentEventRepository(SQLiteDatabase.from_home(home))
    tracer = Tracer(settings)
    otel = _CapturingOtel()
    tracer._otel_tracer = otel
    AgentOpsHarness(repository, tracer=tracer).publish(
        "tool_complete",
        {"output": CANARY, "api_key": CANARY, "workflow_id": "wf-redact"},
    )

    leaks = []
    if CANARY in json.dumps(repository.list()):
        leaks.append("sqlite")
    if CANARY in tracer.path.read_text(encoding="utf-8"):
        leaks.append("jsonl")
    if CANARY in json.dumps(otel.spans):
        leaks.append("otel")
    assert leaks == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "recover_inflight đánh failed mọi proposed_actions status=executing, "
        "không xét principal/owner_user_id hay lease briefing còn hiệu lực."
    ),
)
def test_recover_inflight_preserves_other_owner_and_live_lease(tmp_path):
    home = tmp_path / "home"
    connect(home).close()
    database = SQLiteDatabase.from_home(home)
    repo = SQLiteApprovalRepository(database)
    live = _action("act-live", "user-a")
    other = _action("act-other", "user-b")
    pending = _action("act-pending", "user-a")
    pending = ProposedAction(
        **{**pending.__dict__, "status": ApprovalStatus.PENDING, "execution_id": None}
    )
    repo.create(live)
    repo.create(other)
    repo.create(pending)
    with database.connection() as conn:
        conn.execute(
            "INSERT INTO briefing_state(key, value) VALUES('lease_owner', 'worker-still-running')"
        )
        conn.execute(
            "INSERT INTO briefing_state(key, value) VALUES('lease_until', ?)",
            (str(int(datetime.now(UTC).timestamp()) + 600),),
        )

    repo.recover_inflight()

    assert repo.get("act-pending").status is ApprovalStatus.PENDING
    assert repo.get("act-live").status is ApprovalStatus.EXECUTING
    assert repo.get("act-other").status is ApprovalStatus.EXECUTING


@pytest.mark.xfail(
    strict=True,
    reason="Worker cycle gọi pu.tools.gmail.sync trực tiếp, không qua Tool Harness.",
)
def test_worker_gmail_read_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "gmail-token.json").write_text("{}", encoding="utf-8")
    state = _fresh_state()
    monkeypatch.setattr("pu.tools.gmail.sync", _mark_bypass(state, "gmail"))
    service = BriefingService(home, app_factory=lambda: _app(state))
    service.set_state("scan_requested", "1")
    monkeypatch.setattr(service, "schedule_meeting_briefs", lambda: None)
    service.cycle()
    assert state["bypasses"] == []
    assert any(name in GMAIL_TOOLS for name in state["harness"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Worker schedule_meeting_briefs gọi read_availability trực tiếp, "
        "không qua Tool Harness."
    ),
)
def test_worker_calendar_read_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    monkeypatch.setattr(
        "pu.reporting.availability.read_availability", _mark_bypass(state, "calendar")
    )

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr("pu.ops.briefing.datetime", _Frozen)
    service = BriefingService(home, app_factory=lambda: _app(state))
    service.schedule_meeting_briefs()
    assert state["bypasses"] == []
    assert any(name in CALENDAR_TOOLS for name in state["harness"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "collect_partner_sources đọc trang bằng fetch_source khi không có app, "
        "bỏ qua Tool Harness."
    ),
)
def test_collector_page_read_without_app_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    monkeypatch.setattr("pu.reporting.collection.fetch_source", _mark_bypass(state, "page"))
    monkeypatch.setattr("pu.reporting.collection.search_results", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "pu.reporting.collection.requested_partner_availability",
        _mark_bypass(state, "calendar"),
    )
    repo = WorkspaceRepository(home)
    workspace = repo.create("Acme", "https://acme.example")
    collect_partner_sources(
        repo,
        workspace["id"],
        config=CollectionConfig(max_search_queries=0, max_detail_pages=0, max_duration_seconds=5),
    )
    assert "page" not in state["bypasses"]
    assert any(name in PAGE_TOOLS for name in state["harness"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Collector vẫn gọi requested_partner_availability ngoài Tool Harness "
        "kể cả khi app đã được truyền cho luồng đọc trang."
    ),
)
def test_collector_calendar_read_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    monkeypatch.setattr(
        "pu.reporting.collection.requested_partner_availability",
        _mark_bypass(state, "calendar"),
    )
    repo = WorkspaceRepository(home)
    workspace = repo.create("Acme", "https://acme.example")
    collect_partner_sources(
        repo,
        workspace["id"],
        app=_app(state),
        config=CollectionConfig(max_search_queries=0, max_detail_pages=0, max_duration_seconds=5),
    )
    assert "calendar" not in state["bypasses"]
    assert any(name in CALENDAR_TOOLS for name in state["harness"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Tracer.__init__ gán self._trace_api = None sau _init_otel, "
        "nên span con không gắn được parent context."
    ),
)
def test_tracer_init_keeps_otel_trace_api(tmp_path, monkeypatch):
    sentinel = object()

    def _fake_init(self, _settings):
        self._trace_api = sentinel
        self._otel_provider = object()
        return object()

    monkeypatch.setattr(Tracer, "_init_otel", _fake_init)
    settings = Settings(home=tmp_path / "home", otel_endpoint="http://127.0.0.1:9")
    settings.ensure_home()
    tracer = Tracer(settings)
    assert tracer._otel_tracer is not None
    assert tracer._trace_api is sentinel


@pytest.mark.xfail(
    strict=True,
    reason=(
        "list_events nuốt lỗi Google Calendar bắt đầu bằng 'Google Calendar unavailable' "
        "và, khi lịch local trống, trả về 'No events found'."
    ),
)
def test_list_events_surfaces_google_error_instead_of_empty_diary(tmp_path, monkeypatch):
    import sqlite3

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE calendar_events (
            id INTEGER PRIMARY KEY,
            title TEXT,
            start TEXT,
            "end" TEXT,
            attendees TEXT,
            notes TEXT
        )
        """
    )
    monkeypatch.setattr("pu.tools.google_calendar.is_connected", lambda _home: True)
    monkeypatch.setattr(
        "pu.tools.google_calendar.list_google_events",
        lambda *_args: "Google Calendar unavailable (HttpError: backend unavailable)",
    )
    result = make_list_tool(connection, tmp_path).fn(start="2026-10-21", end="2026-10-21")
    connection.close()
    assert "No events found" not in result
    assert "Google Calendar unavailable" in result

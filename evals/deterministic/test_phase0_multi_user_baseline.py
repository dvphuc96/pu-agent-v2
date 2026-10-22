"""Phase 0 reproductions for static-analysis findings.

These tests encode the multi-user safety properties. A defect that has been
fixed runs as a normal test. The OpenTelemetry canary and the tracer
``_trace_api`` assignment are fixed in Phase 5. The parent-span gate is
OPS-01, separate from the assignment test below.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from pu.approval.models import ApprovalStatus, ProposedAction
from pu.approval.repository import SQLiteApprovalRepository
from pu.config import Settings
from pu.core.interfaces.tools import ToolResult
from pu.db import connect
from pu.harness.audit import ToolAuditRecord
from pu.harness.gateway import bind_harness, reset_bound_harness
from pu.ops.agentops import AgentOpsHarness
from pu.ops.briefing import BriefingService
from pu.ops.tracing import Tracer
from pu.persistence import SQLiteAgentEventRepository, SQLiteDatabase, SQLiteToolAuditSink
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
        workflow_id=None,
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


def _publish_canary(tmp_path):
    """Publish one canary event through AgentOps into SQLite, JSONL and a fake OTel tracer."""
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
        {"output": CANARY, "api_key": CANARY},
    )
    return repository, tracer, otel


def test_agentops_redacts_canary_in_jsonl(tmp_path):
    repository, tracer, _otel = _publish_canary(tmp_path)
    assert CANARY not in json.dumps(repository.list())
    assert CANARY not in tracer.path.read_text(encoding="utf-8")


def test_agentops_redacts_canary_in_otel(tmp_path):
    repository, _tracer, otel = _publish_canary(tmp_path)
    assert CANARY not in json.dumps(repository.list())
    assert CANARY not in json.dumps(otel.spans)


def test_sqlite_tool_audit_columns_redact_canary(tmp_path):
    home = tmp_path / "home"
    connect(home).close()
    database = SQLiteDatabase.from_home(home)
    SQLiteToolAuditSink(database).append(
        ToolAuditRecord(
            execution_id="exec-audit",
            request_id="req-audit",
            workflow_id=None,
            agent_id="report-agent",
            tool_call_id="call-audit",
            actor="agent",
            principal="local-user",
            tool="send_message",
            capability="message:write",
            required_scope="message:write",
            side_effect=True,
            external=False,
            arguments={"text": "hello"},
            action_hash="b" * 64,
            status="executed",
            timestamp="2026-10-21T00:00:00.000Z",
            policy="allow",
            reason=CANARY,
            latency_ms=1,
            result_summary=CANARY,
            error=CANARY,
        )
    )
    with database.connection() as conn:
        row = conn.execute(
            "SELECT reason, result_summary, error, record_json FROM tool_audit_events"
        ).fetchone()
    assert CANARY not in (row["record_json"] or "")
    assert CANARY not in (row["reason"] or "")
    assert CANARY not in (row["result_summary"] or "")
    assert CANARY not in (row["error"] or "")


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


def test_collector_page_read_without_app_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    monkeypatch.setattr("pu.reporting.collection.fetch_source", _mark_bypass(state, "page"))
    monkeypatch.setattr("pu.reporting.collection.search_results", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "pu.reporting.availability.read_availability",
        _mark_bypass(state, "calendar"),
    )
    monkeypatch.setattr(
        "pu.reporting.availability.requested_partner_availability",
        _mark_bypass(state, "calendar"),
    )
    repo = WorkspaceRepository(home)
    workspace = repo.create("Acme", "https://acme.example")
    token = bind_harness(_RecordingHarness(state))
    try:
        collect_partner_sources(
            repo,
            workspace["id"],
            config=CollectionConfig(max_search_queries=0, max_detail_pages=0, max_duration_seconds=5),
        )
    finally:
        reset_bound_harness(token)
    assert "page" not in state["bypasses"]
    assert any(name in PAGE_TOOLS for name in state["harness"])


def test_collector_calendar_read_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    monkeypatch.setattr(
        "pu.reporting.availability.read_availability",
        _mark_bypass(state, "calendar"),
    )
    monkeypatch.setattr(
        "pu.reporting.availability.requested_partner_availability",
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


def test_workspace_fetch_source_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    monkeypatch.setattr("pu.tools.web_source.fetch_source", _mark_bypass(state, "page"))
    repo = WorkspaceRepository(home)
    workspace = repo.create("Acme", "https://acme.example")
    from pu.ops.workspace_api import workspace_action

    workspace_action(
        home,
        {
            "op": "fetch_source",
            "workspace_id": workspace["id"],
            "url": "https://acme.example/about",
        },
        app_factory=lambda: _app(state),
    )
    assert state["bypasses"] == []
    assert any(name in PAGE_TOOLS for name in state["harness"])


def test_dashboard_gmail_sync_goes_through_tool_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = _fresh_state()
    settings = Settings(home=home)
    settings.ensure_home()
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: settings)
    monkeypatch.setattr("pu.tools.gmail.sync", _mark_bypass(state, "gmail"))
    from pu.ops.dashboard import gmail_sync_action

    token = bind_harness(_RecordingHarness(state))
    try:
        gmail_sync_action({})
    finally:
        reset_bound_harness(token)
    assert state["bypasses"] == []
    assert any(name in GMAIL_TOOLS for name in state["harness"])


def test_triage_ics_read_goes_through_tool_harness(tmp_path, monkeypatch):
    from pathlib import Path

    home = tmp_path / "home"
    home.mkdir()
    (home / "calendar.ics").write_text(
        "BEGIN:VEVENT\nSUMMARY:Local\nDTSTART:20261021T090000\nEND:VEVENT\n",
        encoding="utf-8",
    )
    state = _fresh_state()
    original = Path.read_text

    def _tracking_read(self, *args, **kwargs):
        if self.name == "calendar.ics" and not state["in_harness"]:
            state["bypasses"].append("calendar-ics")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _tracking_read)
    from pu.graph.workflows.triage import todays_events

    token = bind_harness(_RecordingHarness(state))
    try:
        todays_events(home)
    finally:
        reset_bound_harness(token)
    assert state["bypasses"] == []
    assert any(name in CALENDAR_TOOLS for name in state["harness"])


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

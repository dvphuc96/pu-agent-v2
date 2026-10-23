"""Phase 6 release gates MU-01 through MU-12.

Fixtures are synthetic users A and B. No real mailbox, token, or customer
record is used. A request without a live session does not receive a principal.
"""

from __future__ import annotations

import importlib
import inspect
import io
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pu.approval.models import ApprovalStatus, ProposedAction
from pu.approval.repository import SQLiteApprovalRepository
from pu.approval.service import HumanApprovalService
from pu.config import Settings
from pu.core.interfaces.llm import LLMResponse
from pu.core.interfaces.orchestration import ResearchWorkflowRequest
from pu.db import connect
from pu.harness.audit import ToolAuditRecord
from pu.identity.contract import AgentRequestRejected, is_backend_user_id
from pu.identity.crypto import decrypt
from pu.identity.directory import current_principal, provision_user
from pu.identity.files import OwnershipDenied
from pu.identity.legacy_import import LegacyImportRejected, import_legacy_rows
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.session import (
    SESSION_COOKIE,
    AuthStore,
    RequestDecision,
    act_as,
    attached_decision,
    session_principal,
)
from pu.identity.threads import spawn_inheriting
from pu.loop.agent import run_loop
from pu.ops.agentops import AgentOpsHarness
from pu.ops.telemetry import telemetry_scope
from pu.ops.tracing import Tracer
from pu.persistence import (
    SQLiteAgentEventRepository,
    SQLiteDatabase,
    SQLiteToolAuditSink,
    SQLiteWorkflowRepository,
)
from pu.reporting.models import StructuredReport
from pu.reporting.repository import FileReportRepository
from pu.reporting.workspace import WorkspaceRepository
from pu.tools.registry import ToolRegistry

BETA = "beta-release-secret"
CANARY = "sk-phase6canarysecretxx"
TOKEN_KEY = "phase6-release-key-xxxx"
ACCESS_TOKEN = "phase6-access-token-xx"
SKIP_POSTGRES = "PostgreSQL unavailable: set PU_POSTGRES_DSN to run MU-07"


@contextmanager
def _as(home, principal: Principal):
    with act_as(home, principal):
        yield


def _open(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    user_a = provision_user(conn)
    user_b = provision_user(conn)
    conn.commit()
    conn.close()
    return home, user_a, user_b


def _settings(home):
    settings = Settings(home=home, otel_endpoint="")
    settings.ensure_home()
    return settings


def _report_payload(report_id: str, secret: str) -> dict:
    return {
        "report_id": report_id,
        "workflow_id": "wf-fixture",
        "title": "Fixture",
        "executive_summary": secret,
        "markdown": secret,
        "sections": {"company": secret},
        "claims": [],
        "sources": [],
        "missing_information": [],
        "contradictions": [],
    }


def _action(action_id: str, principal: str, *, pending: bool, secret: str) -> ProposedAction:
    stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    return ProposedAction(
        id=action_id,
        tool_name="send_message",
        arguments={"body": secret},
        action_hash="a" * 64,
        status=ApprovalStatus.PENDING if pending else ApprovalStatus.EXECUTING,
        principal=principal,
        agent_id="report-agent",
        request_id="req-" + action_id,
        workflow_id=None,
        tool_call_id="call-" + action_id,
        capability="message:write",
        required_scope="message:write",
        side_effect=True,
        external=False,
        risk="medium",
        created_at=stamp,
        updated_at=stamp,
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="milliseconds"),
        execution_id=None if pending else "exec-" + action_id,
        metadata={"owner_user_id": principal},
    )


class _Handler:
    def __init__(self, method: str, path: str, headers: dict, body: bytes = b""):
        from pu.ops.dashboard import Handler

        self.statuses: list[int] = []
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = {"Host": "127.0.0.1:8765", **headers}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = self.statuses.append
        handler.send_header = lambda key, value: None
        handler.end_headers = lambda: None
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        self.body = handler.wfile.getvalue()


class _Provider:
    def __init__(self):
        self.calls = 0

    def complete(self, request, on_text=None):
        self.calls += 1
        return LLMResponse(text="ok")


def _bind_home(monkeypatch, home):
    monkeypatch.setattr("pu.config.load_settings", lambda: _settings(home))
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: _settings(home))


def test_release_seam_is_not_importable_and_cannot_install_a_principal(tmp_path):
    home, user_a, _user_b = _open(tmp_path)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pu.identity.seam")
    from pu.app import PU
    from pu.core.container import ApplicationDependencies

    assert "principal_seam" not in ApplicationDependencies.__dataclass_fields__
    assert "principal_seam" not in inspect.getsource(PU)
    anonymous = AuthStore(home).evaluate({"Host": "127.0.0.1"}, mutate=False)
    assert anonymous.principal is None
    assert anonymous.authenticated is False
    forged = RequestDecision(rejected=False, principal=user_a, session_id="forged")
    with attached_decision(forged):
        assert session_principal() is None
        with pytest.raises(PermissionError, match="no authenticated principal"):
            current_principal(connect(home))


def test_release_mu01_foreign_report_and_workflow_are_refused(tmp_path):
    home, user_a, user_b = _open(tmp_path)
    with _as(home, user_b):
        repo = WorkspaceRepository(home)
        workspace = repo.create("Beta Fixture", "https://beta.example")
        repo.attach_report(workspace["id"], _report_payload("report-betasecret", BETA))
        workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
        workflows.create("wf-beta", ResearchWorkflowRequest(prompt=BETA))
    with _as(home, user_a):
        with pytest.raises(KeyError) as report_error:
            WorkspaceRepository(home).require_report(workspace["id"], "report-betasecret")
        assert BETA not in str(report_error.value)
        assert workflows.get("wf-beta") is None


def test_release_mu02_foreign_artifact_bytes_are_refused(tmp_path):
    home, user_a, user_b = _open(tmp_path)
    report = StructuredReport(
        report_id="report-betaartifact",
        workflow_id="wf-beta",
        title="Fixture",
        executive_summary=BETA,
        sections={"company": BETA},
        claims=[],
        sources=[],
        markdown=BETA,
    )
    with _as(home, user_b):
        FileReportRepository(home).save(report)
    with _as(home, user_a):
        with pytest.raises(OwnershipDenied) as denied:
            FileReportRepository(home).read_bytes("report-betaartifact", "md")
        assert BETA not in str(denied.value)


def test_release_mu03_foreign_connection_makes_no_provider_call(tmp_path, monkeypatch):
    home, user_a, user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    store = AuthStore(home)
    foreign = store.save_oauth_token(
        owner_user_id=user_b.user_id,
        provider="gmail",
        token={"access_token": ACCESS_TOKEN},
    )
    calls: list[str] = []
    assert (
        store.use_oauth_connection(
            foreign,
            owner_user_id=user_a.user_id,
            provider_call=lambda token: calls.append(token["access_token"]) or "sent",
        )
        is None
    )
    assert calls == []
    blob = (home / "state.db").read_bytes()
    assert ACCESS_TOKEN.encode() not in blob
    assert TOKEN_KEY.encode() not in blob


def test_release_mu04_other_owner_approval_is_refused(tmp_path):
    home, user_a, user_b = _open(tmp_path)
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    with _as(home, user_b):
        repo.create(_action("act-b", user_b.user_id, pending=True, secret=BETA))
    with _as(home, user_a):
        with pytest.raises(KeyError) as denied:
            HumanApprovalService(repo).approve("act-b")
        assert BETA not in str(denied.value)
        assert repo.get("act-b") is None
    with _as(home, user_b):
        assert repo.get("act-b").status is ApprovalStatus.PENDING


def test_release_mu05_concurrent_jobs_do_not_mix_rows(tmp_path):
    home, user_a, user_b = _open(tmp_path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def job(owner_id: str, mark: str) -> None:
        try:
            barrier.wait(timeout=5)
            assert session_principal().user_id == owner_id
            conn = connect(home)
            conn.execute(
                "INSERT INTO calendar_events(title, start) VALUES(?, ?)",
                (mark, "2026-10-23T09:00:00"),
            )
            conn.commit()
            titles = [
                row[0]
                for row in conn.execute(
                    "SELECT title FROM calendar_events WHERE owner_user_id = pu_current_owner()"
                )
            ]
            conn.close()
            assert titles == [mark]
        except BaseException as exc:
            errors.append(exc)

    with _as(home, user_a):
        first = spawn_inheriting(lambda: job(user_a.user_id, "alpha-mark"), name="job-a")
    with _as(home, user_b):
        second = spawn_inheriting(lambda: job(user_b.user_id, "beta-mark"), name="job-b")
    first.join(timeout=10)
    second.join(timeout=10)
    assert errors == []


def test_release_mu06_revoked_session_blocks_the_next_request(tmp_path, monkeypatch):
    home, user_a, _user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    store = AuthStore(home)
    issued = store.issue_session(user_a)
    headers = {
        "Cookie": f"{SESSION_COOKIE}={issued.session_id}",
        "X-CSRF-Token": issued.csrf_token,
        "Host": "127.0.0.1",
    }
    live = store.evaluate(headers, mutate=True)
    assert live.authenticated is True
    store.revoke_session(issued.session_id)
    revoked = store.evaluate(headers, mutate=True)
    assert revoked.rejected is True
    assert revoked.reason == "session_revoked"
    with attached_decision(revoked):
        assert session_principal() is None
        with pytest.raises(PermissionError, match="no authenticated principal"):
            current_principal(connect(home))
    connection_id = store.save_oauth_token(
        owner_user_id=user_a.user_id,
        provider="gmail",
        token={"access_token": ACCESS_TOKEN},
    )
    assert store.revoke_oauth_connection(connection_id, owner_user_id=user_a.user_id) is True
    calls: list[str] = []
    assert (
        store.use_oauth_connection(
            connection_id,
            owner_user_id=user_a.user_id,
            provider_call=lambda token: calls.append(token["access_token"]),
        )
        is None
    )
    assert calls == []
    row = sqlite3.connect(home / "state.db").execute(
        "SELECT token_ciphertext FROM oauth_connections WHERE id=?",
        (connection_id,),
    ).fetchone()
    assert ACCESS_TOKEN in decrypt(
        row[0], owner_user_id=user_a.user_id, connection_id=connection_id
    ).decode()


def test_release_mu07_postgres_role_has_no_bypassrls():
    dsn = os.environ.get("PU_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip(SKIP_POSTGRES)
    from evals.deterministic.test_phase1_identity_ownership import (
        test_mu07_rls_hides_other_owner_and_role_cannot_bypass,
    )

    test_mu07_rls_hides_other_owner_and_role_cannot_bypass()


def test_release_mu08_canary_and_token_key_stay_out_of_sinks(tmp_path, monkeypatch):
    home, _user_a, _user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    settings = _settings(home)
    tracer = Tracer(settings)
    AgentOpsHarness(
        SQLiteAgentEventRepository(SQLiteDatabase.from_home(home)),
        tracer=tracer,
    ).publish("tool_complete", {"output": CANARY, "api_key": TOKEN_KEY})
    text = tracer.path.read_text(encoding="utf-8")
    assert CANARY not in text
    assert TOKEN_KEY not in text
    SQLiteToolAuditSink(SQLiteDatabase.from_home(home)).append(
        ToolAuditRecord(
            execution_id="exec-key",
            request_id="req-key",
            workflow_id=None,
            agent_id="worker",
            tool_call_id="call-key",
            actor="worker",
            principal="worker",
            tool="read_gmail_today",
            capability="email:read",
            required_scope="email:read",
            side_effect=False,
            external=True,
            arguments={"note": TOKEN_KEY},
            action_hash="c" * 64,
            status="executed",
            timestamp="2026-10-23T00:00:00.000Z",
            reason=CANARY,
            result_summary=TOKEN_KEY,
            error=CANARY,
        )
    )
    blob = (home / "state.db").read_bytes()
    assert TOKEN_KEY.encode() not in blob
    assert CANARY.encode() not in blob
    for path in home.rglob("*"):
        if path.is_file() and path.suffix in {".jsonl", ".json", ".log", ".txt"}:
            assert CANARY not in path.read_text(encoding="utf-8", errors="replace")
            assert TOKEN_KEY not in path.read_text(encoding="utf-8", errors="replace")


def test_release_mu09_live_lease_is_left_alone_and_dead_lease_is_owner_local(tmp_path):
    home, user_a, user_b = _open(tmp_path)
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    with _as(home, user_a):
        repo.create(_action("act-a", user_a.user_id, pending=False, secret="alpha"))
        with SQLiteDatabase.from_home(home).connection() as conn:
            conn.execute(
                "INSERT INTO briefing_state(key, value) VALUES('lease_until', ?)",
                (str(time.time() + 120),),
            )
        assert repo.recover_inflight() == []
        assert repo.get("act-a").status is ApprovalStatus.EXECUTING
        with SQLiteDatabase.from_home(home).connection() as conn:
            conn.execute(
                "UPDATE briefing_state SET value=? WHERE key='lease_until'",
                (str(time.time() - 30),),
            )
    with _as(home, user_b):
        repo.create(_action("act-b", user_b.user_id, pending=False, secret=BETA))
    with _as(home, user_a):
        recovered = repo.recover_inflight()
        assert [item.id for item in recovered] == ["act-a"]
        assert repo.get("act-a").status is ApprovalStatus.FAILED
        assert repo.get("act-b") is None
    with _as(home, user_b):
        assert repo.get("act-b").status is ApprovalStatus.EXECUTING


def test_release_mu10_legacy_import_without_a_map_is_refused(tmp_path):
    home, _user_a, _user_b = _open(tmp_path)
    conn = connect(home)
    with pytest.raises(LegacyImportRejected, match="no explicit user_id mapping"):
        import_legacy_rows(
            conn,
            None,
            [{"table": "facts", "legacy_owner": "local-user", "values": {"subject": "x", "content": BETA}}],
        )
    count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert count == 0
    assert BETA.encode() not in (home / "state.db").read_bytes()
    conn.close()


def test_release_mu11_idor_and_csrf_are_refused(tmp_path, monkeypatch):
    home, user_a, user_b = _open(tmp_path)
    _bind_home(monkeypatch, home)
    with _as(home, user_b):
        repo = WorkspaceRepository(home)
        workspace = repo.create("Beta Fixture", "https://beta.example")
        repo.attach_report(workspace["id"], _report_payload("report-betasecret", BETA))
    issued = AuthStore(home).issue_session(user_a)
    cookie = {"Cookie": f"{SESSION_COOKIE}={issued.session_id}"}
    listing = _Handler("GET", "/api/workspaces", cookie)
    assert listing.statuses == [200]
    assert BETA not in listing.body.decode()
    export = _Handler(
        "GET",
        f"/api/workspace/export?id={workspace['id']}&report=report-betasecret&format=md",
        cookie,
    )
    assert export.statuses == [400]
    assert BETA not in export.body.decode()
    body = json.dumps({"op": "detail", "workspace_id": workspace["id"]}).encode()
    missing = _Handler(
        "POST",
        "/api/workspace",
        {**cookie, "Content-Length": str(len(body))},
        body,
    )
    assert missing.statuses == [403]
    assert json.loads(missing.body)["error"] == "csrf"
    assert BETA not in missing.body.decode()


def test_release_mu12_http_foreign_workspace_is_remapped(tmp_path, monkeypatch):
    home, user_a, user_b = _open(tmp_path)
    _bind_home(monkeypatch, home)
    with _as(home, user_b):
        workspace = WorkspaceRepository(home).create("Beta Fixture", "https://beta.example")
        WorkspaceRepository(home).add_source(
            workspace["id"],
            title="Beta note",
            content=BETA,
            source_type="document",
        )
    issued = AuthStore(home).issue_session(user_a)
    payload = {
        "op": "detail",
        "workspace_id": workspace["id"],
        "owner_user_id": user_b.user_id,
        "owner": user_b.user_id,
        "user_id": user_b.user_id,
    }
    body = json.dumps(payload).encode()
    response = _Handler(
        "POST",
        "/api/workspace",
        {
            "Cookie": f"{SESSION_COOKIE}={issued.session_id}",
            "X-CSRF-Token": issued.csrf_token,
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        },
        body,
    )
    assert response.statuses == [200]
    decoded = response.body.decode()
    assert BETA not in decoded
    detail = json.loads(decoded)
    assert detail["workspace"]["id"] == user_a.workspace_id
    assert detail["workspace"]["company"] == "Personal"
    assert detail["workspace"]["id"] != workspace["id"]


def test_release_cookieless_request_fails_closed(tmp_path, monkeypatch):
    home, user_a, user_b = _open(tmp_path)
    _bind_home(monkeypatch, home)
    with _as(home, user_b):
        WorkspaceRepository(home).create("Beta Fixture", "https://beta.example")
        WorkspaceRepository(home).add_source(
            WorkspaceRepository(home).list()[0]["id"],
            title="Beta note",
            content=BETA,
            source_type="document",
        )
    anonymous = AuthStore(home).evaluate({"Host": "127.0.0.1"}, mutate=False)
    with attached_decision(anonymous):
        with pytest.raises(PermissionError, match="no authenticated principal"):
            current_principal(connect(home))
        scope = telemetry_scope(home)
        assert scope.denied is True
        tracer = Tracer(_settings(home))
        with pytest.raises(PermissionError, match="telemetry owner is not available"):
            tracer.event("tool", {"output": BETA})
    traces = list((home / "traces").rglob("*")) if (home / "traces").exists() else []
    for path in traces:
        if path.is_file():
            assert BETA not in path.read_text(encoding="utf-8", errors="replace")

    class _Agent:
        def __init__(self):
            self.conn = connect(home)
            self.approval_service = None
            self.event_publisher = None

    monkeypatch.setattr("pu.ops.dashboard.get_agent", lambda: _Agent())
    body = b'{"op":"reject","id":"missing"}'
    denied = _Handler(
        "POST",
        "/api/approvals",
        {"Content-Length": str(len(body)), "Content-Type": "application/json"},
        body,
    )
    assert denied.statuses == [401]
    assert json.loads(denied.body)["error"] == "no authenticated principal"
    assert user_a.user_id not in denied.body.decode()
    assert BETA not in denied.body.decode()


def test_release_dashboard_approval_actor_is_the_session_principal(tmp_path, monkeypatch):
    home, user_a, _user_b = _open(tmp_path)
    _bind_home(monkeypatch, home)
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    service = HumanApprovalService(repo)
    issued = AuthStore(home).issue_session(user_a)
    with attached_decision(
        AuthStore(home).evaluate(
            {"Cookie": f"{SESSION_COOKIE}={issued.session_id}", "Host": "127.0.0.1"},
            mutate=False,
        )
    ):
        repo.create(_action("act-a", user_a.user_id, pending=True, secret="alpha"))

    class _Publisher:
        def publish(self, *args, **kwargs):
            return None

    class _Agent:
        def __init__(self):
            self.conn = connect(home)
            self.approval_service = service
            self.event_publisher = _Publisher()

    monkeypatch.setattr("pu.ops.dashboard.get_agent", lambda: _Agent())
    body = json.dumps({"op": "reject", "id": "act-a", "note": "no"}).encode()
    response = _Handler(
        "POST",
        "/api/approvals",
        {
            "Cookie": f"{SESSION_COOKIE}={issued.session_id}",
            "X-CSRF-Token": issued.csrf_token,
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        },
        body,
    )
    assert response.statuses == [200]
    payload = json.loads(response.body)
    assert payload["action"]["decided_by"] == user_a.user_id
    assert is_backend_user_id(payload["action"]["decided_by"])
    assert payload["action"]["decided_by"] not in {
        "local-human",
        "local-dashboard-user",
        "local-user",
    }


def test_release_run_loop_without_a_principal_does_not_call_the_provider(tmp_path):
    home, user_a, _user_b = _open(tmp_path)
    provider = _Provider()
    with pytest.raises(AgentRequestRejected, match="missing principal"):
        run_loop(provider, "model", "", [], ToolRegistry(), object())
    assert provider.calls == 0
    admin = Principal(PrincipalKind.PLATFORM_ADMIN, user_a.user_id, user_a.workspace_id)
    with _as(home, admin), pytest.raises(AgentRequestRejected, match="missing principal"):
        run_loop(provider, "model", "", [], ToolRegistry(), object())
    assert provider.calls == 0
    with _as(home, user_a):
        result = run_loop(provider, "model", "", [], ToolRegistry(), object())
    assert provider.calls == 1
    assert result.reply == "ok"


def test_release_provider_reads_stay_inside_the_harness():
    from pu.graph.workflows.triage import todays_events
    from pu.ops.dashboard import gmail_sync_action
    from pu.ops.workspace_api import workspace_action
    from pu.reporting import collection

    gmail = inspect.getsource(gmail_sync_action)
    assert gmail.count("gmail.sync(") == 1
    assert "lambda: gmail.sync(" in gmail
    assert "execute_worker_read(" in gmail
    triage = inspect.getsource(todays_events)
    assert "execute_worker_read(" in triage
    assert "BoundaryHarness" in triage
    workspace = inspect.getsource(workspace_action)
    assert "execute_worker_read(" in workspace
    assert "BoundaryHarness(lambda: fetch_source(url))" in workspace
    collector = Path(collection.__file__).read_text(encoding="utf-8")
    assert "execute_worker_read(" in collector
    assert "fetch_source(url)" in collector
    direct = []
    root = Path(__file__).resolve().parents[2] / "pu"
    for path in root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "gmail.sync(" in line and "lambda" not in line and "def sync" not in line:
                direct.append(f"{path}:{line.strip()}")
    assert direct == []


def test_release_no_xfail_and_token_key_is_not_committed():
    root = Path(__file__).resolve().parents[2]
    evals = root / "evals" / "deterministic"
    marker = "pytest.mark." + "xfail"
    call = "pytest." + "xfail"
    for path in evals.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        assert marker not in text
        assert call not in text
    forbidden = {".env", "credentials.json", "token.json", "gmail-token.json", "client_secret.json"}
    assignment = "PU_TOKEN_KEY" + "="
    leaked: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}
        ]
        for name in filenames:
            path = Path(dirpath) / name
            if (name in forbidden or name.startswith(".env")) and name != ".env.example":
                leaked.append(str(path))
                continue
            if path.suffix not in {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".example", ".env", ".ini"}:
                continue
            if "evals" in path.parts and path.suffix == ".py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if assignment not in line:
                    continue
                value = line.split(assignment, 1)[1].strip().strip("\"'")
                if len(value) >= 16 and not value.startswith("$") and "os.environ" not in line:
                    leaked.append(f"{path}:{value[:4]}…")
    assert leaked == []


def test_release_cookieless_probes_do_not_touch_legacy_private_data(tmp_path, monkeypatch):
    """Loopback without a cookie is 401 before any private read or write.

    MU-12 still remaps a foreign workspace_id for an authenticated caller.
    These probes never reach that remap: there is no principal to remap onto.
    """
    from pu.graph.workflows.triage import todays_events
    from pu.harness.gateway import job_owner, worker_context
    from pu.identity.files import private_file
    from pu.ops.chat_runs import active_chat
    from pu.tools.gmail import _token_path

    home, user_a, user_b = _open(tmp_path)
    _bind_home(monkeypatch, home)
    token = "phase6-gmail-token-canary"
    (home / "gmail-token.json").write_text(token, encoding="utf-8")
    knowledge = home / "knowledge"
    knowledge.mkdir()
    (knowledge / "note.txt").write_text(BETA, encoding="utf-8")
    today = datetime.now().strftime("%Y%m%d")
    (home / "calendar.ics").write_text(
        f"BEGIN:VEVENT\nSUMMARY:phase6-legacy-calendar\nDTSTART:{today}T090000\nEND:VEVENT\n",
        encoding="utf-8",
    )
    reads: list[str] = []

    def spy_sync(*_args, **_kwargs):
        reads.append((home / "gmail-token.json").read_text(encoding="utf-8"))
        return "synced"

    monkeypatch.setattr("pu.tools.gmail.sync", spy_sync)

    def post(path: str, payload: dict, issued=None):
        body = json.dumps(payload).encode()
        headers = {"Content-Length": str(len(body)), "Content-Type": "application/json"}
        if issued is not None:
            headers["Cookie"] = f"{SESSION_COOKIE}={issued.session_id}"
            headers["X-CSRF-Token"] = issued.csrf_token
        return _Handler("POST", path, headers, body)

    sync = post("/api/gmail/sync", {})
    assert sync.statuses == [401]
    assert json.loads(sync.body)["error"] == "no authenticated principal"
    assert reads == []
    assert token not in sync.body.decode()

    reindex = post("/api/knowledge", {"op": "reindex"})
    assert reindex.statuses == [401]
    search = post("/api/knowledge", {"op": "search", "query": BETA})
    assert search.statuses == [401]
    assert BETA not in reindex.body.decode() + search.body.decode()

    created = post("/api/workspace", {"op": "create", "company": BETA})
    assert created.statuses == [401]
    listed = _Handler("GET", "/api/workspaces", {})
    assert listed.statuses == [401]
    assert BETA not in created.body.decode() + listed.body.decode()

    anonymous = AuthStore(home).evaluate({"Host": "127.0.0.1"}, mutate=False)
    with attached_decision(anonymous):
        with pytest.raises(PermissionError, match="no authenticated principal"):
            job_owner(home)
        with pytest.raises(PermissionError, match="no authenticated principal"):
            worker_context(owner_user_id="")
        with pytest.raises(PermissionError, match="no authenticated principal"):
            private_file(home, "gmail-token.json")
        with pytest.raises(PermissionError, match="no authenticated principal"):
            _token_path(home)
        with pytest.raises(PermissionError, match="no authenticated principal"):
            todays_events(home)
        with pytest.raises(PermissionError, match="no authenticated principal"):
            current_owner = connect(home)
            try:
                from pu.identity.scope import current_owner_user_id

                current_owner_user_id(current_owner)
            finally:
                current_owner.close()

    conn = connect(home)
    count = conn.execute(
        "SELECT COUNT(*) FROM knowledge_sources WHERE owner_user_id = ''"
    ).fetchone()[0]
    count += conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE owner_user_id = '' OR content LIKE ?",
        (f"%{BETA}%",),
    ).fetchone()[0]
    workspaces = conn.execute(
        "SELECT COUNT(*) FROM research_workspaces WHERE owner_user_id = '' OR company = ?",
        (BETA,),
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="owner_user_id is required"):
        conn.execute(
            "INSERT INTO facts(subject, content, owner_user_id) VALUES('s', ?, '')",
            (BETA,),
        )
    conn.close()
    assert count == 0
    assert workspaces == 0
    assert reads == []

    with active_chat("run-a", user_a.user_id) as event:
        cookieless = post("/api/chat/stop", {"request_id": "run-a"})
        assert cookieless.statuses == [401]
        issued_b = AuthStore(home).issue_session(user_b)
        unknown = post("/api/chat/stop", {"request_id": "run-missing"}, issued_b)
        cross = post("/api/chat/stop", {"request_id": "run-a"}, issued_b)
        assert cross.statuses == unknown.statuses == [200]
        assert json.loads(cross.body) == json.loads(unknown.body) == {"accepted": False}
        assert event.is_set() is False
        issued_a = AuthStore(home).issue_session(user_a)
        owned = post("/api/chat/stop", {"request_id": "run-a"}, issued_a)
        assert owned.statuses == [200]
        assert json.loads(owned.body)["accepted"] is True
        assert event.is_set() is True


def test_release_automatic_briefing_records_the_worker_owner(tmp_path):
    from pu.identity.worker_job import WorkerJob

    home, _user_a, user_b = _open(tmp_path)
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    service = HumanApprovalService(repo)
    job = WorkerJob.open(
        owner_user_id=user_b.user_id,
        workspace_id=user_b.workspace_id,
        expires_at=time.time() + 60,
    )
    try:
        repo.create(_action("act-auto", user_b.user_id, pending=True, secret="alpha"))
        rejected = service.reject("act-auto", decided_by="automatic-briefing")
    finally:
        job.close()
    assert rejected.decided_by == user_b.user_id
    assert is_backend_user_id(rejected.decided_by)


def test_release_google_tokens_stay_with_their_owner(tmp_path, monkeypatch):
    """Drive and Calendar tokens are per owner, like Gmail.

    User A and user B each connect and each read only their own file.
    Neither opens the legacy home token. A cookieless request is 401.
    The database-local owner is the only principal that still sees the
    legacy home file.
    """
    import sys
    from types import ModuleType

    from pu.identity.files import database_local_owner, owner_root
    from pu.tools import google_calendar, google_drive

    home, user_a, user_b = _open(tmp_path)
    _bind_home(monkeypatch, home)
    canary = "phase6-shared-google-token"
    (home / "drive-token.json").write_text(canary, encoding="utf-8")
    (home / "google-token.json").write_text(canary, encoding="utf-8")
    shared_reads: list[str] = []
    loaded: list[str] = []
    holder = {"token": ""}
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes
    original_open = Path.open

    def _shared(path: Path) -> bool:
        return path.name in {"drive-token.json", "google-token.json"} and path.parent == home

    def tracking_read_text(self, *args, **kwargs):
        if _shared(self):
            shared_reads.append(str(self))
        return original_read_text(self, *args, **kwargs)

    def tracking_read_bytes(self, *args, **kwargs):
        if _shared(self):
            shared_reads.append(str(self))
        return original_read_bytes(self, *args, **kwargs)

    def tracking_open(self, *args, **kwargs):
        if _shared(self):
            shared_reads.append(str(self))
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)
    monkeypatch.setattr(Path, "read_bytes", tracking_read_bytes)
    monkeypatch.setattr(Path, "open", tracking_open)

    class FakeCredentials:
        def __init__(self, token: str = ""):
            self.valid = True
            self.expired = False
            self.refresh_token = None
            self.token = token

        @classmethod
        def from_authorized_user_file(cls, path, scopes=None):
            loaded.append(str(path))
            return cls(Path(path).read_text(encoding="utf-8"))

        def to_json(self):
            return json.dumps({"token": self.token})

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes=None):
            return cls()

        @classmethod
        def from_client_config(cls, config, scopes=None):
            return cls()

        def run_local_server(self, port=0):
            return FakeCredentials(holder["token"])

    class _Files:
        def list(self, **_kwargs):
            return self

        def execute(self):
            return {"files": []}

    class _Service:
        def files(self):
            return _Files()

    google = ModuleType("google")
    google_auth = ModuleType("google.auth")
    transport = ModuleType("google.auth.transport")
    requests_mod = ModuleType("google.auth.transport.requests")
    requests_mod.Request = object
    transport.requests = requests_mod
    google_auth.transport = transport
    google.auth = google_auth
    oauth2 = ModuleType("google.oauth2")
    credentials_mod = ModuleType("google.oauth2.credentials")
    credentials_mod.Credentials = FakeCredentials
    oauth2.credentials = credentials_mod
    google.oauth2 = oauth2
    flow_pkg = ModuleType("google_auth_oauthlib")
    flow_mod = ModuleType("google_auth_oauthlib.flow")
    flow_mod.InstalledAppFlow = FakeFlow
    flow_pkg.flow = flow_mod
    discovery = ModuleType("googleapiclient.discovery")
    discovery.build = lambda *_args, **_kwargs: _Service()
    apiclient = ModuleType("googleapiclient")
    apiclient.discovery = discovery
    for name, module in {
        "google": google,
        "google.auth": google_auth,
        "google.auth.transport": transport,
        "google.auth.transport.requests": requests_mod,
        "google.oauth2": oauth2,
        "google.oauth2.credentials": credentials_mod,
        "google_auth_oauthlib": flow_pkg,
        "google_auth_oauthlib.flow": flow_mod,
        "googleapiclient": apiclient,
        "googleapiclient.discovery": discovery,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    bundled = {"installed": {"client_id": "fixture-client", "client_secret": "fixture-secret"}}
    monkeypatch.setattr(google_calendar, "BUNDLED_CLIENT_CONFIG", bundled)

    def connect_both(token: str):
        holder["token"] = token
        google_drive.connect(home)
        google_calendar.connect(home)

    with act_as(home, user_a):
        connect_both("token-user-a")
    with act_as(home, user_b):
        connect_both("token-user-b")

    def owned(user, name: str) -> str:
        with original_open(owner_root(home, user.user_id) / name, encoding="utf-8") as handle:
            return handle.read()

    def legacy(name: str) -> str:
        with original_open(home / name, encoding="utf-8") as handle:
            return handle.read()

    assert "token-user-a" in owned(user_a, "drive-token.json")
    assert "token-user-a" in owned(user_a, "google-token.json")
    assert "token-user-b" in owned(user_b, "drive-token.json")
    assert "token-user-b" in owned(user_b, "google-token.json")
    assert "token-user-b" not in owned(user_a, "drive-token.json")
    assert "token-user-a" not in owned(user_b, "google-token.json")
    assert shared_reads == []
    assert legacy("drive-token.json") == canary
    assert legacy("google-token.json") == canary

    def read_both():
        google_drive._load_credentials(home)
        google_calendar._load_credentials(home, google_calendar.DEFAULT_SCOPES)
        google_drive.list_files(home)

    with act_as(home, user_a):
        read_both()
    assert loaded == [
        str(owner_root(home, user_a.user_id) / "drive-token.json"),
        str(owner_root(home, user_a.user_id) / "google-token.json"),
        str(owner_root(home, user_a.user_id) / "drive-token.json"),
    ]
    assert shared_reads == []
    loaded.clear()
    with act_as(home, user_b):
        read_both()
    assert all(user_b.user_id in path for path in loaded)
    assert shared_reads == []
    assert canary not in "".join(loaded)

    local_id = database_local_owner(home)
    conn = connect(home)
    workspace_id = conn.execute(
        "SELECT workspace_id FROM identity_local WHERE user_id = ?",
        (local_id,),
    ).fetchone()[0]
    conn.close()
    with act_as(home, Principal(PrincipalKind.USER, local_id, workspace_id)):
        assert google_drive._token_path(home) == home / "drive-token.json"
        assert google_calendar._token_path(home) == home / "google-token.json"
        google_drive._load_credentials(home)
    assert str(home / "drive-token.json") in shared_reads
    assert canary in legacy("drive-token.json")

    shared_reads.clear()
    loaded.clear()

    def post(path: str, payload: dict, issued=None):
        body = json.dumps(payload).encode()
        headers = {"Content-Length": str(len(body)), "Content-Type": "application/json"}
        if issued is not None:
            headers["Cookie"] = f"{SESSION_COOKIE}={issued.session_id}"
            headers["X-CSRF-Token"] = issued.csrf_token
        return _Handler("POST", path, headers, body)

    listed = post("/api/drive", {"op": "list"})
    calendar = post("/api/workspace", {"op": "connect_calendar"})
    assert listed.statuses == [401]
    assert calendar.statuses == [401]
    assert json.loads(listed.body)["error"] == "no authenticated principal"
    assert canary not in listed.body.decode() + calendar.body.decode()
    anonymous = AuthStore(home).evaluate({"Host": "127.0.0.1"}, mutate=False)
    with attached_decision(anonymous):
        with pytest.raises(PermissionError, match="no authenticated principal"):
            google_drive._token_path(home)
        with pytest.raises(PermissionError, match="no authenticated principal"):
            google_calendar._token_path(home)
    assert shared_reads == []
    assert loaded == []


def test_release_postgres_check_rejects_empty_owner():
    dsn = os.environ.get("PU_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip(SKIP_POSTGRES)
    import psycopg

    from pu.persistence.postgres_schema import PRIVATE_TABLES, install

    admin = psycopg.connect(dsn, connect_timeout=3)
    try:
        install(admin, password="pu-phase6-fixture", replace_existing=True)
        names = {
            row[0]
            for row in admin.execute(
                "SELECT conname FROM pg_constraint WHERE conname LIKE %s",
                ("%\\_owner_nonempty",),
            )
        }
        assert names == {f"{table}_owner_nonempty" for table in PRIVATE_TABLES}
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute(
                "INSERT INTO facts(owner_user_id, subject, content) VALUES (%s, %s, %s)",
                ("", "fixture", BETA),
            )
        admin.rollback()
    finally:
        admin.close()

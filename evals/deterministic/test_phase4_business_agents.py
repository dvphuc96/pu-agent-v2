"""Phase 4 gates: business agents stay inside one owner's data.

Fixtures are synthetic users A and B. Nothing here is a real mailbox, token,
attachment, or customer record.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from evals.helpers import admitted_judge_contract
from pu.agents.email import EmailAgent
from pu.agents.isolation import ForeignResource, refuse_before_provider
from pu.agents.scoped import ScopedAgent
from pu.config import Settings
from pu.core.interfaces.llm import LLMResponse, LLMUsage
from pu.core.interfaces.orchestration import ResearchWorkflowRequest
from pu.core.interfaces.tools import ToolResult
from pu.db import connect
from pu.evaluation.report import LLMReportJudge
from pu.harness.gateway import execute_worker_read, read_calendar_ics
from pu.identity.contract import AgentRequestRejected
from pu.identity.directory import provision_user
from pu.identity.files import owner_root
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.session import AuthStore, act_as
from pu.memory import knowledge
from pu.memory.semantic.store import SqliteFactStore
from pu.ops.briefing import BriefingService, job_fingerprint
from pu.ops.dashboard import knowledge_action
from pu.ops.workspace_api import ask_sources, workspace_action
from pu.orchestration.inbox_chat import InboxChatBriefing
from pu.orchestration.research import ResearchWorkflowOrchestrator
from pu.persistence.ownership import scope_briefing_fingerprint
from pu.reporting.attachment_store import read_attachment, store_attachment
from pu.reporting.models import StructuredReport
from pu.reporting.repository import FileReportRepository
from pu.reporting.workspace import WorkspaceRepository, content_hash, now
from pu.runtime.agent import DefaultAgentRuntime
from pu.tools.calendar import make_list_tool
from pu.tools.gmail_research import GmailResearchReader
from pu.tools.memory_search import make_tool as make_memory_tool
from pu.tools.registry import ToolRegistry
from pu.tools.report_delivery import make_tools as make_delivery_tools

COMPANY = "Shared Fixture Co"
TOKEN_KEY = "phase4-key-outside-db-xx"
ACCESS_TOKEN = "ya29.phase4providertokenvalue"
BETA_ATTACHMENT = "betaattachmentsecret"
BETA_EMAIL = "betaemailsecret"
BETA_SOURCE = "betasourcesecret"
BETA_REPORT = "betareportsecret"
BETA_FACT = "betafactsecret"
BETA_KNOWLEDGE = "betaknowledgesecret"
BETA_FOLDER = "betafoldersecret"
BETA_CALENDAR = "betacalendartitle"
BETA_ICS = "betaicsmeeting"
BETA_TOKEN = "betatokenmarker"
BETA_THREAD = "betathreadsecret"
BETA_CONTACT = "beta@fixture-b.example"
ALPHA_CONTACT = "alpha@fixture-a.example"


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
    return home, home, user_a, user_b


def _payload(report_id: str, secret: str) -> dict:
    return {
        "report_id": report_id,
        "workflow_id": "wf-" + report_id,
        "title": COMPANY,
        "executive_summary": secret,
        "sections": {"company": secret},
        "claims": [],
        "sources": [
            {
                "id": "S1",
                "title": "Email",
                "source_type": "email",
                "excerpt": secret,
                "derived": False,
            }
        ],
        "markdown": secret,
        "metadata": {},
    }


class CountingProvider:
    def __init__(self):
        self.requests = []

    def complete(self, request, on_text=None):
        self.requests.append(request)
        return LLMResponse(
            text='{"score":8,"reason":"ok","criteria":{}}',
            usage=LLMUsage(),
        )


class CountingHarness:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments, context):
        self.calls.append(name)
        return ToolResult(output="called", ok=True)


def _judge_report():
    report = StructuredReport(
        report_id="report-judge",
        workflow_id="wf-judge",
        title="Fixture",
        executive_summary="Synthetic summary",
        sections={},
        claims=[],
        sources=[],
    )
    deterministic = SimpleNamespace(
        status_details={},
        metrics=SimpleNamespace(status_details={}),
    )
    return report, deterministic


def test_ae01_other_owner_cannot_read_attachment(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    encoded = base64.b64encode(BETA_ATTACHMENT.encode()).decode()
    with _as(seam, user_b):
        attachment_id = store_attachment(home, "note.txt", encoded)
        workspace = WorkspaceRepository(home).create("Beta Files")
        uploaded = workspace_action(
            home,
            {
                "op": "upload_source",
                "workspace_id": workspace["id"],
                "filename": "note.txt",
                "data": encoded,
            },
        )
        uploaded_id = uploaded["sources"][0]["metadata"]["attachment_id"]
    with _as(seam, user_a):
        with pytest.raises(KeyError) as direct:
            read_attachment(home, attachment_id)
        with pytest.raises(KeyError) as downloaded:
            workspace_action(home, {"op": "download_attachment", "attachment_id": uploaded_id})
        assert BETA_ATTACHMENT not in str(direct.value)
        assert BETA_ATTACHMENT not in str(downloaded.value)
        owned = owner_root(home, user_a.user_id) / "attachments"
        leaked = b""
        if owned.is_dir():
            leaked = b"".join(path.read_bytes() for path in owned.rglob("*") if path.is_file())
        assert BETA_ATTACHMENT.encode() not in leaked


def test_ae02_same_company_name_does_not_merge_workspaces(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    repo = WorkspaceRepository(home)
    with _as(seam, user_a):
        alpha = repo.ensure_company(COMPANY, "https://fixture-a.example", ALPHA_CONTACT)
        repo.add_source(alpha["id"], title="Alpha mail", content="alphaemailsecret", source_type="email")
        repo.attach_report(alpha["id"], _payload("report-alpha", "alphareportsecret"))
    with _as(seam, user_b):
        beta = repo.ensure_company(COMPANY, "https://fixture-b.example", BETA_CONTACT)
        repo.add_source(beta["id"], title="Beta mail", content=BETA_SOURCE, source_type="email")
        repo.attach_report(beta["id"], _payload("report-beta", BETA_REPORT))
    assert alpha["id"] != beta["id"]
    with _as(seam, user_a):
        detail = json.dumps(repo.detail(alpha["id"]))
    assert BETA_CONTACT not in detail
    assert BETA_SOURCE not in detail
    assert BETA_REPORT not in detail
    assert "alphaemailsecret" in detail


def test_ae03_google_error_and_other_calendar_stay_unavailable(tmp_path, monkeypatch):
    home, seam, user_a, user_b = _open(tmp_path)
    calls = []

    def google_events(home_path, start, end, limit):
        calls.append(home_path)
        return "betagoogleevent"

    monkeypatch.setattr("pu.tools.google_calendar.list_google_events", google_events)
    legacy = home / "google-token.json"
    legacy.write_text(BETA_TOKEN, encoding="utf-8")
    legacy.with_name("google-token.json.owner").write_text(user_b.user_id, encoding="utf-8")
    owned_token = owner_root(home, user_b.user_id) / "google-token.json"
    owned_token.parent.mkdir(parents=True)
    owned_token.write_text(BETA_TOKEN, encoding="utf-8")
    today = datetime.now().strftime("%Y%m%d")
    ics = owner_root(home, user_b.user_id) / "calendar.ics"
    ics.write_text(
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
        f"SUMMARY:{BETA_ICS}\nDTSTART:{today}T090000\n"
        "END:VEVENT\nEND:VCALENDAR\n",
        encoding="utf-8",
    )
    with _as(seam, user_b):
        conn = connect(home)
        conn.execute(
            'INSERT INTO calendar_events(title, start, "end") VALUES(?,?,?)',
            (BETA_CALENDAR, "2026-10-22T09:00", "2026-10-22T10:00"),
        )
        conn.commit()
        conn.close()
    with _as(seam, user_a):
        conn = connect(home)
        result = make_list_tool(conn, home).fn()
        conn.close()
        calendar = read_calendar_ics(home)
    assert calls == []
    assert BETA_CALENDAR not in result
    assert BETA_TOKEN not in result
    assert "betagoogleevent" not in result
    assert calendar == "(no calendar)"
    assert BETA_ICS not in calendar


def test_ae04_memory_and_knowledge_stay_with_their_owner(tmp_path, monkeypatch):
    home, seam, user_a, user_b = _open(tmp_path)
    with _as(seam, user_b):
        conn = connect(home)
        SqliteFactStore(conn).add("beta", BETA_FACT)
        knowledge.add_source(conn, "Beta playbook", BETA_KNOWLEDGE)
        conn.close()
    shared = home / "knowledge"
    shared.mkdir()
    (shared / "b.md").write_text(BETA_FOLDER, encoding="utf-8")
    with _as(seam, user_a):
        conn = connect(home)
        from pu.memory import Memory

        memory = Memory(conn, Settings(home=home), CountingProvider())
        found = make_memory_tool(memory).fn(query=BETA_FACT)
        chunks = knowledge.search(conn, BETA_KNOWLEDGE)
        conn.close()
        monkeypatch.setattr(
            "pu.ops.dashboard.load_settings",
            lambda: Settings(home=home),
        )
        knowledge_action({"op": "reindex"})
        conn = connect(home)
        folder_hits = knowledge.search(conn, BETA_FOLDER)
        conn.close()
    assert BETA_FACT not in found
    assert chunks == []
    assert folder_hits == []


def test_ae05_same_request_creates_two_reports_and_two_jobs(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    repo = WorkspaceRepository(home)
    with _as(seam, user_a):
        alpha = repo.ensure_company(COMPANY, "https://fixture-a.example", ALPHA_CONTACT)
        repo.add_source(alpha["id"], title="Alpha", content="alphaemailbody", source_type="email")
        stored_a = repo.attach_report(alpha["id"], _payload("report-alpha-job", "alphabodysecret"))
    with _as(seam, user_b):
        beta = repo.ensure_company(COMPANY, "https://fixture-b.example", BETA_CONTACT)
        repo.add_source(beta["id"], title="Beta", content=BETA_EMAIL, source_type="email")
        stored_b = repo.attach_report(beta["id"], _payload("report-beta-job", BETA_EMAIL))
    assert stored_a["content_hash"] != stored_b["content_hash"]
    assert stored_a["content_hash"] == content_hash(stored_a["payload"])
    assert {stored_a["payload"]["report_id"], stored_b["payload"]["report_id"]} == {
        "report-alpha-job",
        "report-beta-job",
    }
    with _as(seam, user_a):
        assert BETA_EMAIL not in json.dumps(repo.detail(alpha["id"]))
    same_ids = ["fixture-message-1"]
    assert job_fingerprint(user_a.user_id, same_ids) != job_fingerprint(user_b.user_id, same_ids)
    fingerprint = "shared-briefing-fingerprint"
    stamp = now()
    with _as(seam, user_a):
        conn = connect(home)
        conn.execute(
            """INSERT INTO briefing_jobs(
                   id, fingerprint, workspace_id, email_ids_json, created_at, updated_at
               ) VALUES(?,?,?,?,?,?)""",
            ("brief-a", fingerprint, alpha["id"], "[]", stamp, stamp),
        )
        conn.commit()
        conn.close()
    with _as(seam, user_b):
        conn = connect(home)
        conn.execute(
            """INSERT INTO briefing_jobs(
                   id, fingerprint, workspace_id, email_ids_json, created_at, updated_at
               ) VALUES(?,?,?,?,?,?)""",
            ("brief-b", fingerprint, beta["id"], "[]", stamp, stamp),
        )
        conn.commit()
        conn.close()
    raw = sqlite3.connect(home / "state.db")
    count = raw.execute(
        "SELECT COUNT(*) FROM briefing_jobs WHERE fingerprint=?",
        (fingerprint,),
    ).fetchone()[0]
    raw.close()
    assert count == 2


def test_ae05_rebuilds_a_global_briefing_fingerprint(tmp_path):
    home, _seam, _user_a, _user_b = _open(tmp_path)
    conn = connect(home)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DROP INDEX IF EXISTS idx_briefing_jobs_status")
    conn.execute("ALTER TABLE briefing_jobs RENAME TO briefing_jobs_oldunique")
    conn.execute(
        """CREATE TABLE briefing_jobs (
            id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            workspace_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT NOT NULL DEFAULT 'queued',
            workflow_id TEXT,
            report_id TEXT,
            email_ids_json TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(workspace_id, owner_user_id)
                REFERENCES research_workspaces(id, owner_user_id)
        )"""
    )
    conn.execute("INSERT INTO briefing_jobs SELECT * FROM briefing_jobs_oldunique")
    conn.execute("DROP TABLE briefing_jobs_oldunique")
    scope_briefing_fingerprint(conn)
    conn.commit()
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='briefing_jobs'"
    ).fetchone()[0]
    conn.close()
    assert "unique(fingerprint,owner_user_id)" in "".join(sql.split()).lower()


def test_ae06_refuses_foreign_ids_before_provider(tmp_path, monkeypatch):
    home, seam, user_a, user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    repo = WorkspaceRepository(home)
    with _as(seam, user_b):
        workspace = repo.ensure_company(COMPANY, "https://fixture-b.example", BETA_CONTACT)
        stored = repo.attach_report(workspace["id"], _payload("report-beta-gate", BETA_REPORT))
        conn = connect(home)
        conn.execute(
            """INSERT INTO crm_emails(gmail_id, thread_id, subject, body_text, internal_date)
               VALUES(?,?,?,?,?)""",
            ("gm-b", "threadB", "Beta", BETA_THREAD, "2026-10-22T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()
    connection_id = AuthStore(home).save_oauth_token(
        owner_user_id=user_b.user_id,
        provider="gmail",
        token={"access_token": ACCESS_TOKEN},
    )
    provider = CountingProvider()
    harness = CountingHarness()

    class Service:
        def __init__(self):
            self.calls = []

        def users(self):
            self.calls.append("users")
            return self

        def threads(self):
            return self

        def get(self, **kwargs):
            self.calls.append(kwargs)
            return self

        def execute(self):
            self.calls.append("execute")
            return {"messages": []}

    with _as(seam, user_a):
        conn = connect(home)
        reader = GmailResearchReader(conn, home)
        service = Service()
        reader.service = lambda: service
        with pytest.raises(ForeignResource) as thread_error:
            reader.thread("threadB")
        conn.close()
        assert thread_error.value.code == "thread_denied"
        assert service.calls == []
        assert BETA_THREAD not in str(thread_error.value)

        for field, value, code in (
            ("thread_id", "threadB", "thread_denied"),
            ("report_id", "report-beta-gate", "report_denied"),
            ("workspace_id", workspace["id"], "workspace_denied"),
            ("connection_id", connection_id, "connection_denied"),
        ):
            result = execute_worker_read(
                harness,
                "read_foreign",
                {field: value},
                owner_user_id=user_a.user_id,
                home=home,
            )
            assert result.ok is False
            assert result.error == code
            assert BETA_THREAD not in result.output
            assert ACCESS_TOKEN not in result.output
            assert harness.calls == []

        with pytest.raises(KeyError):
            ask_sources(
                repo,
                workspace["id"],
                "What did they write?",
                [{"id": "s", "title": "t", "url": "", "content": "c"}],
                SimpleNamespace(
                    llm_provider=provider,
                    settings=SimpleNamespace(model="m"),
                    event_publisher=SimpleNamespace(publish=lambda *args: None),
                ),
            )
        assert provider.requests == []

        agent = EmailAgent(
            DefaultAgentRuntime(provider, harness),
            ToolRegistry(),
            model="m",
        )
        for key, value in (
            ("thread_id", "threadB"),
            ("report_id", "report-beta-gate"),
            ("workspace_id", workspace["id"]),
            ("connection_id", connection_id),
        ):
            with pytest.raises(ForeignResource):
                agent.respond("research this", metadata={"home": home, key: value})
        assert provider.requests == []

        delivery = {tool.name: tool for tool in make_delivery_tools(home)}
        with pytest.raises(ForeignResource) as delivery_error:
            delivery["forward_report_email"].fn(
                workspace["id"],
                stored["payload"]["report_id"],
                "a" * 64,
                "a@fixture-a.example",
                "Report",
            )
        assert delivery_error.value.code == "report_denied"
        assert BETA_REPORT not in str(delivery_error.value)

        calls = []

        class Boom:
            def respond(self, *args, **kwargs):
                calls.append("model")
                raise AssertionError("model")

        boom = Boom()
        orchestrator = ResearchWorkflowOrchestrator(
            email=boom,
            company=boom,
            web=boom,
            calendar=boom,
            memory=boom,
            report=boom,
            report_builder=object(),
            evaluation_harness=object(),
            report_repository=FileReportRepository(home),
        )
        with pytest.raises(ForeignResource) as research_error:
            orchestrator.run(
                ResearchWorkflowRequest(
                    workspace_id=workspace["id"],
                    owner_user_id=user_a.user_id,
                )
            )
        assert research_error.value.code == "workspace_denied"
        assert calls == []

        app = SimpleNamespace(
            conn=connect(home),
            llm_provider=provider,
            settings=SimpleNamespace(home=home, small_model="m", model="m"),
        )
        with pytest.raises(ForeignResource):
            InboxChatBriefing(app).classify(
                [{"emails": [{"thread_id": "threadB", "gmail_id": "gm-b"}]}],
                lambda *args: None,
            )
        assert provider.requests == []

        triage = BriefingService(home)
        with pytest.raises(ForeignResource):
            triage._triage_batch(
                [{"gmail_id": "gm-b", "thread_id": "threadB"}],
                app,
            )
        app.conn.close()
        assert provider.requests == []


def test_provider_paths_admit_before_the_model(tmp_path, monkeypatch):
    home, seam, user_a, _user_b = _open(tmp_path)
    provider = CountingProvider()
    report, deterministic = _judge_report()
    judge = LLMReportJudge(provider, "offline")
    score = judge.evaluate(
        report,
        deterministic_result=deterministic,
        contract=admitted_judge_contract(),
    )
    assert score is not None
    assert len(provider.requests) == 1

    closed = CountingProvider()
    with pytest.raises(AgentRequestRejected):
        LLMReportJudge(closed, "offline").evaluate(
            report, deterministic_result=deterministic
        )
    assert closed.requests == []

    admin = Principal(PrincipalKind.PLATFORM_ADMIN, user_a.user_id, user_a.workspace_id)
    blocked = CountingProvider()
    with _as(seam, admin), pytest.raises(AgentRequestRejected):
        LLMReportJudge(blocked, "offline").evaluate(
            report, deterministic_result=deterministic
        )
    assert blocked.requests == []

    class Denied:
        def complete(self, request, on_text=None):
            raise PermissionError("denied")

    with pytest.raises(PermissionError, match="denied"):
        LLMReportJudge(Denied(), "offline").evaluate(
            report,
            deterministic_result=deterministic,
            contract=admitted_judge_contract(),
        )

    seen = []

    def gate(*args, **kwargs):
        seen.append("gate")
        return False, "", ""

    monkeypatch.setattr("pu.memory.retrieval_gate.should_retrieve", gate)
    from pu.memory import Memory

    with _as(seam, admin):
        conn = connect(home)
        memory = Memory(conn, Settings(home=home), CountingProvider())
        with pytest.raises(PermissionError):
            memory.gated_retrieve("hello")
        conn.close()
    assert seen == []

    missing = CountingProvider()
    with pytest.raises(AgentRequestRejected):
        BriefingService(home)._triage_batch(
            [{"gmail_id": "x"}],
            SimpleNamespace(llm_provider=missing, conn=None),
        )
    assert missing.requests == []


def test_scoped_agent_without_ids_still_reaches_runtime():
    """A turn that names no foreign id is unchanged by the metadata check."""
    provider_calls = []

    class Runtime:
        def run(self, request, observer=None):
            provider_calls.append(request.messages[0]["content"])
            from pu.core.interfaces.agents import AgentResult

            return AgentResult(reply="ok")

    agent = ScopedAgent(Runtime(), ToolRegistry(), model="m")
    result = agent.respond("hello", metadata={"source": "unit"})
    assert result.reply == "ok"
    assert provider_calls == ["hello"]


def test_research_workflow_admits_the_judge_and_refuses_without_principal(
    tmp_path, monkeypatch
):
    """The production research path admits the workflow owner before the judge.

    The session principal stays unset. The same judge refuses, with zero
    provider calls, when that contract is missing.
    """
    from evals.deterministic.test_phase8_report_evaluation import (
        JudgeProvider,
        Phase8Runtime,
    )
    from pu.core.container import create_application
    from pu.evaluation.report import admit as real_admit
    from pu.identity.directory import current_principal
    from pu.identity.session import session_principal

    provider = JudgeProvider()
    order: list[tuple[str, str]] = []
    original = provider.complete

    def wrapped(request, on_text=None):
        order.append(("provider", request.model))
        return original(request, on_text)

    provider.complete = wrapped

    def spy(request):
        assert session_principal() is None
        order.append(("admit", request.owner_user_id))
        return real_admit(request)

    monkeypatch.setattr("pu.evaluation.report.admit", spy)
    app = create_application(
        settings=Settings(
            home=tmp_path,
            api_key="offline",
            gmail=False,
            graph_workflows=False,
            model="",
            report_judge_model="judge-fixture",
            report_judge_enabled=True,
        ),
        llm_provider=provider,
        agent_runtime=Phase8Runtime(),
    )
    result = app.run_research_workflow("Prepare Acme")
    owner = current_principal(app.conn).user_id
    admits = [item for item in order if item[0] == "admit"]
    providers = [item for item in order if item[0] == "provider"]
    assert admits and admits[0][1] == owner
    assert providers and providers[0][1] == "judge-fixture"
    assert order.index(admits[0]) < order.index(providers[0])
    assert result.evaluation.judge is not None
    assert result.evaluation.judge.score == 8.5

    blocked = CountingProvider()
    with pytest.raises(AgentRequestRejected):
        LLMReportJudge(blocked, "offline").evaluate(result.structured_report)
    assert blocked.requests == []

    harness_provider = CountingProvider()
    app.evaluation_harness.judge = LLMReportJudge(harness_provider, "offline")
    with pytest.raises(AgentRequestRejected):
        app.evaluation_harness.evaluate(result.structured_report, run_judge=True)
    assert harness_provider.requests == []


def test_unknown_id_and_database_error_are_refusals(tmp_path):
    home, _seam, user_a, _user_b = _open(tmp_path)
    conn = connect(home)
    try:
        conn.execute(
            """INSERT INTO crm_emails(
                   gmail_id, thread_id, subject, internal_date, owner_user_id
               ) VALUES(?,?,?,?,?)""",
            (
                "seed-owned",
                "thread-owned",
                "Seed",
                "2026-10-22T00:00:00+00:00",
                user_a.user_id,
            ),
        )
        conn.commit()
        with pytest.raises(ForeignResource) as unknown:
            refuse_before_provider(
                conn, thread_id="thread-missing", owner=user_a.user_id
            )
        assert unknown.value.code == "thread_denied"
        refuse_before_provider(conn, thread_id="thread-owned", owner=user_a.user_id)
    finally:
        conn.close()

    class Broken:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("fixture")

    with pytest.raises(ForeignResource) as broken:
        refuse_before_provider(
            Broken(), thread_id="thread-owned", owner=user_a.user_id
        )
    assert broken.value.code == "thread_denied"


def test_hidden_postgres_row_is_refused_before_provider():
    """A foreign id hidden by pu_app row level security is a refusal.

    The role cannot see the other owner's row, so the lookup returns nothing.
    That absence is a denial, and the caller's own row is still allowed.
    """
    dsn = os.environ.get("PU_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("PostgreSQL unavailable: set PU_POSTGRES_DSN")
    try:
        import psycopg
        from psycopg import conninfo
    except ImportError as exc:
        pytest.skip(f"PostgreSQL unavailable ({exc})")
    try:
        admin = psycopg.connect(dsn, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL unavailable ({exc})")
    app = None
    try:
        from pu.persistence.postgres_schema import install, set_owner

        install(admin, password="pu-phase1-fixture", replace_existing=True)
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        rows = (
            (user_a, "ws-fixture-a", "report-fixture-a"),
            (user_b, "ws-fixture-b", "report-fixture-b"),
        )
        for user, workspace, report in rows:
            admin.execute("INSERT INTO users(id) VALUES (%s)", (user,))
            admin.execute(
                """INSERT INTO research_workspaces(id, owner_user_id, company)
                   VALUES (%s, %s, %s)""",
                (workspace, user, "fixture"),
            )
            admin.execute(
                """INSERT INTO workspace_reports(report_id, workspace_id, owner_user_id)
                   VALUES (%s, %s, %s)""",
                (report, workspace, user),
            )
        admin.commit()
        params = conninfo.conninfo_to_dict(dsn)
        host = params.get("host") or "127.0.0.1"
        if str(host).startswith("/"):
            host = "127.0.0.1"
        app = psycopg.connect(
            host=host,
            port=params.get("port") or 5432,
            dbname=params.get("dbname") or admin.info.dbname,
            user="pu_app",
            password="pu-phase1-fixture",
            connect_timeout=3,
        )
        with app.transaction():
            set_owner(app, user_a)
            with pytest.raises(ForeignResource) as hidden_workspace:
                refuse_before_provider(app, workspace_id="ws-fixture-b", owner=user_a)
            assert hidden_workspace.value.code == "workspace_denied"
            with pytest.raises(ForeignResource) as hidden_report:
                refuse_before_provider(app, report_id="report-fixture-b", owner=user_a)
            assert hidden_report.value.code == "report_denied"
            with pytest.raises(ForeignResource) as missing:
                refuse_before_provider(app, workspace_id="ws-not-stored", owner=user_a)
            assert missing.value.code == "workspace_denied"
            refuse_before_provider(app, workspace_id="ws-fixture-a", owner=user_a)
            refuse_before_provider(app, report_id="report-fixture-a", owner=user_a)
    finally:
        admin.close()
        if app is not None:
            app.close()

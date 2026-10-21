"""Phase 1 gates: identity, ownership, and PostgreSQL row level security.

Fixtures are synthetic users A and B. Nothing here is a real mailbox, token,
or customer record. MU-11 covers IDOR only; CSRF stays a Phase 2 gate.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager

import pytest

from pu.core.interfaces.orchestration import ResearchWorkflowRequest
from pu.db import connect
from pu.identity.directory import provision_user, workspace_count
from pu.identity.files import OwnershipDenied
from pu.identity.legacy_import import LegacyImportRejected, import_legacy_rows
from pu.identity.principal import Principal
from pu.identity.seam import InternalPrincipalSeam
from pu.ops.workspace_api import export_workspace_artifact, workspace_action, workspace_list
from pu.persistence import SQLiteDatabase, SQLiteWorkflowRepository
from pu.persistence.ownership import OWNED_TABLES
from pu.persistence.postgres_schema import MARKER_COLUMN, PRIVATE_TABLES, install, set_owner
from pu.reporting.models import StructuredReport
from pu.reporting.repository import FileReportRepository
from pu.reporting.workspace import WorkspaceRepository

A_MARK = "fixture-a-marker"
B_MARK = "fixture-b-marker"
BETA_REPORT = "beta-secret-report"
BETA_WORKFLOW = "beta-secret-workflow"
BETA_ARTIFACT = "beta-secret-artifact"
BETA_SOURCE = "beta-secret-source"
ALPHA_SOURCE = "alpha-written-source"
LEGACY_FACT = "legacy-fact-body"
SKIP_POSTGRES = "PostgreSQL unavailable: set PU_POSTGRES_DSN to run MU-07"


@contextmanager
def _as(seam: InternalPrincipalSeam, principal: Principal):
    token = seam.attach(principal)
    try:
        yield
    finally:
        seam.detach(token)


def _open(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    user_a = provision_user(conn)
    user_b = provision_user(conn)
    conn.commit()
    return home, conn, InternalPrincipalSeam(), user_a, user_b


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


def test_backend_issues_one_personal_workspace_and_seam_ignores_body(tmp_path):
    home, conn, seam, user_a, _user_b = _open(tmp_path)
    assert list(inspect.signature(provision_user).parameters) == ["conn"]
    assert list(inspect.signature(InternalPrincipalSeam.attach).parameters) == ["self", "principal"]
    assert str(uuid.UUID(user_a.user_id)) == user_a.user_id
    assert str(uuid.UUID(user_a.workspace_id)) == user_a.workspace_id
    assert workspace_count(conn, user_a.user_id) == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO personal_workspaces(id, owner_user_id, created_at) VALUES (?, ?, ?)",
            (str(uuid.uuid4()), user_a.user_id, "t"),
        )
    conn.rollback()
    with pytest.raises(TypeError):
        seam.attach({"owner_user_id": user_a.user_id, "workspace_id": user_a.workspace_id})
    from evals.helpers import ScriptedProvider, make_pu
    from pu.core.container import build_dependencies

    app = make_pu(home / "app", ScriptedProvider([]))
    try:
        assert isinstance(app.principal_seam, InternalPrincipalSeam)
        assert app.principal_seam is app.dependencies.principal_seam
        built = build_dependencies(settings=app.settings, llm_provider=ScriptedProvider([]))
        assert isinstance(built.principal_seam, InternalPrincipalSeam)
    finally:
        app.close()
    conn.close()


def test_mu01_rejects_other_users_report_and_workflow(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    conn.close()
    with _as(seam, user_b):
        repo = WorkspaceRepository(home)
        workspace = repo.create("Beta Fixture", "https://beta.example")
        repo.attach_report(workspace["id"], _report_payload("report-betasecret", BETA_REPORT))
        workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
        workflows.create("wf-beta", ResearchWorkflowRequest(prompt=BETA_WORKFLOW))
    with _as(seam, user_a):
        with pytest.raises(KeyError) as report_error:
            WorkspaceRepository(home).require_report(workspace["id"], "report-betasecret")
        assert BETA_REPORT not in str(report_error.value)
        assert workflows.get("wf-beta") is None
        with pytest.raises(KeyError) as workflow_error:
            workflows.request("wf-beta")
        assert BETA_WORKFLOW not in str(workflow_error.value)


def test_mu02_rejects_other_users_artifact_bytes(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    conn.close()
    report = StructuredReport(
        report_id="report-betaartifact",
        workflow_id="wf-beta",
        title="Fixture",
        executive_summary=BETA_ARTIFACT,
        sections={"company": BETA_ARTIFACT},
        claims=[],
        sources=[],
        markdown=BETA_ARTIFACT,
    )
    with _as(seam, user_b):
        FileReportRepository(home).save(report)
    with _as(seam, user_a):
        with pytest.raises(OwnershipDenied) as denied:
            FileReportRepository(home).read_bytes("report-betaartifact", "md")
        assert BETA_ARTIFACT not in str(denied.value)


def test_sqlite_owner_column_and_composite_fk(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    for table in OWNED_TABLES:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert "owner_user_id" in columns
    facts_fts = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'facts_fts'"
    ).fetchone()[0]
    assert "owner_user_id" in facts_fts
    foreign_keys = conn.execute("PRAGMA foreign_key_list(workflow_stage_checkpoints)").fetchall()
    assert any(row[2] == "workflow_runs" and row[3] == "workflow_id" for row in foreign_keys)
    assert any(row[3] == "owner_user_id" for row in foreign_keys)
    with _as(seam, user_a):
        conn.execute(
            """INSERT INTO workflow_runs(
                   id, workflow_type, status, request_json, created_at, updated_at
               ) VALUES (?, 'morning_research', 'running', '{}', 't', 't')""",
            ("wf-owner-a",),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO workflow_stage_checkpoints(
                       workflow_id, stage_name, status, updated_at, owner_user_id
                   ) VALUES ('wf-owner-a', 'collect', 'completed', 't', ?)""",
                (user_b.user_id,),
            )
    conn.rollback()
    conn.close()
    assert home.is_dir()


def test_mu10_legacy_import_requires_explicit_mapping(tmp_path):
    _home, conn, seam, user_a, user_b = _open(tmp_path)
    mapped = {
        "table": "facts",
        "legacy_owner": "local-user",
        "values": {"subject": "fixture", "content": LEGACY_FACT},
    }
    with pytest.raises(LegacyImportRejected):
        import_legacy_rows(conn, None, [mapped])
    assert _fact_count(conn, LEGACY_FACT) == 0

    written = import_legacy_rows(conn, {"local-user": user_a.user_id}, [mapped])
    assert written == 1
    with _as(seam, user_b):
        visible = conn.execute(
            "SELECT content FROM facts WHERE owner_user_id = pu_current_owner()"
        ).fetchall()
    assert LEGACY_FACT not in [row[0] for row in visible]
    with _as(seam, user_a):
        visible = conn.execute(
            "SELECT content FROM facts WHERE owner_user_id = pu_current_owner()"
        ).fetchall()
    assert LEGACY_FACT in [row[0] for row in visible]

    batch = [
        mapped | {"values": {"subject": "fixture", "content": "batch-kept"}},
        {
            "table": "facts",
            "legacy_owner": "unknown-legacy",
            "values": {"subject": "fixture", "content": "batch-dropped"},
        },
    ]
    with pytest.raises(LegacyImportRejected):
        import_legacy_rows(conn, {"local-user": user_a.user_id}, batch)
    assert _fact_count(conn, "batch-kept") == 0
    assert _fact_count(conn, "batch-dropped") == 0
    conn.close()


def test_mu11_idor_url_and_body_do_not_return_other_user(tmp_path):
    home, conn, seam, _user_a, user_b = _open(tmp_path)
    conn.close()
    with _as(seam, user_b):
        repo = WorkspaceRepository(home)
        workspace = repo.create("Beta Fixture", "https://beta.example")
        repo.attach_report(workspace["id"], _report_payload("report-betasecret", BETA_REPORT))
        workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
        workflows.create("wf-beta", ResearchWorkflowRequest(prompt=BETA_WORKFLOW))
    with _as(seam, _user_a):
        listed = workspace_list(home, workspace["id"], "report-betasecret")
        encoded = json.dumps(listed)
        assert BETA_REPORT not in encoded
        assert listed["workspace"]["company"] == "Personal"
        with pytest.raises(KeyError) as export_error:
            export_workspace_artifact(home, workspace["id"], "report-betasecret", "md")
        assert BETA_REPORT not in str(export_error.value)
        detail = workspace_action(
            home,
            {
                "op": "detail",
                "workspace_id": workspace["id"],
                "report_id": "report-betasecret",
                "owner_user_id": user_b.user_id,
            },
        )
        assert BETA_REPORT not in json.dumps(detail)
        with pytest.raises(KeyError) as workflow_error:
            workflows.request("wf-beta")
        assert BETA_WORKFLOW not in str(workflow_error.value)


def test_mu12_client_owner_and_workspace_follow_principal(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    conn.close()
    with _as(seam, user_b):
        repo = WorkspaceRepository(home)
        workspace = repo.create("Beta Fixture", "https://beta.example")
        repo.add_source(workspace["id"], title="Beta", content=BETA_SOURCE)
    with _as(seam, user_a):
        detail = workspace_action(
            home,
            {
                "op": "add_source",
                "workspace_id": workspace["id"],
                "owner_user_id": user_b.user_id,
                "owner": user_b.user_id,
                "user_id": user_b.user_id,
                "title": "Alpha",
                "content": ALPHA_SOURCE,
            },
        )
        assert detail["workspace"]["id"] == user_a.workspace_id
        assert detail["workspace"]["owner_user_id"] == user_a.user_id
        assert any(source["content"] == ALPHA_SOURCE for source in detail["sources"])
        assert BETA_SOURCE not in json.dumps(detail)
    with _as(seam, user_b):
        sources = WorkspaceRepository(home).sources(workspace["id"])
    assert [source["content"] for source in sources] == [BETA_SOURCE]
    owner = connect(home).execute(
        "SELECT owner_user_id FROM workspace_sources WHERE content = ?",
        (ALPHA_SOURCE,),
    ).fetchone()
    assert owner[0] == user_a.user_id


def _fact_count(conn, content: str) -> int:
    row = conn.execute("SELECT COUNT(*) FROM facts WHERE content = ?", (content,)).fetchone()
    return int(row[0])


def _postgres_dsn() -> str:
    dsn = os.environ.get("PU_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip(SKIP_POSTGRES)
    return dsn


def _seed_postgres(admin, owner: str, workspace_id: str, marker: str) -> None:
    admin.execute("INSERT INTO users(id) VALUES (%s)", (owner,))
    admin.execute(
        "INSERT INTO personal_workspaces(id, owner_user_id) VALUES (%s, %s)",
        (marker, owner),
    )
    admin.execute(
        "INSERT INTO private_files(relative_path, owner_user_id) VALUES (%s, %s)",
        (marker, owner),
    )
    admin.execute(
        "INSERT INTO workflow_runs(id, owner_user_id) VALUES (%s, %s)",
        (marker, owner),
    )
    admin.execute(
        """INSERT INTO workflow_stage_checkpoints(workflow_id, owner_user_id, stage_name)
           VALUES (%s, %s, %s)""",
        (marker, owner, marker),
    )
    admin.execute(
        "INSERT INTO agent_events(id, owner_user_id, workflow_id) VALUES (%s, %s, %s)",
        (marker, owner, marker),
    )
    admin.execute(
        """INSERT INTO tool_audit_events(execution_id, owner_user_id, workflow_id)
           VALUES (%s, %s, %s)""",
        (marker, owner, marker),
    )
    admin.execute(
        "INSERT INTO research_workspaces(id, owner_user_id, company) VALUES (%s, %s, %s)",
        (workspace_id, owner, marker),
    )
    admin.execute(
        """INSERT INTO workspace_sources(id, workspace_id, owner_user_id, content)
           VALUES (%s, %s, %s, %s)""",
        (marker, workspace_id, owner, marker),
    )
    admin.execute(
        """INSERT INTO workspace_reports(report_id, workspace_id, owner_user_id)
           VALUES (%s, %s, %s)""",
        (marker, workspace_id, owner),
    )
    admin.execute(
        """INSERT INTO workspace_messages(id, workspace_id, owner_user_id, answer)
           VALUES (%s, %s, %s, %s)""",
        (marker, workspace_id, owner, marker),
    )
    admin.execute(
        """INSERT INTO workspace_deliveries(
               action_hash, workspace_id, owner_user_id, report_id, destination
           ) VALUES (%s, %s, %s, %s, %s)""",
        (marker, workspace_id, owner, marker, marker),
    )
    source_id = admin.execute(
        "INSERT INTO knowledge_sources(owner_user_id, title) VALUES (%s, %s) RETURNING id",
        (owner, marker),
    ).fetchone()[0]
    admin.execute(
        """INSERT INTO knowledge_chunks(source_id, owner_user_id, content)
           VALUES (%s, %s, %s)""",
        (source_id, owner, marker),
    )
    admin.execute(
        "INSERT INTO knowledge_fts(owner_user_id, content) VALUES (%s, %s)",
        (owner, marker),
    )
    admin.execute(
        "INSERT INTO facts(owner_user_id, subject, content) VALUES (%s, %s, %s)",
        (owner, "fixture", marker),
    )
    admin.execute(
        "INSERT INTO facts_fts(owner_user_id, subject, content) VALUES (%s, %s, %s)",
        (owner, "fixture", marker),
    )
    admin.execute(
        "INSERT INTO episodes(owner_user_id, summary) VALUES (%s, %s)",
        (owner, marker),
    )
    admin.execute(
        "INSERT INTO episodes_fts(owner_user_id, summary) VALUES (%s, %s)",
        (owner, marker),
    )
    admin.execute(
        "INSERT INTO chat_log(owner_user_id, content) VALUES (%s, %s)",
        (owner, marker),
    )
    admin.execute(
        "INSERT INTO crm_emails(gmail_id, owner_user_id, subject) VALUES (%s, %s, %s)",
        (marker, owner, marker),
    )
    admin.execute(
        "INSERT INTO calendar_events(owner_user_id, title) VALUES (%s, %s)",
        (owner, marker),
    )
    admin.execute(
        "INSERT INTO proposed_actions(id, owner_user_id, workflow_id) VALUES (%s, %s, %s)",
        (marker, owner, marker),
    )
    admin.execute(
        "INSERT INTO briefing_state(key, owner_user_id, value) VALUES (%s, %s, %s)",
        ("fixture", owner, marker),
    )
    admin.execute(
        "INSERT INTO briefing_seen(gmail_id, owner_user_id, reason) VALUES (%s, %s, %s)",
        (marker, owner, marker),
    )
    admin.execute(
        "INSERT INTO briefing_jobs(id, workspace_id, owner_user_id) VALUES (%s, %s, %s)",
        (marker, workspace_id, owner),
    )


def test_mu07_rls_hides_other_owner_and_role_cannot_bypass():
    dsn = _postgres_dsn()
    try:
        import psycopg
        from psycopg import conninfo, errors
    except ImportError as exc:
        pytest.skip(f"{SKIP_POSTGRES} ({exc})")
    try:
        admin = psycopg.connect(dsn, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"{SKIP_POSTGRES} ({exc})")
    app = None
    try:
        install(admin)
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        _seed_postgres(admin, user_a, "fixture-a-ws", A_MARK)
        _seed_postgres(admin, user_b, "fixture-b-ws", B_MARK)
        admin.commit()
        with pytest.raises(errors.ForeignKeyViolation):
            admin.execute(
                """INSERT INTO workflow_stage_checkpoints(
                       workflow_id, owner_user_id, stage_name
                   ) VALUES (%s, %s, 'mismatch')""",
                (A_MARK, user_b),
            )
        admin.rollback()
        role = admin.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'pu_app'"
        ).fetchone()
        assert role == (False, False)
        flags = admin.execute(
            """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
               FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'pu_phase1' AND c.relkind = 'r'
                 AND c.relname = ANY(%s)""",
            (list(PRIVATE_TABLES),),
        ).fetchall()
        assert {name for name, _rls, _force in flags} == set(PRIVATE_TABLES)
        assert all(enabled and forced for _name, enabled, forced in flags)
        admin.commit()
        params = conninfo.conninfo_to_dict(dsn)
        host = params.get("host") or "127.0.0.1"
        if host.startswith("/"):
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
            for table, column in MARKER_COLUMN.items():
                seen = [row[0] for row in app.execute(f"SELECT {column} FROM {table}")]
                assert seen == [A_MARK], table
            with pytest.raises(errors.InsufficientPrivilege):
                app.execute(
                    "INSERT INTO facts(owner_user_id, subject, content) VALUES (%s, %s, %s)",
                    (user_b, "fixture", B_MARK),
                )
    finally:
        admin.close()
        if app is not None:
            app.close()

"""Phase 1 review fixes: crash-safe ownership migration and owner filters.

Fixtures are synthetic users A and B. Nothing here is a mailbox, token, or
customer record.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pu.approval.models import ApprovalStatus, ProposedAction
from pu.approval.repository import SQLiteApprovalRepository
from pu.db import connect
from pu.identity.directory import provision_user
from pu.identity.files import write_owned_text
from pu.identity.legacy_import import import_legacy_rows
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.requests import coerce_workspace_id, discard_client_owner
from pu.identity.session import act_as
from pu.ops.briefing import BriefingService
from pu.persistence import SQLiteDatabase
from pu.persistence.ownership import OWNED_TABLES
from pu.persistence.postgres_schema import PRIVATE_TABLES, install
from pu.reporting.repository import FileReportRepository

A_MARK = "review-a-marker"
B_MARK = "review-b-marker"


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
    return home, conn, home, user_a, user_b


def _action(action_id: str, principal: str) -> ProposedAction:
    stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    return ProposedAction(
        id=action_id,
        tool_name="send_message",
        arguments={"body": principal},
        action_hash="a" * 64,
        status=ApprovalStatus.EXECUTING,
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
        execution_id="exec-" + action_id,
    )


def test_ownership_migration_resumes_after_mid_rebuild_crash(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    conn.execute(
        "INSERT INTO facts(subject, content) VALUES('crash', 'searchable-fact')"
    )
    conn.execute("INSERT INTO briefing_state(key, value) VALUES('lease_until', '1')")
    conn.execute(
        """INSERT INTO briefing_seen(gmail_id, domain, reason, seen_at)
           VALUES('msg-1', 'example.test', 'kept', 't')"""
    )
    conn.commit()
    conn.execute("ALTER TABLE briefing_state RENAME TO briefing_state__pre_owner")
    conn.execute(
        """CREATE TABLE briefing_state (
               key TEXT NOT NULL,
               value TEXT NOT NULL,
               owner_user_id TEXT NOT NULL DEFAULT '',
               PRIMARY KEY(key, owner_user_id)
           )"""
    )
    conn.execute("ALTER TABLE briefing_seen RENAME TO briefing_seen__pre_owner")
    conn.execute("DROP TABLE facts_fts")
    conn.execute(
        """CREATE VIRTUAL TABLE facts_fts USING fts5(
               subject, content, owner_user_id UNINDEXED, content=facts, content_rowid=id
           )"""
    )
    conn.execute("DELETE FROM schema_migrations WHERE version = 9005")
    conn.commit()
    conn.close()

    conn = connect(home)
    found = conn.execute(
        "SELECT content FROM facts_fts WHERE facts_fts MATCH 'searchable'"
    ).fetchall()
    assert [row[0] for row in found] == ["searchable-fact"]
    state = conn.execute(
        "SELECT value FROM briefing_state WHERE key = 'lease_until'"
    ).fetchone()
    assert state[0] == "1"
    seen = conn.execute(
        "SELECT reason FROM briefing_seen WHERE gmail_id = 'msg-1'"
    ).fetchone()
    assert seen[0] == "kept"
    assert conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 9005"
    ).fetchone()
    leftovers = conn.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE '%__pre_owner'"
    ).fetchall()
    assert leftovers == []
    assert conn.execute("PRAGMA table_info(crm_emails)").fetchall()
    pk = [
        row[1]
        for row in conn.execute("PRAGMA table_info(crm_emails)")
        if row[5]
    ]
    assert pk == ["gmail_id", "owner_user_id"]
    conn.close()


def test_crm_emails_keep_one_row_per_owner_for_the_same_gmail_id(tmp_path):
    from pu.tools.gmail import upsert_messages

    home, conn, seam, user_a, user_b = _open(tmp_path)
    row = {
        "gmail_id": "same-id",
        "thread_id": "t",
        "sender_name": "A",
        "sender_email": "a@example.test",
        "subject": A_MARK,
        "snippet": "",
        "body_text": "",
        "internal_date": "2026-10-21T00:00:00+00:00",
        "unread": 1,
    }
    with _as(seam, user_a):
        assert upsert_messages(conn, [row]) == 1
    with _as(seam, user_b):
        other = dict(row, subject=B_MARK, sender_name="B")
        assert upsert_messages(conn, [other]) == 1
        visible = conn.execute(
            """SELECT subject FROM crm_emails
               WHERE gmail_id='same-id' AND owner_user_id = pu_current_owner()"""
        ).fetchall()
        assert [item[0] for item in visible] == [B_MARK]
    with _as(seam, user_a):
        changed = dict(row, subject="alpha-updated", unread=0)
        upsert_messages(conn, [changed])
        visible = conn.execute(
            """SELECT subject FROM crm_emails
               WHERE owner_user_id = pu_current_owner()"""
        ).fetchall()
        assert [item[0] for item in visible] == ["alpha-updated"]
    both = conn.execute("SELECT owner_user_id, subject FROM crm_emails").fetchall()
    assert {row[1] for row in both} == {"alpha-updated", B_MARK}
    conn.close()
    assert home.is_dir()


def test_dashboard_snapshot_sql_and_reveal_hide_the_other_owner(tmp_path, monkeypatch):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    with _as(seam, user_a):
        conn.execute("INSERT INTO facts(subject, content) VALUES('a', ?)", (A_MARK,))
    conn.commit()
    with _as(seam, user_b):
        conn.execute("INSERT INTO facts(subject, content) VALUES('b', ?)", (B_MARK,))
        conn.execute(
            """INSERT INTO crm_emails(gmail_id, subject, internal_date)
               VALUES('beta-mail', ?, '2026-10-21T00:00:00+00:00')""",
            (B_MARK,),
        )
    conn.commit()
    conn.close()
    other = home / "owners" / user_b.user_id
    other.mkdir(parents=True, exist_ok=True)
    (other / "note.txt").write_text("beta-file-secret", encoding="utf-8")
    (home / "shared-secret.txt").write_text("shared-home-secret", encoding="utf-8")

    from pu.config import Settings
    from pu.ops.dashboard import approvals_info, collect, reveal_path, run_query

    def settings():
        value = Settings(home=home)
        value.ensure_home()
        return value

    monkeypatch.setattr("pu.ops.dashboard.load_settings", settings)
    monkeypatch.setattr("pu.config.load_settings", settings)
    monkeypatch.setattr("pu.ops.settings_api.load_settings", settings)

    with _as(seam, user_a):
        conn = connect(home)
        conn.execute(
            """INSERT INTO crm_emails(gmail_id, subject, internal_date)
               VALUES('alpha-mail', ?, '2026-10-21T00:00:00+00:00')""",
            (A_MARK,),
        )
        conn.commit()
        conn.close()
        snapshot = collect()
        revealed = reveal_path(f"../owners/{user_b.user_id}/note.txt")
        nested = reveal_path(f"owners/{user_b.user_id}/note.txt")
        queried = run_query({"sql": "SELECT subject FROM crm_emails"})
        hidden = run_query({"sql": "SELECT id FROM users"})
        info = approvals_info(home)
    rendered = str(snapshot["facts"]) + str(snapshot["crm"]) + str(snapshot["db"])
    assert A_MARK in rendered
    assert B_MARK not in rendered
    assert revealed == {"error": "path belongs to another owner"}
    assert nested == {"error": "path belongs to another owner"}
    assert "beta-file-secret" not in str(revealed) + str(nested)
    assert B_MARK not in str(queried)
    assert A_MARK in str(queried)
    assert hidden.get("rows") in (None, [])
    assert "error" in hidden
    assert info["items"] == []


def test_approvals_repository_and_dashboard_are_owner_filtered(tmp_path, monkeypatch):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    conn.close()
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_b):
        repo.create(_action("beta-action", B_MARK))
    with _as(seam, user_a):
        repo.create(_action("alpha-action", A_MARK))
        assert repo.get("beta-action") is None
        assert repo.get("alpha-action").id == "alpha-action"
        assert [item.id for item in repo.list()] == ["alpha-action"]
        recovered = repo.recover_inflight()
        assert [item.id for item in recovered] == ["alpha-action"]
        assert recovered[0].status == ApprovalStatus.FAILED
    with _as(seam, user_b):
        still = repo.get("beta-action")
        assert still is not None and still.status == ApprovalStatus.EXECUTING

    from pu.config import Settings
    from pu.ops.dashboard import approvals_info

    monkeypatch.setattr(
        "pu.ops.dashboard.load_settings",
        lambda: Settings(home=home),
    )
    with _as(seam, user_a):
        payload = approvals_info(home)
    assert [item["id"] for item in payload["items"]] == ["alpha-action"]
    assert B_MARK not in str(payload)


def test_briefing_snapshot_retry_and_enqueue_follow_the_principal(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    with _as(seam, user_b):
        conn.execute(
            """INSERT INTO research_workspaces(
                   id, company, website, contact, created_at, updated_at
               ) VALUES(?, 'Beta Co', '', '', 't', 't')""",
            (user_b.workspace_id,),
        )
        conn.execute(
            """INSERT INTO briefing_jobs(
                   id, fingerprint, workspace_id, email_ids_json, status, created_at, updated_at
               ) VALUES('job-b', 'fp-b', ?, '[]', 'failed', 't', 't')""",
            (user_b.workspace_id,),
        )
    conn.commit()
    with _as(seam, user_a):
        conn.execute(
            """INSERT INTO research_workspaces(
                   id, company, website, contact, created_at, updated_at
               ) VALUES(?, 'Alpha Co', '', '', 't', 't')""",
            (user_a.workspace_id,),
        )
        conn.execute(
            """INSERT INTO briefing_jobs(
                   id, fingerprint, workspace_id, email_ids_json, status, created_at, updated_at
               ) VALUES('job-a', 'fp-a', ?, '[]', 'queued', 't', 't')""",
            (user_a.workspace_id,),
        )
    conn.commit()
    service = BriefingService(home)
    with _as(seam, user_a):
        companies = [job["company"] for job in service.snapshot()["jobs"]]
        assert companies == ["Alpha Co"]
        with service.repo.database.connection() as owned:
            conn_retry = owned
            conn_retry.execute(
                """UPDATE briefing_jobs
                   SET status='queued', stage='queued', error='', attempts=0, updated_at='t2'
                   WHERE id='job-b' AND status='failed' AND owner_user_id = pu_current_owner()"""
            )
        seen = {}

        def remember():
            from pu.identity.directory import current_principal

            current = current_principal(conn)
            seen["user"] = current.user_id
            seen["kind"] = current.kind

        service._run_as_owner(user_b.user_id, remember)
        with service.repo.database.connection() as owned:
            wid = coerce_workspace_id(owned, user_b.workspace_id)
        assert wid == user_a.workspace_id
    assert seen == {"user": user_b.user_id, "kind": PrincipalKind.WORKER}
    status = conn.execute(
        "SELECT status FROM briefing_jobs WHERE id='job-b'"
    ).fetchone()
    assert status[0] == "failed"
    cleaned = discard_client_owner(
        {"op": "enqueue", "workspace_id": user_b.workspace_id, "owner_user_id": user_b.user_id}
    )
    assert "owner_user_id" not in cleaned
    conn.close()


def test_legacy_import_rolls_back_the_batch_when_a_later_insert_fails(tmp_path):
    _home, conn, seam, user_a, _user_b = _open(tmp_path)
    batch = [
        {
            "table": "facts",
            "legacy_owner": "local-user",
            "values": {"subject": "fixture", "content": "kept-then-rolled"},
        },
        {
            "table": "facts",
            "legacy_owner": "local-user",
            "values": {"no_such_column": "x"},
        },
    ]
    with _as(seam, user_a), pytest.raises(sqlite3.OperationalError):
        import_legacy_rows(conn, {"local-user": user_a.user_id}, batch)
    left = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE content = 'kept-then-rolled'"
    ).fetchone()
    assert left[0] == 0
    conn.close()


def test_sqlite_trigger_rejects_a_workflow_id_postgres_would_reject(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    with _as(seam, user_a):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO agent_events(
                       id, schema_version, kind, occurred_at, severity, payload_json, workflow_id
                   ) VALUES('evt-missing', 1, 'llm', 't', 'info', '{}', 'missing-wf')"""
            )
        conn.rollback()
        conn.execute(
            """INSERT INTO workflow_runs(
                   id, workflow_type, status, request_json, created_at, updated_at
               ) VALUES('real-wf', 'morning_research', 'running', '{}', 't', 't')"""
        )
        conn.execute(
            """INSERT INTO agent_events(
                   id, schema_version, kind, occurred_at, severity, payload_json, workflow_id
               ) VALUES('evt-real', 1, 'llm', 't', 'info', '{}', 'real-wf')"""
        )
        conn.execute(
            """INSERT INTO tool_audit_events(
                   execution_id, actor, tool, capability, required_scope, side_effect, external,
                   action_hash, status, timestamp, record_json, workflow_id
               ) VALUES('ex', 'agent', 'lookup', 'web:read', 'web:read', 0, 0,
                        'h', 'ok', 't', '{}', NULL)"""
        )
    conn.commit()
    with _as(seam, user_b), pytest.raises(sqlite3.IntegrityError):
        conn.execute(
                """INSERT INTO proposed_actions(
                       id, tool_name, arguments_json, action_hash, status, principal,
                       capability, required_scope, side_effect, external, risk,
                       created_at, updated_at, expires_at, revision, workflow_id
                   ) VALUES('act-b', 'send_message', '{}', 'h', 'pending', 'b',
                            'message:write', 'message:write', 1, 0, 'low',
                            't', 't', 't', 1, 'real-wf')"""
            )
    conn.close()
    assert home.is_dir()


def test_private_files_and_report_list_do_not_mirror_into_the_shared_home(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    conn.close()
    with _as(seam, user_a):
        written = write_owned_text(home, "notes/secret.txt", A_MARK)
    assert written.is_file()
    assert not (home / "notes" / "secret.txt").exists()
    shared = home / "reports"
    shared.mkdir()
    (shared / "report-shared.json").write_text(
        '{"report_id":"report-shared","title":"' + B_MARK + '"}', encoding="utf-8"
    )
    with _as(seam, user_a):
        assert FileReportRepository(home).list() == []
    with _as(seam, user_b):
        assert FileReportRepository(home).list() == []


def test_install_requires_a_password_and_refuses_to_drop_existing_rows():
    with pytest.raises(ValueError, match="password"):
        install(object())
    assert "users" not in PRIVATE_TABLES

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    class _Conn:
        def __init__(self):
            self.statements: list[str] = []
            self.autocommit = False

        def execute(self, query, params=None):
            text = query if isinstance(query, str) else str(query)
            self.statements.append(text)
            if "schemata" in text:
                return _Result([(1,)])
            if "information_schema.tables" in text:
                return _Result([("facts",)])
            if "COUNT" in text.upper():
                return _Result([(4,)])
            return _Result([])

    conn = _Conn()
    with pytest.raises(RuntimeError, match="refusing to DROP SCHEMA"):
        install(conn, password="fixture-only", replace_existing=False)
    assert not any("DROP SCHEMA" in statement for statement in conn.statements)


# The briefing worker must see every due owner, then attach that owner per job.
# Platform admin metrics count every owner and select no payload text.
# Mentioning the column is not a filter; these statements are the allowlist.
CROSS_OWNER_ALLOWLIST = (
    ("pu/ops/briefing.py", "SELECT DISTINCT owner_user_id FROM briefing_jobs"),
    ("pu/ops/briefing.py", "SELECT owner_user_id FROM briefing_state"),
    (
        "pu/persistence/events.py",
        "SELECT kind, status, duration_ms",
    ),
)


def _has_owner_filter(statement: str) -> bool:
    if "pu_current_owner" in statement:
        return True
    # ``?`` is SQLite. ``%s`` is the same bound owner predicate on PostgreSQL.
    return re.search(r"(?i)\bowner_user_id\s*=\s*(\?|%s)", statement) is not None


def _cross_owner_allowed(path: Path, statement: str) -> str:
    for allowed_path, snippet in CROSS_OWNER_ALLOWLIST:
        if path.as_posix() == allowed_path and snippet in statement:
            return snippet
    return ""


def test_private_table_statements_carry_an_owner_filter():
    skip = {
        Path("pu/persistence/ownership.py"),
        Path("pu/persistence/postgres_schema.py"),
        Path("pu/persistence/migrations.py"),
        Path("pu/db.py"),
    }
    select_from = re.compile(
        r"(?is)\bSELECT\b[\s\S]{0,1200}?\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    update_set = re.compile(r"(?is)\bUPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET\b")
    delete_from = re.compile(r"(?is)\bDELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)")
    hits: list[str] = []
    used_allowlist: set[tuple[str, str]] = set()
    for path in Path("pu").rglob("*.py"):
        if path in skip:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        joined_parts = {
            id(value)
            for node in ast.walk(tree)
            if isinstance(node, ast.JoinedStr)
            for value in node.values
            if isinstance(value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and id(node) in joined_parts:
                continue
            statement = _statement_text(node)
            if not statement:
                continue
            tables = {
                match.group(1)
                for pattern in (select_from, update_set, delete_from)
                for match in pattern.finditer(statement)
            }
            if not tables & set(OWNED_TABLES):
                continue
            if _has_owner_filter(statement):
                continue
            allowed = _cross_owner_allowed(path, statement)
            if allowed:
                used_allowlist.add((path.as_posix(), allowed))
                continue
            hits.append(f"{path}:{getattr(node, 'lineno', 0)}: {' '.join(statement.split())[:160]}")
    assert hits == []
    assert used_allowlist == set(CROSS_OWNER_ALLOWLIST)


def _statement_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append(" ")
        return "".join(parts)
    return ""

"""Phase 2 gates: session, CSRF, encrypted tokens, worker reads, and recovery.

Fixtures are synthetic users A and B. The identity provider is an in-process
fake. No real client secret, mailbox, or customer token is used.
"""

from __future__ import annotations

import io
import json
import sqlite3
import threading
import time
import urllib.parse
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from pu.approval.models import ApprovalStatus, ProposedAction
from pu.approval.repository import SQLiteApprovalRepository
from pu.approval.service import HumanApprovalService
from pu.config import Settings
from pu.core.interfaces.tools import ToolResult
from pu.db import connect
from pu.harness.audit import ToolAuditRecord
from pu.harness.gateway import execute_worker_read
from pu.identity.crypto import decrypt
from pu.identity.directory import provision_user
from pu.identity.files import OwnershipDenied, read_owned_bytes, write_owned_text
from pu.identity.oidc import AuthError, OidcProvider, sign_hs256
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.seam import InternalPrincipalSeam, attached_principal
from pu.identity.session import (
    SESSION_COOKIE,
    AuthStore,
    evaluate_on_home,
    format_set_cookie,
)
from pu.identity.threads import spawn_inheriting
from pu.ops.agentops import AgentOpsHarness
from pu.ops.tracing import Tracer
from pu.persistence import SQLiteDatabase, SQLiteToolAuditSink
from pu.reporting.workspace import WorkspaceRepository

A_MARK = "fixture-a-marker"
B_MARK = "fixture-b-marker"
B_SECRET = "beta-approval-secret"
TOKEN_KEY = "phase2-key-outside-db-xx"
ACCESS_TOKEN = "ya29.phase2providertokenvalue"
CLIENT_SECRET = "test-client-secret"


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
    conn.close()
    return home, InternalPrincipalSeam(), user_a, user_b


def _settings(home):
    settings = Settings(home=home)
    settings.ensure_home()
    return settings


def _provider(http_post):
    return OidcProvider(
        authorization_endpoint="https://idp.test/authorize",
        token_endpoint="https://idp.test/token",
        client_id="pu-test",
        redirect_uri="https://app.test/api/auth/callback",
        client_secret=CLIENT_SECRET,
        http_post=http_post,
    )


def _http_post_for(subject: str, seen: dict):
    def http_post(_url, form):
        seen["form"] = dict(form)
        return {"id_token": sign_hs256({"sub": subject}, CLIENT_SECRET)}

    return http_post


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


def _audit(mark: str) -> ToolAuditRecord:
    return ToolAuditRecord(
        execution_id="exec-" + mark,
        request_id="req-" + mark,
        workflow_id=None,
        agent_id="worker",
        tool_call_id="call-" + mark,
        actor="worker",
        principal="worker",
        tool="read_gmail_today",
        capability="email:read",
        required_scope="email:read",
        side_effect=False,
        external=True,
        arguments={},
        action_hash="b" * 64,
        status="executed",
        timestamp="2026-10-21T00:00:00.000Z",
        reason=mark,
    )


class _Handler:
    def __init__(self, method: str, path: str, headers: dict, body: bytes = b""):
        from pu.ops.dashboard import Handler

        self.statuses: list[int] = []
        self.sent: list[tuple[str, str]] = []
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = headers
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = self.statuses.append
        handler.send_header = lambda key, value: self.sent.append((key, value))
        handler.end_headers = lambda: None
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        self.body = handler.wfile.getvalue()


def _cookie(headers: list[tuple[str, str]], name: str) -> str:
    for key, value in headers:
        if key == "Set-Cookie" and value.startswith(name + "="):
            return value
    raise AssertionError(name)


def test_mu11_oidc_pkce_sets_lax_cookie_and_checks_state(tmp_path, monkeypatch):
    home, _seam, _user_a, _user_b = _open(tmp_path)
    monkeypatch.setattr("pu.config.load_settings", lambda: _settings(home))
    seen: dict = {}
    provider = _provider(_http_post_for("subject-a", seen))
    monkeypatch.setattr("pu.ops.dashboard._oidc_provider_from_env", lambda: provider)
    login = _Handler("GET", "/api/auth/login", {})
    cookie = _cookie(login.sent, "pu_oidc")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert "SameSite=Strict" not in cookie
    payload = json.loads(login.body)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(payload["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in query
    verifier_later = seen.get("form")
    assert verifier_later is None
    transaction = cookie.split(";", 1)[0].split("=", 1)[1]
    callback = _Handler(
        "GET",
        "/api/auth/callback?code=auth-code&state=" + query["state"][0],
        {"Cookie": f"pu_oidc={transaction}"},
    )
    assert callback.statuses == [200]
    issued = json.loads(callback.body)
    assert issued["csrf_token"]
    session_cookie = _cookie(callback.sent, SESSION_COOKIE)
    assert "HttpOnly" in session_cookie and "Secure" in session_cookie
    assert "SameSite=Lax" in session_cookie
    assert seen["form"]["code_verifier"]
    assert seen["form"]["code_verifier"] not in payload["authorization_url"]
    assert seen["form"]["grant_type"] == "authorization_code"
    store = AuthStore(home)
    with pytest.raises(AuthError) as missing:
        store.complete_oidc(provider, code="c", state="s", transaction_cookie="")
    assert missing.value.code == "oidc_cookie"
    started = store.begin_oidc(provider)
    with pytest.raises(AuthError) as mismatch:
        store.complete_oidc(
            provider,
            code="c",
            state="not-the-state",
            transaction_cookie=started.transaction_id,
        )
    assert mismatch.value.code == "state"


def test_mu11_csrf_rejects_state_change_and_legacy_loopback_still_runs(tmp_path, monkeypatch):
    home, _seam, user_a, _user_b = _open(tmp_path)
    monkeypatch.setattr("pu.config.load_settings", lambda: _settings(home))
    issued = AuthStore(home).issue_session(user_a)
    assert "HttpOnly" in issued.set_cookie
    assert "Secure" in issued.set_cookie
    assert "SameSite=Lax" in issued.set_cookie
    bare = {"Cookie": f"{SESSION_COOKIE}={issued.session_id}", "Content-Length": "2"}
    blocked = _Handler("POST", "/api/chat/stop", bare, b"{}")
    assert blocked.statuses == [403]
    assert json.loads(blocked.body)["error"] == "csrf"
    wrong = {**bare, "X-CSRF-Token": "not-the-session-token"}
    mismatched = _Handler("POST", "/api/chat/stop", wrong, b"{}")
    assert mismatched.statuses == [403]
    assert json.loads(mismatched.body)["error"] == "csrf"
    allowed_headers = {**bare, "X-CSRF-Token": issued.csrf_token}
    allowed = _Handler("POST", "/api/chat/stop", allowed_headers, b"{}")
    assert allowed.statuses == [200]
    assert "accepted" in json.loads(allowed.body)
    legacy = _Handler("POST", "/api/chat/stop", {"Content-Length": "2"}, b"{}")
    assert legacy.statuses == [200]
    assert "accepted" in json.loads(legacy.body)
    assert evaluate_on_home({}, mutate=True).rejected is False
    AuthStore(home).revoke_session(issued.session_id)
    revoked = _Handler("GET", "/api/briefing", {"Cookie": f"{SESSION_COOKIE}={issued.session_id}"})
    assert revoked.statuses == [401]
    assert json.loads(revoked.body)["error"] == "session_revoked"
    assert format_set_cookie(SESSION_COOKIE, "x").count("SameSite=Lax") == 1


def test_mu03_foreign_connection_does_not_call_provider(tmp_path, monkeypatch):
    home, _seam, user_a, user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    store = AuthStore(home)
    foreign = store.save_oauth_token(
        owner_user_id=user_b.user_id,
        provider="gmail",
        token={"access_token": ACCESS_TOKEN},
    )
    calls: list[str] = []

    def provider_call(token):
        calls.append(token["access_token"])
        return "sent"

    assert store.use_oauth_connection(
        foreign, owner_user_id=user_a.user_id, provider_call=provider_call
    ) is None
    assert calls == []

    class _Harness:
        def execute(self, name, arguments, context):
            calls.append(name)
            assert context.metadata["principal_kind"] == PrincipalKind.WORKER.value
            assert context.metadata["owner_user_id"] == user_a.user_id
            return ToolResult(ok=True, output="{}")

    blocked = execute_worker_read(
        _Harness(),
        "read_gmail_today",
        {"connection_id": foreign},
        owner_user_id=user_a.user_id,
        workspace_id=user_a.workspace_id,
        home=home,
    )
    assert blocked.ok is False
    assert blocked.error == "connection_denied"
    assert calls == []
    own = store.save_oauth_token(
        owner_user_id=user_a.user_id,
        provider="gmail",
        token={"access_token": ACCESS_TOKEN},
    )
    assert store.use_oauth_connection(
        own, owner_user_id=user_a.user_id, provider_call=provider_call
    ) == "sent"
    assert calls == [ACCESS_TOKEN]
    blob = (home / "state.db").read_bytes()
    assert ACCESS_TOKEN.encode() not in blob
    assert TOKEN_KEY.encode() not in blob
    row = sqlite3.connect(home / "state.db").execute(
        "SELECT token_ciphertext FROM oauth_connections WHERE id=?", (own,)
    ).fetchone()
    assert decrypt(row[0]).decode().find(ACCESS_TOKEN) >= 0


def test_mu04_other_owner_approval_is_not_found(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_b):
        repo.create(_action("act-b", user_b.user_id, pending=True, secret=B_SECRET))
    with _as(seam, user_a):
        with pytest.raises(KeyError) as denied:
            HumanApprovalService(repo).approve("act-b")
        assert B_SECRET not in str(denied.value)
        assert repo.get("act-b") is None
    with _as(seam, user_b):
        assert repo.get("act-b").status is ApprovalStatus.PENDING


def test_mu05_concurrent_worker_threads_do_not_mix_rows(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def job(owner_id: str, mark: str, website: str) -> None:
        try:
            barrier.wait(timeout=5)
            assert attached_principal().user_id == owner_id
            repo = WorkspaceRepository(home)
            workspace = repo.create(mark, website)
            repo.add_source(workspace["id"], title=mark, content=mark, source_type="document")
            write_owned_text(home, f"notes/{mark}.txt", mark)
            conn = connect(home)
            conn.execute(
                "INSERT INTO calendar_events(title, start) VALUES(?, ?)",
                (mark, "2026-10-21T09:00:00"),
            )
            conn.execute(
                "INSERT INTO crm_emails(gmail_id, subject, internal_date) VALUES(?, ?, ?)",
                (mark, mark, "2026-10-21T00:00:00+00:00"),
            )
            conn.commit()
            conn.close()
            SQLiteToolAuditSink(SQLiteDatabase.from_home(home)).append(_audit(mark))
        except BaseException as exc:
            errors.append(exc)

    with _as(seam, user_a):
        first = spawn_inheriting(
            lambda: job(user_a.user_id, A_MARK, "https://alpha.example"), name="job-a"
        )
    with _as(seam, user_b):
        second = spawn_inheriting(
            lambda: job(user_b.user_id, B_MARK, "https://beta.example"), name="job-b"
        )
    first.join(timeout=10)
    second.join(timeout=10)
    assert errors == []
    with _as(seam, user_a):
        companies = [row["company"] for row in WorkspaceRepository(home).list()]
        assert companies == [A_MARK]
        conn = connect(home)
        titles = [
            row[0]
            for row in conn.execute(
                "SELECT title FROM calendar_events WHERE owner_user_id = pu_current_owner()"
            )
        ]
        subjects = [
            row[0]
            for row in conn.execute(
                "SELECT subject FROM crm_emails WHERE owner_user_id = pu_current_owner()"
            )
        ]
        conn.close()
        assert titles == [A_MARK]
        assert subjects == [A_MARK]
        assert read_owned_bytes(home, f"notes/{A_MARK}.txt") == A_MARK.encode()
        with pytest.raises(OwnershipDenied):
            read_owned_bytes(home, f"notes/{B_MARK}.txt")
        reasons = [item["reason"] for item in SQLiteToolAuditSink(SQLiteDatabase.from_home(home)).list()]
        assert reasons == [A_MARK]
    with _as(seam, user_b):
        companies = [row["company"] for row in WorkspaceRepository(home).list()]
        assert companies == [B_MARK]


def test_background_thread_inherits_principal_context(tmp_path):
    _home, seam, user_a, _user_b = _open(tmp_path)
    seen: dict[str, str] = {}

    def sample() -> None:
        current = attached_principal()
        seen["id"] = current.user_id if current else ""

    with _as(seam, user_a):
        raw = threading.Thread(target=sample)
        raw.start()
        raw.join()
    assert seen["id"] == ""
    with _as(seam, user_a):
        inherited = spawn_inheriting(sample, name="inherit-principal")
        inherited.join()
    assert seen["id"] == user_a.user_id


def test_mu06_revocation_blocks_the_next_request(tmp_path, monkeypatch):
    home, _seam, user_a, _user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    store = AuthStore(home)
    issued = store.issue_session(user_a)
    headers = {"Cookie": f"{SESSION_COOKIE}={issued.session_id}", "X-CSRF-Token": issued.csrf_token}
    assert store.evaluate(headers, mutate=True).rejected is False
    store.revoke_session(issued.session_id)
    revoked = store.evaluate(headers, mutate=True)
    assert revoked.rejected is True
    assert revoked.reason == "session_revoked"
    connection_id = store.save_oauth_token(
        owner_user_id=user_a.user_id,
        provider="gmail",
        token={"access_token": ACCESS_TOKEN},
    )
    assert store.revoke_oauth_connection(connection_id, owner_user_id=user_a.user_id) is True
    calls: list[str] = []
    assert store.use_oauth_connection(
        connection_id,
        owner_user_id=user_a.user_id,
        provider_call=lambda token: calls.append(token["access_token"]),
    ) is None
    assert calls == []


def test_mu08_encryption_key_stays_out_of_jsonl_and_database(tmp_path, monkeypatch):
    home, _seam, _user_a, _user_b = _open(tmp_path)
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    settings = Settings(home=home, otel_endpoint="")
    settings.ensure_home()
    tracer = Tracer(settings)
    AgentOpsHarness(_repository(home), tracer=tracer).publish(
        "tool_complete",
        {"output": TOKEN_KEY},
    )
    assert TOKEN_KEY not in tracer.path.read_text(encoding="utf-8")
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
            timestamp="2026-10-21T00:00:00.000Z",
            reason=TOKEN_KEY,
            result_summary=TOKEN_KEY,
            error=TOKEN_KEY,
        )
    )
    blob = (home / "state.db").read_bytes()
    assert TOKEN_KEY.encode() not in blob
    with SQLiteDatabase.from_home(home).connection() as conn:
        row = conn.execute(
            "SELECT reason, result_summary, error FROM tool_audit_events"
        ).fetchone()
    assert TOKEN_KEY not in (row["reason"] or "")
    assert TOKEN_KEY not in (row["result_summary"] or "")
    assert TOKEN_KEY not in (row["error"] or "")


def _repository(home):
    from pu.persistence import SQLiteAgentEventRepository

    return SQLiteAgentEventRepository(SQLiteDatabase.from_home(home))


def test_mu09_dead_lease_fails_only_the_current_owner(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    repo = SQLiteApprovalRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_a):
        repo.create(_action("act-a", user_a.user_id, pending=False, secret="alpha"))
        pending = _action("act-pending", user_a.user_id, pending=True, secret="alpha-pending")
        repo.create(pending)
        with SQLiteDatabase.from_home(home).connection() as conn:
            conn.execute(
                "INSERT INTO briefing_state(key, value) VALUES('lease_until', ?)",
                (str(time.time() - 30),),
            )
    with _as(seam, user_b):
        repo.create(_action("act-b", user_b.user_id, pending=False, secret=B_SECRET))
    with _as(seam, user_a):
        recovered = repo.recover_inflight()
        assert [item.id for item in recovered] == ["act-a"]
        assert repo.get("act-a").status is ApprovalStatus.FAILED
        assert "uncertain" in (repo.get("act-a").error or "")
        assert repo.get("act-a").execution_id == "exec-act-a"
        assert repo.get("act-pending").status is ApprovalStatus.PENDING
        assert repo.get("act-b") is None
    with _as(seam, user_b):
        assert repo.get("act-b").status is ApprovalStatus.EXECUTING
        assert repo.recover_inflight()[0].id == "act-b"
        assert repo.get("act-b").status is ApprovalStatus.FAILED


def test_reveal_path_and_sql_console_stay_inside_the_owner(tmp_path, monkeypatch):
    home, seam, user_a, user_b = _open(tmp_path)
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: _settings(home))
    (home / "shared-secret.txt").write_text("shared-home-secret", encoding="utf-8")
    other = home / "owners" / user_b.user_id
    other.mkdir(parents=True)
    (other / "note.txt").write_text("beta-file-secret", encoding="utf-8")
    with _as(seam, user_b):
        conn = connect(home)
        conn.execute(
            "INSERT INTO crm_emails(gmail_id, subject, internal_date) VALUES(?, ?, ?)",
            ("beta-mail", B_MARK, "2026-10-21T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()
    with _as(seam, user_a):
        conn = connect(home)
        conn.execute(
            "INSERT INTO crm_emails(gmail_id, subject, internal_date) VALUES(?, ?, ?)",
            ("alpha-mail", A_MARK, "2026-10-21T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()
        from pu.ops.dashboard import reveal_path, run_query

        shared = reveal_path("shared-secret.txt")
        database = reveal_path("state.db")
        escaped = reveal_path(f"../owners/{user_b.user_id}/note.txt")
        nested = reveal_path(f"owners/{user_b.user_id}/note.txt")
        queried = run_query({"sql": "SELECT subject FROM crm_emails"})
        hidden = run_query({"sql": "SELECT csrf_token FROM auth_sessions"})
    rendered = json.dumps({"shared": shared, "database": database, "escaped": escaped, "nested": nested})
    assert shared.get("ok") is not True
    assert database.get("ok") is not True
    assert escaped.get("ok") is not True
    assert "shared-home-secret" not in rendered
    assert "beta-file-secret" not in rendered
    assert B_MARK not in json.dumps(queried)
    assert A_MARK in json.dumps(queried)
    assert "error" in hidden
    assert "csrf_token" not in json.dumps(hidden.get("rows", []))

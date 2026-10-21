"""Application sessions, CSRF, and encrypted provider connections.

The browser session is an HttpOnly Secure SameSite=Lax cookie. Lax keeps the
OIDC transaction cookie on the top-level GET callback. It does not authorize
a state change: every mutation still presents the session's CSRF token.
Revocation is a row update checked on the next request.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pu.identity.crypto import decrypt, encrypt
from pu.identity.directory import ensure_identity_tables, provision_user
from pu.identity.oidc import (
    AuthError,
    OidcProvider,
    authorization_url,
    exchange_code,
    pkce_pair,
)
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.seam import InternalPrincipalSeam

SESSION_COOKIE = "pu_session"
OIDC_COOKIE = "pu_oidc"
CSRF_HEADER = "X-CSRF-Token"

_DDL = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS oidc_transactions (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oidc_subjects (
    sub TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_connections (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    token_ciphertext TEXT NOT NULL,
    revoked_at TEXT
);
"""


def format_set_cookie(name: str, value: str, *, max_age: int | None = None) -> str:
    """HttpOnly Secure SameSite=Lax. Lax is what lets the OIDC callback see it."""
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "Secure", "SameSite=Lax"]
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    return "; ".join(parts)


def cookie_value(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    raw = ""
    if getter is not None:
        raw = getter("Cookie") or getter("cookie") or ""
    for part in str(raw).split(";"):
        item = part.strip()
        if item.startswith(name + "="):
            return item.split("=", 1)[1].strip()
    return ""


def header_value(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return str(getter(name) or getter(name.lower()) or "")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _equal(left: str, right: str) -> bool:
    left_b, right_b = left.encode("utf-8"), right.encode("utf-8")
    if len(left_b) != len(right_b):
        return False
    return secrets.compare_digest(left_b, right_b)


@dataclass(frozen=True)
class OidcStart:
    authorization_url: str
    set_cookie: str
    transaction_id: str


@dataclass(frozen=True)
class SessionIssued:
    session_id: str
    csrf_token: str
    principal: Principal
    set_cookie: str
    clear_oidc_cookie: str


@dataclass(frozen=True)
class RequestDecision:
    rejected: bool
    reason: str = ""
    principal: Principal | None = None
    session_id: str = ""


class AuthStore:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "state.db"
        self._ensure()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure(self) -> None:
        with self._connect() as conn:
            ensure_identity_tables(conn)
            conn.executescript(_DDL)
            conn.commit()

    def begin_oidc(self, provider: OidcProvider) -> OidcStart:
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        transaction_id = secrets.token_urlsafe(24)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO oidc_transactions(id, state, code_verifier, created_at) VALUES(?,?,?,?)",
                (transaction_id, state, verifier, _now()),
            )
            conn.commit()
        return OidcStart(
            authorization_url=authorization_url(provider, state=state, challenge=challenge),
            set_cookie=format_set_cookie(OIDC_COOKIE, transaction_id, max_age=600),
            transaction_id=transaction_id,
        )

    def complete_oidc(
        self,
        provider: OidcProvider,
        *,
        code: str,
        state: str,
        transaction_cookie: str,
    ) -> SessionIssued:
        if not transaction_cookie or not code or not state:
            raise AuthError("oidc_cookie")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state, code_verifier FROM oidc_transactions WHERE id=?",
                (transaction_cookie,),
            ).fetchone()
            conn.execute("DELETE FROM oidc_transactions WHERE id=?", (transaction_cookie,))
            conn.commit()
        if row is None or not _equal(row["state"], state):
            raise AuthError("state")
        subject = exchange_code(provider, code=code, verifier=row["code_verifier"])
        principal = self._principal_for_subject(subject)
        return self.issue_session(principal)

    def _principal_for_subject(self, subject: str) -> Principal:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, workspace_id FROM oidc_subjects WHERE sub=?",
                (subject,),
            ).fetchone()
            if row is not None:
                return Principal(PrincipalKind.USER, row["user_id"], row["workspace_id"])
            principal = provision_user(conn)
            conn.execute(
                "INSERT INTO oidc_subjects(sub, user_id, workspace_id) VALUES(?,?,?)",
                (subject, principal.user_id, principal.workspace_id),
            )
            conn.commit()
            return principal

    def issue_session(self, principal: Principal) -> SessionIssued:
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO auth_sessions(
                       id, owner_user_id, workspace_id, csrf_token, created_at
                   ) VALUES(?,?,?,?,?)""",
                (session_id, principal.user_id, principal.workspace_id, csrf_token, _now()),
            )
            conn.commit()
        return SessionIssued(
            session_id=session_id,
            csrf_token=csrf_token,
            principal=principal,
            set_cookie=format_set_cookie(SESSION_COOKIE, session_id, max_age=12 * 60 * 60),
            clear_oidc_cookie=format_set_cookie(OIDC_COOKIE, "", max_age=0),
        )

    def revoke_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (_now(), session_id),
            )
            conn.commit()

    def csrf_token(self, session_id: str) -> str | None:
        session = self._live_session(session_id)
        if session is None:
            return None
        return session["csrf_token"]

    def _live_session(self, session_id: str) -> sqlite3.Row | None:
        if not session_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_sessions WHERE id=? AND revoked_at IS NULL",
                (session_id,),
            ).fetchone()
        return row

    def evaluate(self, headers: Any, *, mutate: bool) -> RequestDecision:
        session_id = cookie_value(headers, SESSION_COOKIE)
        if not session_id:
            return RequestDecision(rejected=False)
        session = self._live_session(session_id)
        if session is None:
            return RequestDecision(rejected=True, reason="session_revoked", session_id=session_id)
        if mutate:
            presented = header_value(headers, CSRF_HEADER)
            if not presented or not _equal(presented, session["csrf_token"]):
                return RequestDecision(rejected=True, reason="csrf", session_id=session_id)
        principal = Principal(
            PrincipalKind.USER, session["owner_user_id"], session["workspace_id"]
        )
        return RequestDecision(
            rejected=False, principal=principal, session_id=session_id
        )

    def save_oauth_token(self, *, owner_user_id: str, provider: str, token: dict) -> str:
        connection_id = str(uuid.uuid4())
        ciphertext = encrypt(json.dumps(token, separators=(",", ":")).encode("utf-8"))
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO oauth_connections(
                       id, owner_user_id, provider, token_ciphertext
                   ) VALUES(?,?,?,?)""",
                (connection_id, owner_user_id, provider, ciphertext),
            )
            conn.commit()
        return connection_id

    def revoke_oauth_connection(self, connection_id: str, *, owner_user_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE oauth_connections SET revoked_at=?
                   WHERE id=? AND owner_user_id=? AND revoked_at IS NULL""",
                (_now(), connection_id, owner_user_id),
            )
            conn.commit()
            return cursor.rowcount == 1

    def _connection(self, connection_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM oauth_connections WHERE id=?",
                (connection_id,),
            ).fetchone()

    def owner_may_call(self, connection_id: str, owner_user_id: str) -> bool:
        row = self._connection(connection_id)
        if row is None or row["revoked_at"]:
            return False
        return row["owner_user_id"] == owner_user_id

    def use_oauth_connection(self, connection_id: str, *, owner_user_id: str, provider_call):
        """Decrypt and call only when this owner still holds a live connection.

        A foreign or revoked id returns before ``provider_call`` runs.
        """
        row = self._connection(connection_id)
        if row is None or row["revoked_at"] or row["owner_user_id"] != owner_user_id:
            return None
        token = json.loads(decrypt(row["token_ciphertext"]).decode("utf-8"))
        return provider_call(token)


def evaluate_on_home(headers: Any, *, mutate: bool) -> RequestDecision:
    """Check the session cookie when one is present. No cookie stays legacy."""
    if not cookie_value(headers, SESSION_COOKIE):
        return RequestDecision(rejected=False)
    from pu.config import load_settings

    home = load_settings().ensure_home()
    try:
        return AuthStore(home).evaluate(headers, mutate=mutate)
    except (sqlite3.Error, OSError, ValueError):
        return RequestDecision(rejected=True, reason="session_revoked")


def refuse_foreign_connection(home: Path | None, connection_id: str, owner_user_id: str) -> str | None:
    """Return an error code when this owner must not call the provider."""
    if not connection_id:
        return None
    if home is None or not owner_may_use(home, connection_id, owner_user_id):
        return "connection_denied"
    return None


def owner_may_use(home: Path, connection_id: str, owner_user_id: str) -> bool:
    return AuthStore(home).owner_may_call(connection_id, owner_user_id)


@contextmanager
def attached_decision(decision: RequestDecision) -> Iterator[RequestDecision]:
    if decision.principal is None:
        yield decision
        return
    seam = InternalPrincipalSeam()
    token = seam.attach(decision.principal)
    try:
        yield decision
    finally:
        seam.detach(token)

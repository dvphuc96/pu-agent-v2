"""Users and the one personal workspace each user is allowed to have."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from pu.identity.principal import Principal, PrincipalKind, issue_user_id, issue_workspace_id

_IDENTITY_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personal_workspaces (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS identity_local (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
    workspace_id TEXT NOT NULL UNIQUE REFERENCES personal_workspaces(id)
);
CREATE TABLE IF NOT EXISTS private_files (
    relative_path TEXT NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (relative_path, owner_user_id)
);
"""


def ensure_identity_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_IDENTITY_DDL)


def _raw(conn: sqlite3.Connection, sql: str, params: tuple = ()):
    """Run SQL without the ownership INSERT stamp."""
    cursor = sqlite3.Connection.cursor(conn)
    return cursor.execute(sql, params)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def provision_user(conn: sqlite3.Connection) -> Principal:
    """Issue a new user and exactly one personal workspace.

    The ids come from the backend. Nothing in the arguments can name them.
    """
    ensure_identity_tables(conn)
    user_id = issue_user_id()
    workspace_id = issue_workspace_id()
    stamp = _now()
    _raw(conn, "INSERT INTO users(id, created_at) VALUES(?, ?)", (user_id, stamp))
    _raw(
        conn,
        "INSERT INTO personal_workspaces(id, owner_user_id, created_at) VALUES(?, ?, ?)",
        (workspace_id, user_id, stamp),
    )
    return Principal(PrincipalKind.USER, user_id, workspace_id)


def ensure_local_principal(conn: sqlite3.Connection) -> Principal:
    """Return the single dev/test principal stored for this database.

    CLI and the single-user suite stamp rows with this owner when no HTTP
    request is in progress. A bound request never receives it.
    """
    ensure_identity_tables(conn)
    row = _raw(
        conn,
        "SELECT user_id, workspace_id FROM identity_local WHERE singleton = 1",
    ).fetchone()
    if row is None:
        principal = provision_user(conn)
        _raw(
            conn,
            "INSERT INTO identity_local(singleton, user_id, workspace_id) VALUES(1, ?, ?)",
            (principal.user_id, principal.workspace_id),
        )
    else:
        principal = Principal(PrincipalKind.USER, row[0], row[1])
    conn._pu_local_owner = principal.user_id  # type: ignore[attr-defined]
    conn._pu_local_workspace = principal.workspace_id  # type: ignore[attr-defined]
    return principal


def current_principal(conn: sqlite3.Connection) -> Principal:
    """Worker grant, else the authenticated session.

    A bound request with no session raises. It does not become the
    database-local owner. Outside a request, CLI and the single-user suite
    still use that one database owner so their rows stay visible.
    """
    from pu.identity.session import request_bound, session_principal
    from pu.identity.worker_job import current_grant

    grant = current_grant()
    if grant is not None:
        return Principal(PrincipalKind.WORKER, grant.owner_user_id, grant.workspace_id)
    principal = session_principal()
    if principal is not None:
        if principal.kind is PrincipalKind.PLATFORM_ADMIN:
            raise PermissionError("platform admin does not receive a private owner scope")
        return principal
    if request_bound():
        raise PermissionError("no authenticated principal")
    return ensure_local_principal(conn)


def workspace_count(conn: sqlite3.Connection, user_id: str) -> int:
    row = _raw(
        conn,
        "SELECT COUNT(*) FROM personal_workspaces WHERE owner_user_id = ?",
        (user_id,),
    ).fetchone()
    return int(row[0] if row else 0)

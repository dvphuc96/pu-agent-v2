"""Refuse another user's ids before a provider call.

Business agents may read only the rows the current principal owns. A
connection, thread, report, or workspace id that belongs to someone else
stops here. The provider is not called, and the error carries no private
content.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_ID_FIELDS = ("connection_id", "thread_id", "report_id", "workspace_id")


class ForeignResource(PermissionError):
    """The id belongs to another owner. No provider call follows."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _postgres(conn: object) -> bool:
    return type(conn).__module__.startswith("psycopg")


def foreign_code(
    conn: sqlite3.Connection,
    *,
    connection_id: str = "",
    thread_id: str = "",
    report_id: str = "",
    workspace_id: str = "",
    owner: str = "",
) -> str | None:
    """Return a denial code unless this owner can see the id.

    A foreign row hidden by row level security looks the same as a missing
    row. Both are refusals, and a database error is a refusal too. The
    error carries no private content. ``owner`` overrides the attached
    principal for a worker job.
    """
    from pu.identity.directory import current_principal

    owner = owner or current_principal(conn).user_id
    mark = "%s" if _postgres(conn) else "?"
    checks = (
        ("connection_denied", connection_id, "oauth_connections", "id"),
        ("thread_denied", thread_id, "crm_emails", "thread_id"),
        ("report_denied", report_id, "workspace_reports", "report_id"),
        ("workspace_denied", workspace_id, "research_workspaces", "id"),
    )
    for code, value, table, column in checks:
        token = str(value or "").strip()
        if not token:
            continue
        sql = (
            f"SELECT 1 FROM {table} WHERE {column}={mark} "
            f"AND owner_user_id={mark}"
        )
        try:
            row = conn.execute(sql, (token, owner)).fetchone()
        except PermissionError:
            raise
        except Exception:
            return code
        if row is None:
            return code
    return None


def refuse_before_provider(
    conn: sqlite3.Connection,
    *,
    connection_id: str = "",
    thread_id: str = "",
    report_id: str = "",
    workspace_id: str = "",
    thread_ids: list[str] | None = None,
    owner: str = "",
) -> None:
    """Raise when any of these ids belong to another owner."""
    code = foreign_code(
        conn,
        connection_id=connection_id,
        thread_id=thread_id,
        report_id=report_id,
        workspace_id=workspace_id,
        owner=owner,
    )
    if code:
        raise ForeignResource(code)
    for item in thread_ids or []:
        code = foreign_code(conn, thread_id=item, owner=owner)
        if code:
            raise ForeignResource(code)


def refuse_metadata(home: Path | str | None, metadata: dict | None) -> None:
    """Stop a business-agent turn that names another user's id.

    Missing a database is not a reason to call the provider anyway.
    """
    meta = metadata or {}
    if not any(str(meta.get(key) or "").strip() for key in _ID_FIELDS):
        return
    if not home:
        raise ForeignResource("foreign_resource")
    from pu.db import connect

    conn = connect(Path(home))
    try:
        refuse_before_provider(
            conn,
            connection_id=str(meta.get("connection_id") or ""),
            thread_id=str(meta.get("thread_id") or ""),
            report_id=str(meta.get("report_id") or ""),
            workspace_id=str(meta.get("workspace_id") or ""),
        )
    finally:
        conn.close()

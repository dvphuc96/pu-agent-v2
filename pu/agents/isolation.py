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


def foreign_code(
    conn: sqlite3.Connection,
    *,
    connection_id: str = "",
    thread_id: str = "",
    report_id: str = "",
    workspace_id: str = "",
    owner: str = "",
) -> str | None:
    """Return a denial code when an id is stored for a different owner.

    An id this owner holds, or an id that is not stored, is not a denial.
    The caller still has to refuse a stored foreign id before any provider.
    ``owner`` overrides the attached principal for a worker job.
    """
    from pu.identity.directory import current_principal

    owner = owner or current_principal(conn).user_id
    checks = (
        (
            "connection_denied",
            connection_id,
            "SELECT owner_user_id FROM oauth_connections WHERE id=?",
        ),
        (
            "thread_denied",
            thread_id,
            "SELECT owner_user_id FROM crm_emails WHERE thread_id=?",
        ),
        (
            "report_denied",
            report_id,
            "SELECT owner_user_id FROM workspace_reports WHERE report_id=?",
        ),
        (
            "workspace_denied",
            workspace_id,
            "SELECT owner_user_id FROM research_workspaces WHERE id=?",
        ),
    )
    for code, value, sql in checks:
        token = str(value or "").strip()
        if not token:
            continue
        try:
            rows = conn.execute(sql, (token,)).fetchall()
        except sqlite3.Error:
            continue
        owners = {row[0] for row in rows if row[0]}
        if owners and owner not in owners:
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

"""Ignore owner and workspace fields supplied by the client.

The server takes the owner from the attached principal. A ``workspace_id``
is honored only when that research workspace already belongs to the same
principal. Any other id is replaced by the caller's personal workspace, so
a body that names user B still writes and reads as user A.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from pu.identity.directory import current_principal, ensure_identity_tables

_IGNORED_FIELDS = ("owner_user_id", "owner", "user_id")


def discard_client_owner(payload: dict) -> dict:
    """Return a copy of ``payload`` without client-supplied owner fields."""
    cleaned = dict(payload)
    for field in _IGNORED_FIELDS:
        cleaned.pop(field, None)
    return cleaned


def coerce_workspace_id(conn: sqlite3.Connection, requested: str | None) -> str:
    """Map a client workspace id onto the current principal's own workspace.

    MU-12: an explicit id this owner does not hold is replaced by their
    personal workspace. It is not a 403. Agent and provider calls use
    ``refuse_before_provider`` and reject that same id before the model.
    """
    ensure_identity_tables(conn)
    principal = current_principal(conn)
    requested = (requested or "").strip()
    if requested:
        row = conn.execute(
            """SELECT id FROM research_workspaces
               WHERE id = ? AND owner_user_id = pu_current_owner()""",
            (requested,),
        ).fetchone()
        if row is not None:
            return row[0]
        if requested == principal.workspace_id:
            _ensure_personal_research_row(conn, principal.workspace_id, principal.user_id)
            return principal.workspace_id
    _ensure_personal_research_row(conn, principal.workspace_id, principal.user_id)
    return principal.workspace_id


def _ensure_personal_research_row(conn: sqlite3.Connection, workspace_id: str, owner: str) -> None:
    stamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    conn.execute(
        """INSERT OR IGNORE INTO research_workspaces(
               id, company, website, contact, created_at, updated_at, owner_user_id
           ) VALUES(?, 'Personal', '', '', ?, ?, ?)""",
        (workspace_id, stamp, stamp, owner),
    )

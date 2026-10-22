"""Import rows that still say ``local-user`` only with an explicit map.

A missing map rejects the whole batch. Rows are never assigned to a random
user, and a later row is not written when an earlier label has no mapping.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

from pu.persistence.ownership import OWNED_TABLES

LEGACY_LOCAL_USER = "local-user"


class LegacyImportRejected(Exception):
    """The batch was refused because the legacy-owner map is incomplete."""


def import_legacy_rows(
    conn: sqlite3.Connection,
    mapping: Mapping[str, str] | None,
    rows: Sequence[Mapping],
) -> int:
    """Insert ``rows`` under the user id named by ``mapping``.

    Each row is ``{"table", "legacy_owner", "values"}``. ``values`` is a
    column map for that table and must not include ``owner_user_id``; the
    mapped user id is the owner. The batch is validated before any insert.
    """
    mapping = dict(mapping or {})
    if not rows:
        return 0
    planned: list[tuple[str, str, dict]] = []
    for index, row in enumerate(rows):
        table = str(row.get("table") or "")
        label = str(row.get("legacy_owner") or "")
        values = row.get("values")
        if table not in OWNED_TABLES:
            raise LegacyImportRejected(f"row {index} names a table that is not a private table")
        if not isinstance(values, Mapping) or not values:
            raise LegacyImportRejected(f"row {index} has no column values")
        if "owner_user_id" in values:
            raise LegacyImportRejected(f"row {index} must not choose owner_user_id")
        if label not in mapping or not str(mapping[label]).strip():
            raise LegacyImportRejected(
                f"legacy owner {label!r} has no explicit user_id mapping; the batch was rejected"
            )
        user_id = str(mapping[label])
        exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if exists is None:
            raise LegacyImportRejected(
                f"mapped user_id for {label!r} is not a backend user; the batch was rejected"
            )
        planned.append((table, user_id, dict(values)))

    conn.execute("SAVEPOINT legacy_import")
    try:
        for table, user_id, values in planned:
            columns = list(values)
            columns.append("owner_user_id")
            placeholders = ", ".join("?" for _ in columns)
            quoted = ", ".join(columns)
            conn.execute(
                f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
                tuple(values[column] for column in values) + (user_id,),
            )
    except Exception:
        conn.execute("ROLLBACK TO legacy_import")
        conn.execute("RELEASE legacy_import")
        raise
    conn.execute("RELEASE legacy_import")
    return len(planned)

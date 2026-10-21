"""Stamp and resolve ``owner_user_id`` on SQLite connections.

Dev and test stay on SQLite, but inserts through this connection carry the
current principal. The seam wins when a test has attached one. Otherwise the
database-local principal is used so the existing single-user suite keeps
seeing the rows it writes.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence

from pu.identity.seam import attached_principal
from pu.persistence.ownership import OWNED_TABLES

# Raw sqlite3.Connection objects cannot store arbitrary attributes. Short-lived
# connections that are not OwnershipConnection keep their cache here.
_RAW_CACHE: dict[int, tuple[str, str]] = {}


def _remember(conn: sqlite3.Connection, user_id: str, workspace_id: str) -> None:
    try:
        conn._pu_local_owner = user_id  # type: ignore[attr-defined]
        conn._pu_local_workspace = workspace_id  # type: ignore[attr-defined]
    except AttributeError:
        _RAW_CACHE[id(conn)] = (user_id, workspace_id)


def _remembered_owner(conn: sqlite3.Connection) -> str:
    if hasattr(conn, "_pu_local_owner"):
        return conn._pu_local_owner or ""  # type: ignore[attr-defined]
    return _RAW_CACHE.get(id(conn), ("", ""))[0]


_INSERT = re.compile(
    r"""^\s*INSERT\s+(?:OR\s+(?:IGNORE|REPLACE|ABORT|FAIL|ROLLBACK)\s+)?INTO\s+
        (?P<table>"[^"]+"|`[^`]+`|\w+)\s*
        \((?P<cols>[^)]*)\)\s*VALUES\s*\(""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def load_local_owner_cache(conn: sqlite3.Connection) -> None:
    """Cache the database-local user id so SQL functions do not re-enter SQLite."""
    try:
        cursor = sqlite3.Connection.cursor(conn)
        row = cursor.execute(
            "SELECT user_id, workspace_id FROM identity_local WHERE singleton = 1"
        ).fetchone()
    except sqlite3.Error:
        _remember(conn, "", "")
        return
    if row is None:
        _remember(conn, "", "")
        return
    _remember(conn, row[0], row[1])


def current_owner_user_id(conn: sqlite3.Connection) -> str:
    attached = attached_principal()
    if attached is not None:
        return attached.user_id
    cached = _remembered_owner(conn)
    if cached:
        return cached
    load_local_owner_cache(conn)
    return _remembered_owner(conn)


def register_owner_function(conn: sqlite3.Connection) -> None:
    def pu_current_owner() -> str:
        return current_owner_user_id(conn)

    conn.create_function("pu_current_owner", 0, pu_current_owner, deterministic=False)


def stamp_sql(conn: sqlite3.Connection, sql: str, params):
    """Append ``owner_user_id`` to a named-column INSERT into a private table."""
    if not isinstance(sql, str):
        return sql, params
    match = _INSERT.match(sql)
    if match is None:
        return sql, params
    table = match.group("table").strip().strip('"').strip("`")
    if table not in OWNED_TABLES:
        return sql, params
    columns = [part.strip().strip('"').strip("`") for part in match.group("cols").split(",")]
    if "owner_user_id" in columns:
        return sql, params
    owner = current_owner_user_id(conn)
    if not owner:
        return sql, params
    new_cols = match.group("cols").rstrip() + ", owner_user_id"
    rest_at = match.end()
    depth = 1
    index = rest_at
    while index < len(sql) and depth:
        char = sql[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    close = index - 1
    placeholder = ":owner_user_id" if isinstance(params, Mapping) else "?"
    values_body = sql[rest_at:close]
    prefix = sql[: match.start("cols")] + new_cols + sql[match.end("cols") : rest_at]
    suffix = sql[close:]
    joiner = ", " if values_body.strip() else ""
    rewritten = prefix + values_body + joiner + placeholder + suffix
    return rewritten, _with_owner(params, owner)


def stamp_many(conn: sqlite3.Connection, sql: str, seq: Iterable):
    rows = list(seq)
    if not rows:
        return sql, rows
    rewritten, _sample = stamp_sql(conn, sql, rows[0])
    if rewritten == sql:
        return sql, rows
    owner = current_owner_user_id(conn)
    return rewritten, [_with_owner(row, owner) for row in rows]


def _with_owner(params, owner: str):
    if isinstance(params, Mapping):
        copied = dict(params)
        copied["owner_user_id"] = owner
        return copied
    if isinstance(params, tuple):
        return params + (owner,)
    if isinstance(params, list):
        return [*params, owner]
    if isinstance(params, Sequence) and not isinstance(params, (str, bytes)):
        return tuple(params) + (owner,)
    return params


class OwnershipCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        sql, parameters = stamp_sql(self.connection, sql, parameters)
        return super().execute(sql, parameters)

    def executemany(self, sql, seq):
        sql, seq = stamp_many(self.connection, sql, seq)
        return super().executemany(sql, seq)


class OwnershipConnection(sqlite3.Connection):
    def cursor(self, factory=None):
        if factory is None:
            return super().cursor(OwnershipCursor)
        return super().cursor(factory)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, seq):
        return self.cursor().executemany(sql, seq)

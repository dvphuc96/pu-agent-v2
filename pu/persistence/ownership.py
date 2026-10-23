"""Add ``owner_user_id`` and composite foreign keys to private SQLite tables.

Fresh databases and databases created before Phase 1 both go through this
migration. SQLite has no row level security; the columns, composite foreign
keys, and the connection stamp are the ownership boundary for dev and test.
PostgreSQL enforces the same columns with RLS.
"""

from __future__ import annotations

import re
import sqlite3

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

OWNED_TABLES = frozenset(
    {
        "calendar_events",
        "facts",
        "episodes",
        "chat_log",
        "crm_emails",
        "knowledge_sources",
        "knowledge_chunks",
        "proposed_actions",
        "workflow_runs",
        "workflow_stage_checkpoints",
        "agent_events",
        "tool_audit_events",
        "research_workspaces",
        "workspace_sources",
        "workspace_reports",
        "workspace_messages",
        "workspace_deliveries",
        "briefing_state",
        "briefing_seen",
        "briefing_jobs",
    }
)

_FACTS_FTS_TRIGGERS = """
CREATE TRIGGER facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, subject, content, owner_user_id)
    VALUES (new.id, new.subject, new.content, new.owner_user_id);
END;
CREATE TRIGGER facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, content, owner_user_id)
    VALUES ('delete', old.id, old.subject, old.content, old.owner_user_id);
END;
CREATE TRIGGER facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, content, owner_user_id)
    VALUES ('delete', old.id, old.subject, old.content, old.owner_user_id);
    INSERT INTO facts_fts(rowid, subject, content, owner_user_id)
    VALUES (new.id, new.subject, new.content, new.owner_user_id);
END;
"""

_EPISODES_FTS_TRIGGERS = """
CREATE TRIGGER episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, summary, owner_user_id)
    VALUES (new.id, new.summary, new.owner_user_id);
END;
CREATE TRIGGER episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, owner_user_id)
    VALUES ('delete', old.id, old.summary, old.owner_user_id);
END;
CREATE TRIGGER episodes_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, summary, owner_user_id)
    VALUES ('delete', old.id, old.summary, old.owner_user_id);
    INSERT INTO episodes_fts(rowid, summary, owner_user_id)
    VALUES (new.id, new.summary, new.owner_user_id);
END;
"""

_KNOWLEDGE_FTS_TRIGGERS = """
CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(rowid, content, owner_user_id)
    VALUES (new.id, new.content, new.owner_user_id);
END;
CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, owner_user_id)
    VALUES ('delete', old.id, old.content, old.owner_user_id);
END;
CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge_chunks BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, owner_user_id)
    VALUES ('delete', old.id, old.content, old.owner_user_id);
    INSERT INTO knowledge_fts(rowid, content, owner_user_id)
    VALUES (new.id, new.content, new.owner_user_id);
END;
"""


def apply_ownership_migration(conn: sqlite3.Connection) -> None:
    from pu.identity.directory import ensure_local_principal

    # A crash between rename and drop leaves ``table__pre_owner``. Restore that
    # backup before any "already migrated" check, or the copy is skipped and
    # version 9005 would still be recorded.
    _resume_interrupted(conn)
    conn.commit()
    principal = ensure_local_principal(conn)
    owner = principal.user_id
    for table in sorted(OWNED_TABLES):
        _add_owner_column(conn, table)
    for table in sorted(OWNED_TABLES):
        _backfill_owner(conn, table, owner)
    _unique_owner_key(conn, "workflow_runs", "id")
    _unique_owner_key(conn, "research_workspaces", "id")
    _unique_owner_key(conn, "knowledge_sources", "id")
    _unique_owner_key(conn, "workspace_reports", "report_id")
    _rebuild_checkpoints(conn)
    _rebuild_workspace_children(conn)
    _rebuild_briefing_identity(conn)
    _rebuild_crm_emails(conn)
    _rebuild_knowledge_chunks(conn)
    _upgrade_fts(
        conn,
        "facts_fts",
        "facts",
        ("subject", "content", "owner_user_id"),
        _FACTS_FTS_TRIGGERS,
    )
    _upgrade_fts(
        conn,
        "episodes_fts",
        "episodes",
        ("summary", "owner_user_id"),
        _EPISODES_FTS_TRIGGERS,
    )
    _upgrade_fts(
        conn,
        "knowledge_fts",
        "knowledge_chunks",
        ("content", "owner_user_id"),
        _KNOWLEDGE_FTS_TRIGGERS,
    )
    _owner_match_triggers(conn)
    if _exists(conn, "agent_events"):
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_agent_events_workflow_owner
               ON agent_events(workflow_id, owner_user_id)"""
        )
    _assert_no_backups(conn)
    conn._pu_local_owner = owner  # type: ignore[attr-defined]
    conn._pu_local_workspace = principal.workspace_id  # type: ignore[attr-defined]


def _exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (name,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _add_owner_column(conn: sqlite3.Connection, table: str) -> None:
    if not _exists(conn, table) or _is_virtual(conn, table):
        return
    if "owner_user_id" in _columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''")


def reject_empty_owner_user_id(conn: sqlite3.Connection) -> None:
    """Backfill leftover blank owners, then refuse new blank writes.

    SQLite cannot add a CHECK to an existing column without rebuilding the
    table. A BEFORE INSERT/UPDATE trigger is the feasible guard. Virtual
    FTS tables keep the owner copied from their content table.
    """
    from pu.identity.directory import ensure_local_principal

    owner = ensure_local_principal(conn).user_id
    for table in sorted(OWNED_TABLES):
        _backfill_owner(conn, table, owner)
    for table in sorted(OWNED_TABLES):
        if not _exists(conn, table) or _is_virtual(conn, table):
            continue
        if "owner_user_id" not in _columns(conn, table):
            continue
        for event, suffix in (("INSERT", "ins"), ("UPDATE", "upd")):
            name = f"{table}_owner_nonempty_{suffix}"
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            conn.execute(
                f"""CREATE TRIGGER {name}
                    BEFORE {event} ON {table}
                    WHEN NEW.owner_user_id IS NULL OR NEW.owner_user_id = ''
                    BEGIN
                        SELECT RAISE(ABORT, 'owner_user_id is required');
                    END"""
            )


def _backfill_owner(conn: sqlite3.Connection, table: str, owner: str) -> None:
    if not _exists(conn, table) or _is_virtual(conn, table):
        return
    if "owner_user_id" not in _columns(conn, table):
        return
    conn.execute(
        f"UPDATE {table} SET owner_user_id = ? WHERE owner_user_id = ''",
        (owner,),
    )


def _is_virtual(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
    return bool(row and row[0] and "VIRTUAL" in row[0].upper())


def _unique_owner_key(conn: sqlite3.Connection, table: str, key: str) -> None:
    if not _exists(conn, table) or "owner_user_id" not in _columns(conn, table):
        return
    conn.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_{key}_owner ON {table}({key}, owner_user_id)"
    )


def _pk(conn: sqlite3.Connection, table: str) -> list[str]:
    ranked = sorted(
        (row[5], row[1]) for row in conn.execute(f"PRAGMA table_info({table})") if row[5]
    )
    return [name for _, name in ranked]


def _backup_name(table: str) -> str:
    return f"{table}__pre_owner"


def _count(conn: sqlite3.Connection, table: str) -> int:
    if not _IDENT.fullmatch(table):
        raise RuntimeError(f"refusing to touch a non-identifier table name: {table}")
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _resume_interrupted(conn: sqlite3.Connection) -> None:
    """Put a half-rebuilt table back so the normal rebuild copies every row.

    SQLite DDL cannot stay in one transaction across ``PRAGMA foreign_keys``.
    Resuming from the backup is the crash boundary: a live table that is
    missing or shorter than its backup is discarded, and a finished copy drops
    the backup. A leftover backup means version 9005 must not be recorded.
    """
    backups = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%__pre_owner'"
        )
    ]
    if not backups:
        return
    _fk_off(conn)
    try:
        for backup in backups:
            if not backup.endswith("__pre_owner"):
                continue
            live = backup[: -len("__pre_owner")]
            if not _IDENT.fullmatch(live):
                raise RuntimeError(f"unexpected ownership backup {backup}")
            backup_count = _count(conn, backup)
            if not _exists(conn, live):
                conn.execute(f"ALTER TABLE {backup} RENAME TO {live}")
                continue
            live_count = _count(conn, live)
            if live_count < backup_count:
                conn.execute(f"DROP TABLE {live}")
                conn.execute(f"ALTER TABLE {backup} RENAME TO {live}")
            elif live_count == backup_count:
                conn.execute(f"DROP TABLE {backup}")
            else:
                raise RuntimeError(
                    f"{live} has {live_count} rows but backup {backup} has {backup_count}; "
                    "ownership migration will not record a version"
                )
    finally:
        _fk_on(conn)


def _assert_no_backups(conn: sqlite3.Connection) -> None:
    leftover = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%__pre_owner'"
        )
    ]
    if leftover:
        raise RuntimeError(
            "ownership migration left backups and will not record version 9005: "
            + ", ".join(leftover)
        )


def _has_fk(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    ref_table: str,
    ref_columns: tuple[str, ...],
) -> bool:
    if _exists(conn, _backup_name(table)):
        return False
    if not _exists(conn, table):
        return False
    groups: dict[int, list[tuple[int, str, str, str]]] = {}
    for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
        groups.setdefault(row[0], []).append((row[1], row[3], row[2], row[4]))
    expected = list(zip(columns, [ref_table] * len(columns), ref_columns))
    for pairs in groups.values():
        ordered = [(src, parent, dst) for _, src, parent, dst in sorted(pairs)]
        if ordered == expected:
            return True
    return False


def _fk_off(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")


def _fk_on(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")


def _rebuild(conn: sqlite3.Connection, table: str, create_sql: str, columns: list[str]) -> None:
    if not _IDENT.fullmatch(table):
        raise RuntimeError(f"refusing to rebuild a non-identifier table name: {table}")
    backup = _backup_name(table)
    if not _exists(conn, table):
        if _exists(conn, backup):
            _fk_off(conn)
            conn.execute(f"ALTER TABLE {backup} RENAME TO {table}")
            _fk_on(conn)
        else:
            conn.execute(create_sql)
            return
    present = _columns(conn, table)
    copied = [column for column in columns if column in present]
    _fk_off(conn)
    conn.execute(f"ALTER TABLE {table} RENAME TO {backup}")
    conn.execute(create_sql)
    if copied:
        quoted = ", ".join(copied)
        conn.execute(f"INSERT INTO {table}({quoted}) SELECT {quoted} FROM {backup}")
    source = _count(conn, backup)
    copied_count = _count(conn, table)
    if copied_count != source:
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {backup} RENAME TO {table}")
        _fk_on(conn)
        raise RuntimeError(
            f"{table} rebuild copied {copied_count} of {source} rows; backup restored"
        )
    conn.execute(f"DROP TABLE {backup}")
    _fk_on(conn)


def _rebuild_checkpoints(conn: sqlite3.Connection) -> None:
    if _has_fk(
        conn,
        "workflow_stage_checkpoints",
        ("workflow_id", "owner_user_id"),
        "workflow_runs",
        ("id", "owner_user_id"),
    ) and _pk(conn, "workflow_stage_checkpoints") == [
        "workflow_id",
        "owner_user_id",
        "stage_name",
    ]:
        return
    _drop_triggers(conn, "workflow_stage_checkpoints")
    _rebuild(
        conn,
        "workflow_stage_checkpoints",
        """CREATE TABLE workflow_stage_checkpoints (
            workflow_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL DEFAULT '',
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workflow_id, owner_user_id, stage_name),
            FOREIGN KEY(workflow_id, owner_user_id)
                REFERENCES workflow_runs(id, owner_user_id) ON DELETE CASCADE
        )""",
        [
            "workflow_id",
            "owner_user_id",
            "stage_name",
            "status",
            "result_json",
            "error",
            "updated_at",
        ],
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_workflow_checkpoints_status
           ON workflow_stage_checkpoints(status, updated_at DESC)"""
    )


def _rebuild_workspace_children(conn: sqlite3.Connection) -> None:
    if not _has_fk(
        conn,
        "workspace_sources",
        ("workspace_id", "owner_user_id"),
        "research_workspaces",
        ("id", "owner_user_id"),
    ):
        _drop_triggers(conn, "workspace_sources")
        _rebuild(
            conn,
            "workspace_sources",
            """CREATE TABLE workspace_sources (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                fingerprint TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(workspace_id, fingerprint),
                FOREIGN KEY(workspace_id, owner_user_id)
                    REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE
            )""",
            [
                "id",
                "workspace_id",
                "owner_user_id",
                "title",
                "source_type",
                "content",
                "url",
                "published_at",
                "enabled",
                "fingerprint",
                "metadata_json",
                "created_at",
            ],
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_workspace_sources
               ON workspace_sources(workspace_id, created_at)"""
        )
    if not _has_fk(
        conn,
        "workspace_reports",
        ("workspace_id", "owner_user_id"),
        "research_workspaces",
        ("id", "owner_user_id"),
    ):
        _drop_triggers(conn, "workspace_reports")
        _rebuild(
            conn,
            "workspace_reports",
            """CREATE TABLE workspace_reports (
                report_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source_map_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(report_id, owner_user_id),
                FOREIGN KEY(workspace_id, owner_user_id)
                    REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE
            )""",
            [
                "report_id",
                "workspace_id",
                "owner_user_id",
                "content_hash",
                "payload_json",
                "source_map_json",
                "created_at",
            ],
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_workspace_reports
               ON workspace_reports(workspace_id, created_at DESC)"""
        )
    if not _has_fk(
        conn,
        "workspace_messages",
        ("workspace_id", "owner_user_id"),
        "research_workspaces",
        ("id", "owner_user_id"),
    ):
        _drop_triggers(conn, "workspace_messages")
        _rebuild(
            conn,
            "workspace_messages",
            """CREATE TABLE workspace_messages (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL DEFAULT '',
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id, owner_user_id)
                    REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE
            )""",
            [
                "id",
                "workspace_id",
                "owner_user_id",
                "question",
                "answer",
                "source_ids_json",
                "created_at",
            ],
        )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_workspace_messages
               ON workspace_messages(workspace_id, created_at)"""
        )
    if not _has_fk(
        conn,
        "workspace_deliveries",
        ("report_id", "owner_user_id"),
        "workspace_reports",
        ("report_id", "owner_user_id"),
    ):
        _drop_triggers(conn, "workspace_deliveries")
        _rebuild(
            conn,
            "workspace_deliveries",
            """CREATE TABLE workspace_deliveries (
                action_hash TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL DEFAULT '',
                report_id TEXT NOT NULL,
                destination TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id, owner_user_id)
                    REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE,
                FOREIGN KEY(report_id, owner_user_id)
                    REFERENCES workspace_reports(report_id, owner_user_id)
            )""",
            [
                "action_hash",
                "workspace_id",
                "owner_user_id",
                "report_id",
                "destination",
                "result_json",
                "created_at",
            ],
        )
    if not _has_fk(
        conn,
        "briefing_jobs",
        ("workspace_id", "owner_user_id"),
        "research_workspaces",
        ("id", "owner_user_id"),
    ):
        _drop_triggers(conn, "briefing_jobs")
        _rebuild(conn, "briefing_jobs", _BRIEFING_JOBS_CREATE, _BRIEFING_JOBS_COLUMNS)
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_briefing_jobs_status
               ON briefing_jobs(status, created_at)"""
        )


_BRIEFING_JOBS_CREATE = """CREATE TABLE briefing_jobs (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    workflow_id TEXT,
    report_id TEXT,
    email_ids_json TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt TEXT NOT NULL DEFAULT '',
    UNIQUE(fingerprint, owner_user_id),
    FOREIGN KEY(workspace_id, owner_user_id)
        REFERENCES research_workspaces(id, owner_user_id)
)"""

_BRIEFING_JOBS_COLUMNS = [
    "id",
    "fingerprint",
    "workspace_id",
    "owner_user_id",
    "status",
    "stage",
    "workflow_id",
    "report_id",
    "email_ids_json",
    "error",
    "created_at",
    "updated_at",
    "attempts",
    "next_attempt",
]


def scope_briefing_fingerprint(conn: sqlite3.Connection) -> None:
    """Allow the same briefing fingerprint for two owners.

    Databases that already applied the global UNIQUE constraint are rebuilt.
    A table that already has ``UNIQUE(fingerprint, owner_user_id)`` is left
    as it is.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'briefing_jobs'"
    ).fetchone()
    if row is None or not row[0]:
        return
    normalized = "".join(row[0].split()).lower()
    if "unique(fingerprint,owner_user_id)" in normalized:
        return
    _drop_triggers(conn, "briefing_jobs")
    _rebuild(conn, "briefing_jobs", _BRIEFING_JOBS_CREATE, _BRIEFING_JOBS_COLUMNS)
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_briefing_jobs_status
           ON briefing_jobs(status, created_at)"""
    )


def _needs_pk(conn: sqlite3.Connection, table: str, expected: list[str]) -> bool:
    if _exists(conn, _backup_name(table)):
        return True
    return _exists(conn, table) and _pk(conn, table) != expected


def _rebuild_briefing_identity(conn: sqlite3.Connection) -> None:
    if _needs_pk(conn, "briefing_state", ["key", "owner_user_id"]):
        _drop_triggers(conn, "briefing_state")
        _rebuild(
            conn,
            "briefing_state",
            """CREATE TABLE briefing_state (
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                owner_user_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(key, owner_user_id)
            )""",
            ["key", "value", "owner_user_id"],
        )
    if _needs_pk(conn, "briefing_seen", ["gmail_id", "owner_user_id"]):
        _drop_triggers(conn, "briefing_seen")
        _rebuild(
            conn,
            "briefing_seen",
            """CREATE TABLE briefing_seen (
                gmail_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL,
                reason TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY(gmail_id, owner_user_id)
            )""",
            ["gmail_id", "owner_user_id", "domain", "reason", "seen_at"],
        )


def _rebuild_crm_emails(conn: sqlite3.Connection) -> None:
    """Match the Postgres primary key ``(gmail_id, owner_user_id)``."""
    if not _needs_pk(conn, "crm_emails", ["gmail_id", "owner_user_id"]):
        return
    _drop_triggers(conn, "crm_emails")
    _rebuild(
        conn,
        "crm_emails",
        """CREATE TABLE crm_emails (
            gmail_id TEXT NOT NULL,
            thread_id TEXT DEFAULT '',
            sender_name TEXT DEFAULT '',
            sender_email TEXT DEFAULT '',
            subject TEXT DEFAULT '',
            snippet TEXT DEFAULT '',
            body_text TEXT DEFAULT '',
            internal_date TEXT NOT NULL,
            unread INTEGER DEFAULT 1,
            synced_at TEXT DEFAULT (datetime('now')),
            owner_user_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(gmail_id, owner_user_id)
        )""",
        [
            "gmail_id",
            "thread_id",
            "sender_name",
            "sender_email",
            "subject",
            "snippet",
            "body_text",
            "internal_date",
            "unread",
            "synced_at",
            "owner_user_id",
        ],
    )


def _rebuild_knowledge_chunks(conn: sqlite3.Connection) -> None:
    if not _exists(conn, "knowledge_chunks"):
        return
    if _has_fk(
        conn,
        "knowledge_chunks",
        ("source_id", "owner_user_id"),
        "knowledge_sources",
        ("id", "owner_user_id"),
    ):
        return
    _drop_triggers(conn, "knowledge_chunks")
    if _exists(conn, "knowledge_fts"):
        conn.execute("DROP TABLE IF EXISTS knowledge_fts")
    _rebuild(
        conn,
        "knowledge_chunks",
        """CREATE TABLE knowledge_chunks (
            id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL,
            owner_user_id TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            FOREIGN KEY(source_id, owner_user_id)
                REFERENCES knowledge_sources(id, owner_user_id) ON DELETE CASCADE
        )""",
        ["id", "source_id", "owner_user_id", "content"],
    )


def _drop_triggers(conn: sqlite3.Connection, table: str) -> None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
        (table,),
    ).fetchall()
    for (name,) in rows:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")


def _trigger_names(trigger_sql: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(
            r"CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            trigger_sql,
            re.IGNORECASE,
        )
    }


def _upgrade_fts(
    conn: sqlite3.Connection,
    fts_name: str,
    content: str,
    columns: tuple[str, ...],
    trigger_sql: str,
) -> None:
    if not _exists(conn, content):
        return
    expected = _trigger_names(trigger_sql)
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (fts_name,)).fetchone()
    sql = row[0] if row and row[0] else ""
    present = {
        name
        for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
            (content,),
        )
    }
    # External-content FTS5 COUNT(*) follows the content table, so an index
    # that was never rebuilt still looks full. The docsize shadow counts
    # indexed rows.
    indexed = -1
    docsize = f"{fts_name}_docsize"
    if _exists(conn, fts_name) and _exists(conn, docsize):
        try:
            indexed = _count(conn, docsize)
        except sqlite3.Error:
            indexed = -1
    if (
        "owner_user_id" in sql
        and expected <= present
        and indexed == _count(conn, content)
    ):
        return
    _drop_triggers(conn, content)
    conn.execute(f"DROP TABLE IF EXISTS {fts_name}")
    rendered = []
    for column in columns:
        if column == "owner_user_id":
            rendered.append("owner_user_id UNINDEXED")
        else:
            rendered.append(column)
    conn.execute(
        f"CREATE VIRTUAL TABLE {fts_name} USING fts5("
        + ", ".join(rendered)
        + f", content={content}, content_rowid=id)"
    )
    conn.executescript(trigger_sql)
    conn.execute(f"INSERT INTO {fts_name}({fts_name}) VALUES('rebuild')")


# Bump the suffix when the trigger body changes. CREATE IF NOT EXISTS will
# not replace an existing body, so a new name is the install.
_OWNER_MATCH_VERSION = "v1"


def install_owner_match_triggers(conn: sqlite3.Connection) -> None:
    """Install workflow owner-match triggers once.

    ``CREATE TRIGGER IF NOT EXISTS`` is safe when several connections migrate
    or open the database together. Dropping and recreating the same name on
    every ``connect()`` races: DDL commits implicitly, and the second CREATE
    then fails with ``trigger already exists``.
    """
    _owner_match_triggers(conn)
    _install_episodes_update_trigger(conn)


def _install_episodes_update_trigger(conn: sqlite3.Connection) -> None:
    if not _exists(conn, "episodes") or not _exists(conn, "episodes_fts"):
        return
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
               INSERT INTO episodes_fts(episodes_fts, rowid, summary, owner_user_id)
               VALUES ('delete', old.id, old.summary, old.owner_user_id);
               INSERT INTO episodes_fts(rowid, summary, owner_user_id)
               VALUES (new.id, new.summary, new.owner_user_id);
           END"""
    )


def _owner_match_triggers(conn: sqlite3.Connection) -> None:
    statements = (
        (
            "agent_events",
            "workflow_id",
            "agent_events workflow_id must reference workflow_runs for the same owner",
        ),
        (
            "tool_audit_events",
            "workflow_id",
            "tool_audit_events workflow_id must reference workflow_runs for the same owner",
        ),
        (
            "proposed_actions",
            "workflow_id",
            "proposed_actions workflow_id must reference workflow_runs for the same owner",
        ),
    )
    for table, column, message in statements:
        if not _exists(conn, table):
            continue
        for timing in ("INSERT", "UPDATE"):
            legacy = f"{table}_owner_match_{timing.lower()}"
            name = f"{legacy}_{_OWNER_MATCH_VERSION}"
            conn.execute(
                f"""CREATE TRIGGER IF NOT EXISTS {name}
                    BEFORE {timing} ON {table}
                    FOR EACH ROW
                    WHEN NEW.{column} IS NOT NULL AND NOT EXISTS (
                        SELECT 1 FROM workflow_runs
                        WHERE id = NEW.{column} AND owner_user_id = NEW.owner_user_id
                    )
                    BEGIN
                        SELECT RAISE(ABORT, '{message}');
                    END"""
            )
            if legacy != name:
                conn.execute(f"DROP TRIGGER IF EXISTS {legacy}")

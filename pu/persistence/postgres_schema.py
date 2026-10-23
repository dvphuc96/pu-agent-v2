"""PostgreSQL production schema for private data.

SQLite remains the dev/test adapter. Production enables row level security
and forces it for the table owner. Production connections must log in as
``pu_app`` (NOSUPERUSER, NOBYPASSRLS). A superuser connection bypasses row
level security even when FORCE is set, so a production DSN must not use a
superuser or any role with BYPASSRLS. The session variable
``pu.owner_user_id`` is the only owner the policies accept.
"""

from __future__ import annotations

SCHEMA = "pu_phase1"

PRIVATE_TABLES = (
    "personal_workspaces",
    "private_files",
    "calendar_events",
    "facts",
    "facts_fts",
    "episodes",
    "episodes_fts",
    "chat_log",
    "crm_emails",
    "knowledge_sources",
    "knowledge_chunks",
    "knowledge_fts",
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
)

# Natural text column used by the MU-07 fixture to prove a row is hidden.
MARKER_COLUMN = {
    "personal_workspaces": "id",
    "private_files": "relative_path",
    "calendar_events": "title",
    "facts": "content",
    "facts_fts": "content",
    "episodes": "summary",
    "episodes_fts": "summary",
    "chat_log": "content",
    "crm_emails": "subject",
    "knowledge_sources": "title",
    "knowledge_chunks": "content",
    "knowledge_fts": "content",
    "proposed_actions": "id",
    "workflow_runs": "id",
    "workflow_stage_checkpoints": "stage_name",
    "agent_events": "id",
    "tool_audit_events": "execution_id",
    "research_workspaces": "company",
    "workspace_sources": "content",
    "workspace_reports": "report_id",
    "workspace_messages": "answer",
    "workspace_deliveries": "destination",
    "briefing_state": "value",
    "briefing_seen": "reason",
    "briefing_jobs": "id",
}

_DDL = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE personal_workspaces (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE private_files (
    relative_path TEXT NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (relative_path, owner_user_id)
);
CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workflow_type TEXT NOT NULL DEFAULT 'morning_research',
    status TEXT NOT NULL DEFAULT 'running',
    request_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (id, owner_user_id)
);
CREATE TABLE workflow_stage_checkpoints (
    workflow_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    result_json TEXT,
    updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (workflow_id, owner_user_id, stage_name),
    FOREIGN KEY (workflow_id, owner_user_id)
        REFERENCES workflow_runs(id, owner_user_id) ON DELETE CASCADE
);
CREATE TABLE agent_events (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workflow_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (workflow_id, owner_user_id)
        REFERENCES workflow_runs(id, owner_user_id)
);
CREATE TABLE tool_audit_events (
    id BIGSERIAL PRIMARY KEY,
    execution_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    workflow_id TEXT,
    record_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (workflow_id, owner_user_id)
        REFERENCES workflow_runs(id, owner_user_id)
);
CREATE TABLE research_workspaces (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    UNIQUE (id, owner_user_id)
);
CREATE TABLE workspace_sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE
);
CREATE TABLE workspace_reports (
    report_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (report_id, owner_user_id),
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE
);
CREATE TABLE workspace_messages (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE
);
CREATE TABLE workspace_deliveries (
    action_hash TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    destination TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES research_workspaces(id, owner_user_id) ON DELETE CASCADE,
    FOREIGN KEY (report_id, owner_user_id)
        REFERENCES workspace_reports(report_id, owner_user_id)
);
CREATE TABLE knowledge_sources (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    UNIQUE (id, owner_user_id)
);
CREATE TABLE knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL,
    owner_user_id TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (source_id, owner_user_id)
        REFERENCES knowledge_sources(id, owner_user_id) ON DELETE CASCADE
);
CREATE TABLE knowledge_fts (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT ''
);
CREATE TABLE facts (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT ''
);
CREATE TABLE facts_fts (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT ''
);
CREATE TABLE episodes (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE episodes_fts (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE chat_log (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT ''
);
CREATE TABLE crm_emails (
    gmail_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (gmail_id, owner_user_id)
);
CREATE TABLE calendar_events (
    id BIGSERIAL PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT ''
);
CREATE TABLE proposed_actions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workflow_id TEXT,
    FOREIGN KEY (workflow_id, owner_user_id)
        REFERENCES workflow_runs(id, owner_user_id)
);
CREATE TABLE briefing_state (
    key TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (key, owner_user_id)
);
CREATE TABLE briefing_seen (
    gmail_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (gmail_id, owner_user_id)
);
CREATE TABLE briefing_jobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    FOREIGN KEY (workspace_id, owner_user_id)
        REFERENCES research_workspaces(id, owner_user_id)
);
"""


def _schema_private_rows(conn) -> int | None:
    """Row count in an existing schema, or None when the schema is absent.

    Table names come from ``information_schema`` and are restricted to simple
    identifiers before they are interpolated.
    """
    import re

    found = conn.execute(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
        (SCHEMA,),
    ).fetchone()
    if not found:
        return None
    tables = conn.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = %s AND table_type = 'BASE TABLE'""",
        (SCHEMA,),
    ).fetchall()
    total = 0
    for (table,) in tables:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(table)):
            continue
        total += int(
            conn.execute(f'SELECT COUNT(*) FROM "{SCHEMA}"."{table}"').fetchone()[0]
        )
    return total


def install(
    conn,
    *,
    role: str = "pu_app",
    password: str | None = None,
    replace_existing: bool = False,
) -> None:
    """Create the phase-1 schema and make ``role`` subject to forced RLS.

    Production must connect as this role (``pu_app`` by default). There is no
    default password. ``DROP SCHEMA`` runs only for an empty schema, or when
    ``replace_existing`` is set for a fixture. A schema that already holds
    rows is left in place.

    ``CREATE ROLE`` cannot run inside a transaction block, so this switches the
    connection to autocommit for the duration of the install and restores the
    previous mode afterwards.
    """
    from psycopg import errors, sql

    if not password:
        raise ValueError("password is required; there is no default database password")
    if not role.replace("_", "").isalnum():
        raise ValueError("role must be a simple SQL identifier")
    previous_autocommit = getattr(conn, "autocommit", None)
    if previous_autocommit is False:
        conn.autocommit = True
    try:
        existing = _schema_private_rows(conn)
        if existing and not replace_existing:
            raise RuntimeError(
                f"refusing to DROP SCHEMA {SCHEMA}: it already contains {existing} rows"
            )
        if existing is not None:
            conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        conn.execute(f"SET search_path TO {SCHEMA}")
        for statement in _DDL.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(statement)
        for table in PRIVATE_TABLES:
            conn.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {table}_owner_nonempty "
                "CHECK (owner_user_id <> '')"
            )
            conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            conn.execute(
                f"""CREATE POLICY pu_owner_isolation ON {table}
                    USING (owner_user_id = current_setting('pu.owner_user_id', true))
                    WITH CHECK (owner_user_id = current_setting('pu.owner_user_id', true))"""
            )
        # ``users`` is keyed by id, not owner_user_id, so it stays out of
        # PRIVATE_TABLES. A caller may see only their own user row.
        conn.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
        conn.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
        conn.execute(
            """CREATE POLICY pu_user_self ON users
               USING (id = current_setting('pu.owner_user_id', true))
               WITH CHECK (id = current_setting('pu.owner_user_id', true))"""
        )
        try:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} "
                    "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
        except errors.DuplicateObject:
            conn.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                    "NOCREATEROLE LOGIN PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
            sql.Identifier(SCHEMA), sql.Identifier(role)
        ))
        conn.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(sql.Identifier(SCHEMA), sql.Identifier(role))
        )
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                sql.Identifier(SCHEMA), sql.Identifier(role)
            )
        )
        conn.execute(
            sql.SQL("ALTER ROLE {} SET search_path TO {}").format(
                sql.Identifier(role), sql.Identifier(SCHEMA)
            )
        )
    finally:
        if previous_autocommit is False:
            conn.autocommit = previous_autocommit


def set_owner(conn, owner_user_id: str) -> None:
    conn.execute("SELECT set_config('pu.owner_user_id', %s, true)", (owner_user_id,))

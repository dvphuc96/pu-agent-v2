"""WORKER reads for Gmail, calendar, and public pages.

An application tool harness, when one is bound or passed in, is the only
call. ``BoundaryHarness`` covers the same boundary when the process has no
application yet: the provider or file read runs inside ``execute``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import datetime
from pathlib import Path
from typing import Any

from pu.core.interfaces.tools import ToolContext, ToolResult
from pu.identity.principal import PrincipalKind

_BOUND: ContextVar[Any] = ContextVar("pu_bound_read_harness", default=None)
_EXECUTING: ContextVar[bool] = ContextVar("pu_harness_execute", default=False)

READ_SCOPES = {
    "read_web_page": "web:read",
    "search_web": "web:read",
    "list_events": "calendar:read",
    "read_week_availability": "calendar:read",
    "read_gmail_today": "email:read",
    "read_email_inbox": "email:read",
    "search_gmail": "email:read",
    "read_gmail_thread": "email:read",
}


def bind_harness(harness: Any) -> Token:
    return _BOUND.set(harness)


def reset_bound_harness(token: Token) -> None:
    _BOUND.reset(token)


def clear_bound_harness() -> None:
    _BOUND.set(None)


def bound_harness() -> Any:
    return _BOUND.get()


def harness_execute_active() -> bool:
    """True while a worker read is inside ``Harness.execute``."""
    return _EXECUTING.get()


def external_harness(app: Any = None) -> Any:
    bound = _BOUND.get()
    if bound is not None:
        return bound
    if app is None:
        return None
    return getattr(app, "tool_harness", None)


def read_harness(app: Any, producer: Callable[..., Any]) -> Any:
    """Return a harness. There is no direct-call fallback.

    A bound harness or the application's tool harness wins. Otherwise the
    provider read runs inside ``BoundaryHarness.execute``.
    """
    found = external_harness(app)
    if found is not None:
        return found
    return BoundaryHarness(producer)


def job_owner(home: Path | None) -> tuple[str, str]:
    from pu.identity.principal import PrincipalKind
    from pu.identity.session import request_bound, session_principal
    from pu.identity.worker_job import current_grant

    try:
        grant = current_grant()
    except PermissionError:
        return "", ""
    if grant is not None:
        return grant.owner_user_id, grant.workspace_id
    principal = session_principal()
    if principal is not None:
        if principal.kind is PrincipalKind.PLATFORM_ADMIN:
            return "", ""
        return principal.user_id, principal.workspace_id
    if request_bound() or home is None:
        return "", ""
    database = Path(home) / "state.db"
    if not database.is_file():
        return "", ""
    conn = sqlite3.connect(database)
    try:
        row = conn.execute(
            "SELECT user_id, workspace_id FROM identity_local WHERE singleton = 1"
        ).fetchone()
    except sqlite3.Error:
        return "", ""
    finally:
        conn.close()
    if not row:
        return "", ""
    return str(row[0]), str(row[1])


def worker_context(
    *,
    owner_user_id: str,
    workspace_id: str = "",
    job_id: str = "",
    scopes: tuple[str, ...] = (),
    observer=None,
    extra_metadata: dict | None = None,
    tool_name: str = "",
) -> ToolContext:
    scope_set = set(scopes)
    if tool_name in READ_SCOPES:
        scope_set.add(READ_SCOPES[tool_name])
    metadata = {
        "principal_kind": PrincipalKind.WORKER.value,
        "owner_user_id": owner_user_id,
        "job_id": job_id,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ToolContext(
        observer=observer,
        actor="worker",
        principal=owner_user_id or "worker",
        agent_id="worker",
        scopes=frozenset(scope_set),
        capabilities=frozenset(scope_set),
        metadata=metadata,
    )


class BoundaryHarness:
    """One read inside ``execute`` when the process has no application harness."""

    def __init__(self, producer: Callable[[], Any]):
        self._producer = producer

    def execute(self, name: str, arguments: dict, context: ToolContext) -> ToolResult:
        del name
        if context.metadata.get("principal_kind") != PrincipalKind.WORKER.value:
            return ToolResult(output="", ok=False, error="worker_principal_required")
        token = _EXECUTING.set(True)
        try:
            output = _invoke_producer(self._producer, arguments or {})
        finally:
            _EXECUTING.reset(token)
        if not isinstance(output, str):
            output = json.dumps(output, ensure_ascii=False, default=str)
        return ToolResult(ok=True, output=output)


def _open_worker(owner_user_id: str, workspace_id: str, job_id: str):
    """Grant this read to the job owner. Invalid ids run without a grant."""
    if not owner_user_id or not workspace_id:
        return None
    import time

    from pu.identity.worker_job import WorkerJob

    try:
        return WorkerJob.open(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            expires_at=time.time() + 120,
            job_id=job_id,
        )
    except (TypeError, ValueError):
        return None


def execute_worker_read(
    harness,
    name: str,
    arguments: dict | None,
    *,
    owner_user_id: str,
    workspace_id: str = "",
    job_id: str = "",
    scopes: tuple[str, ...] = (),
    observer=None,
    extra_metadata: dict | None = None,
    home: Path | None = None,
) -> ToolResult:
    payload = dict(arguments or {})
    connection_id = str(payload.get("connection_id") or "")
    thread_id = str(payload.get("thread_id") or "")
    report_id = str(payload.get("report_id") or "")
    named_workspace = str(payload.get("workspace_id") or "")
    if connection_id:
        from pu.identity.session import refuse_foreign_connection

        refusal = refuse_foreign_connection(home, connection_id, owner_user_id)
        if refusal is not None:
            return ToolResult(output="", ok=False, error=refusal)
    if thread_id or report_id or named_workspace:
        if home is None:
            return ToolResult(output="", ok=False, error="foreign_resource")
        from pu.agents.isolation import ForeignResource, refuse_before_provider
        from pu.db import connect

        conn = connect(home)
        try:
            refuse_before_provider(
                conn,
                thread_id=thread_id,
                report_id=report_id,
                workspace_id=named_workspace,
                owner=owner_user_id,
            )
        except ForeignResource as exc:
            return ToolResult(output="", ok=False, error=exc.code)
        finally:
            conn.close()
    context = worker_context(
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        job_id=job_id,
        scopes=scopes,
        observer=observer,
        extra_metadata=extra_metadata,
        tool_name=name,
    )
    job = _open_worker(owner_user_id, workspace_id, job_id)
    executing = _EXECUTING.set(True)
    try:
        return harness.execute(name, payload, context)
    finally:
        _EXECUTING.reset(executing)
        if job is not None:
            job.close()


def _invoke_producer(producer: Callable[..., Any], arguments: dict) -> Any:
    import inspect

    try:
        parameters = inspect.signature(producer).parameters
    except (TypeError, ValueError):
        return producer()
    if not parameters:
        return producer()
    return producer(arguments)


def parse_json_output(result: ToolResult) -> Any:
    if not result.ok:
        raise ValueError(result.error or "tool harness rejected the read")
    try:
        return json.loads(result.output)
    except (TypeError, ValueError):
        return result.output


def coerce_availability(result: ToolResult) -> dict:
    unknown = {
        "status": "unknown",
        "slots": [],
        "events": [],
        "checked_sources": [],
        "warnings": [],
        "timezone": "Asia/Ho_Chi_Minh",
    }
    if not result.ok:
        unknown["warnings"] = [result.error or "calendar read blocked"]
        return unknown
    try:
        parsed = json.loads(result.output)
    except (TypeError, ValueError):
        unknown["warnings"] = ["calendar read returned no structured intervals"]
        return unknown
    if not isinstance(parsed, dict) or "status" not in parsed:
        return unknown
    parsed.setdefault("slots", [])
    parsed.setdefault("events", [])
    parsed.setdefault("warnings", [])
    parsed.setdefault("checked_sources", [])
    return parsed


def read_calendar_ics(home: Path) -> str:
    """Today's titles from this owner's calendar.ics.

    Called only from a harness ``execute``. Another user's file is not read.
    """
    from pu.identity.files import private_file

    ics = private_file(home, "calendar.ics")
    if ics is None:
        return "(no calendar)"
    today = datetime.now().strftime("%Y%m%d")
    lines: list[str] = []
    title = ""
    for line in ics.read_text(encoding="utf-8").splitlines():
        if line.startswith("SUMMARY:"):
            title = line[len("SUMMARY:") :]
        elif line.startswith("DTSTART") and today in line and title:
            lines.append(title)
    return "; ".join(lines) or "(nothing today)"

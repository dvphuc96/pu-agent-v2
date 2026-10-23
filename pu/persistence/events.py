"""Durable AgentOps event and tool-audit repositories."""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any

from pu.core.interfaces.events import AgentEvent
from pu.harness.audit import ToolAuditRecord, ToolAuditSink, redact
from pu.persistence.database import SQLiteDatabase


class SQLiteAgentEventRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def _guard(self) -> None:
        from pu.identity.worker_job import owner_from_grant

        owner_from_grant()

    def append(self, event: AgentEvent) -> None:
        self._guard()
        with self.database.connection() as conn:
            conn.execute(
                """INSERT INTO agent_events(
                       id, schema_version, kind, occurred_at, trace_id, request_id,
                       workflow_id, agent_id, tool_call_id, execution_id, approval_id,
                       report_id, severity, status, duration_ms, payload_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event.id, event.schema_version, event.kind, event.occurred_at.isoformat(),
                    event.trace_id, event.request_id, event.workflow_id, event.agent_id,
                    event.tool_call_id, event.execution_id, event.approval_id, event.report_id,
                    event.severity, event.status, event.duration_ms,
                    json.dumps(redact(event.payload), ensure_ascii=False, default=str),
                ),
            )

    def for_run(self, workflow_run_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        """Events for one run, keyed by ``(workflow_run_id, owner_user_id)``."""
        return self.list(limit=limit, workflow_id=workflow_run_id)

    def list(self, *, limit: int = 200, workflow_id: str | None = None) -> list[dict[str, Any]]:
        self._guard()
        if _caller_is_admin():
            return []
        sql = "SELECT * FROM agent_events WHERE owner_user_id = pu_current_owner()"
        params: tuple[Any, ...] = ()
        if workflow_id:
            sql += " AND workflow_id=?"
            params = (workflow_id,)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        params += (limit,)
        with self.database.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            items.append(item)
        return items

    def aggregate(self, *, limit: int = 5000) -> dict[str, Any]:
        self._guard()
        if _caller_is_admin():
            return self.platform_aggregate(limit=limit)
        with self.database.connection() as conn:
            rows = conn.execute(
                """SELECT kind, status, duration_ms, payload_json FROM agent_events
                   WHERE owner_user_id = pu_current_owner()
                   ORDER BY occurred_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        by_kind: dict[str, int] = {}
        llm_latencies: list[int] = []
        tool_total = tool_errors = 0
        wf_ok = wf_fail = 0
        approval_total = approval_fail = 0
        security_blocks = 0
        for row in rows:
            kind = row["kind"]
            by_kind[kind] = by_kind.get(kind, 0) + 1
            payload = json.loads(row["payload_json"] or "{}")
            duration = row["duration_ms"]
            if kind == "llm" and duration is not None:
                llm_latencies.append(int(duration))
            if kind == "tool_complete":
                tool_total += 1
                if payload.get("ok") is False:
                    tool_errors += 1
            if kind == "workflow_completed":
                wf_ok += 1
            if kind == "workflow_failed":
                wf_fail += 1
            if kind in {
                "approval_execution_completed",
                "approval_execution_failed",
                "approval_recovery_failed_closed",
            }:
                approval_total += 1
                if kind != "approval_execution_completed" or payload.get("ok") is False:
                    approval_fail += 1
            if kind in {"tool_blocked", "security"} and (
                kind == "tool_blocked" or payload.get("allowed") is False
            ):
                security_blocks += 1
        llm_latencies.sort()
        p95 = 0
        if llm_latencies:
            # Nearest-rank percentile: ceil(p*N)-1 for a zero-based sorted list.
            p95 = llm_latencies[max(0, math.ceil(len(llm_latencies) * 0.95) - 1)]
        return {
            "events": len(rows), "by_kind": by_kind,
            "llm_p95_ms": p95,
            "tool_error_rate": tool_errors / tool_total if tool_total else 0.0,
            "workflow_success_rate": wf_ok / (wf_ok + wf_fail) if (wf_ok + wf_fail) else 1.0,
            "approval_failure_rate": approval_fail / approval_total if approval_total else 0.0,
            "security_blocks": security_blocks,
        }

    def platform_aggregate(self, *, limit: int = 5000) -> dict[str, Any]:
        """Numeric totals across owners. Payload text is not selected.

        Only a platform admin may call this. The query reads kind, status,
        duration, and two scalar JSON flags. It does not return prompts,
        mail, or report bodies.
        """
        if not _caller_is_admin():
            raise PermissionError("platform metrics require a platform admin principal")
        with self.database.connection() as conn:
            rows = conn.execute(
                """SELECT kind, status, duration_ms,
                          json_extract(payload_json, '$.ok') AS ok,
                          json_extract(payload_json, '$.allowed') AS allowed
                   FROM agent_events
                   ORDER BY occurred_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        llm_latencies: list[int] = []
        tool_total = tool_errors = 0
        wf_ok = wf_fail = 0
        approval_total = approval_fail = 0
        security_blocks = 0
        for row in rows:
            kind = row["kind"] if _safe_kind(row["kind"]) else "other"
            duration = row["duration_ms"]
            ok = _json_bool(row["ok"])
            allowed = _json_bool(row["allowed"])
            if kind == "llm" and duration is not None:
                llm_latencies.append(int(duration))
            if kind == "tool_complete":
                tool_total += 1
                if ok is False:
                    tool_errors += 1
            if kind == "workflow_completed":
                wf_ok += 1
            if kind == "workflow_failed":
                wf_fail += 1
            if kind in {
                "approval_execution_completed",
                "approval_execution_failed",
                "approval_recovery_failed_closed",
            }:
                approval_total += 1
                if kind != "approval_execution_completed" or ok is False:
                    approval_fail += 1
            if kind in {"tool_blocked", "security"} and (
                kind == "tool_blocked" or allowed is False
            ):
                security_blocks += 1
        llm_latencies.sort()
        p95 = 0
        if llm_latencies:
            p95 = llm_latencies[max(0, math.ceil(len(llm_latencies) * 0.95) - 1)]
        return {
            "events": len(rows),
            "llm_p95_ms": p95,
            "tool_error_rate": tool_errors / tool_total if tool_total else 0.0,
            "workflow_success_rate": wf_ok / (wf_ok + wf_fail) if (wf_ok + wf_fail) else 1.0,
            "approval_failure_rate": approval_fail / approval_total if approval_total else 0.0,
            "security_blocks": security_blocks,
        }


def _caller_is_admin() -> bool:
    from pu.identity.principal import PrincipalKind
    from pu.identity.seam import attached_principal

    attached = attached_principal()
    return attached is not None and attached.kind is PrincipalKind.PLATFORM_ADMIN


def _safe_kind(kind: object) -> bool:
    if not isinstance(kind, str) or not kind or len(kind) > 64:
        return False
    return all(char.isalnum() or char in {"_", ".", ":"} for char in kind)


def _json_bool(value: object) -> bool | None:
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    return None


class SQLiteToolAuditSink(ToolAuditSink):
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def append(self, record: ToolAuditRecord) -> None:
        payload = redact(asdict(record))
        with self.database.connection() as conn:
            conn.execute(
                """INSERT INTO tool_audit_events(
                       execution_id, request_id, workflow_id, agent_id, tool_call_id,
                       actor, principal, tool, capability, required_scope, side_effect,
                       external, action_hash, status, timestamp, policy, reason,
                       latency_ms, result_summary, error, record_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.execution_id, record.request_id, record.workflow_id, record.agent_id,
                    record.tool_call_id, record.actor, record.principal, record.tool,
                    record.capability, record.required_scope, int(record.side_effect),
                    int(record.external), record.action_hash, record.status, record.timestamp,
                    record.policy, payload.get("reason"), record.latency_ms,
                    payload.get("result_summary"), payload.get("error"),
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )

    def list(self, limit: int = 250) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """SELECT record_json FROM tool_audit_events
                   WHERE owner_user_id = pu_current_owner()
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

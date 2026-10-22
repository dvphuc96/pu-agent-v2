"""Durable, redacted audit trail for tool executions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}

SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{10,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+"),
)


def redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    key = os.environ.get("PU_TOKEN_KEY", "")
    if len(key) >= 8 and key in redacted:
        redacted = redacted.replace(key, "[REDACTED]")
    return redacted


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _is_sensitive_key(key: str) -> bool:
    low = key.lower().replace("-", "_")
    return any(part in low for part in SENSITIVE_KEYS)


def redact(value: Any, *, key: str = "") -> Any:
    if key and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def action_hash(tool_name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"tool": tool_name, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolAuditRecord:
    execution_id: str
    request_id: str | None
    workflow_id: str | None
    agent_id: str | None
    tool_call_id: str | None
    actor: str
    principal: str | None
    tool: str
    capability: str
    required_scope: str
    side_effect: bool
    external: bool
    arguments: dict[str, Any]
    action_hash: str
    status: str
    timestamp: str
    policy: str | None = None
    reason: str | None = None
    latency_ms: int | None = None
    result_summary: str | None = None
    error: str | None = None


@runtime_checkable
class ToolAuditSink(Protocol):
    def append(self, record: ToolAuditRecord) -> None: ...


class JsonlToolAuditSink(ToolAuditSink):
    """Append-only JSONL audit sink. Each transition is a separate event."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: ToolAuditRecord) -> None:
        payload = redact(asdict(record))
        if not isinstance(payload, dict):
            payload = {"value": payload}
        path = self._destination(payload)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        with self._lock, path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def _production_home(self) -> Path | None:
        """Container wires one sink at ``home/traces/tool-audit.jsonl``.

        An explicit path such as a unit-test ``audit.jsonl`` is not that sink
        and keeps writing exactly where it was constructed.
        """
        if self.path.name != "tool-audit.jsonl" or self.path.parent.name != "traces":
            return None
        return self.path.parent.parent

    def _destination(self, payload: dict) -> Path | None:
        """Per-owner tool audit. Never copy one owner's file into another root.

        The database-local owner still uses ``home/traces/tool-audit.jsonl``.
        Every line is stamped with the principal's ``owner_user_id``. A missing
        owner, a denied worker grant, or a platform admin writes nothing here.
        """
        home = self._production_home()
        if home is None:
            return self.path
        from pu.ops.telemetry import telemetry_scope, trace_dir_for

        scope = telemetry_scope(home)
        if scope.denied or scope.admin or not scope.owner_user_id:
            return None
        payload["owner_user_id"] = scope.owner_user_id
        if scope.isolated:
            return trace_dir_for(home, scope) / self.path.name
        return self.path


class CompositeToolAuditSink(ToolAuditSink):
    """Fan one immutable audit transition to multiple durable sinks."""

    def __init__(self, *sinks: ToolAuditSink):
        self.sinks = [sink for sink in sinks if sink is not None]

    def append(self, record: ToolAuditRecord) -> None:
        for sink in self.sinks:
            sink.append(record)


class InMemoryToolAuditSink(ToolAuditSink):
    """Deterministic test sink; never used by product composition root."""

    def __init__(self):
        self.records: list[ToolAuditRecord] = []

    def append(self, record: ToolAuditRecord) -> None:
        self.records.append(record)

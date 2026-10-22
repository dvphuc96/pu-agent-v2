"""Durable AgentOps event bus, metrics projection and SLO evaluation."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from pu.config import Settings
from pu.core.interfaces.events import AgentEvent, AgentEventRepository, EventPublisher


def _status(kind: str, payload: dict[str, Any]) -> str | None:
    if payload.get("ok") is False or payload.get("allowed") is False:
        return "failed"
    if kind.endswith("_failed") or kind in {"workflow_failed", "tool_blocked"}:
        return "failed"
    if kind.endswith("_completed") or payload.get("ok") is True:
        return "succeeded"
    return payload.get("status") or payload.get("gate_status")


def _severity(kind: str, payload: dict[str, Any]) -> str:
    status = _status(kind, payload)
    if status in {"failed", "fail", "blocked"} or kind in {"tool_blocked", "workflow_failed"}:
        return "warning"
    return "info"


class AgentOpsHarness(EventPublisher):
    """Single event boundary for JSONL/OTel tracing + durable structured events."""

    def __init__(self, repository: AgentEventRepository, tracer=None):
        self.repository = repository
        self.tracer = tracer

    def publish(self, kind: str, event: dict[str, Any]) -> None:
        payload = dict(event or {})
        duration = payload.get("latency_ms", payload.get("duration_ms", payload.get("ms")))
        try:
            duration_ms = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_ms = None
        workflow_id = payload.get("workflow_id")
        request_id = payload.get("request_id")
        structured = AgentEvent(
            kind=kind,
            payload=payload,
            trace_id=payload.get("trace_id") or workflow_id or request_id,
            request_id=request_id,
            workflow_id=workflow_id,
            agent_id=payload.get("agent_id"),
            tool_call_id=payload.get("tool_call_id"),
            execution_id=payload.get("execution_id"),
            approval_id=payload.get("approval_id"),
            report_id=payload.get("report_id"),
            severity=_severity(kind, payload),
            status=_status(kind, payload),
            duration_ms=duration_ms,
        )
        self.repository.append(structured)
        if self.tracer is not None:
            self.tracer.event(kind, {
                "event_id": structured.id,
                "schema_version": structured.schema_version,
                **payload,
            })


@dataclass(frozen=True)
class SLOStatus:
    name: str
    value: float
    target: float
    comparator: str
    ok: bool
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SLOEvaluator:
    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(self, metrics: dict[str, Any]) -> dict[str, Any]:
        checks = [
            SLOStatus(
                "llm_p95_latency",
                float(metrics.get("llm_p95_ms", 0)),
                float(self.settings.slo_llm_p95_ms),
                "<=", float(metrics.get("llm_p95_ms", 0)) <= self.settings.slo_llm_p95_ms,
                "ms",
            ),
            SLOStatus(
                "tool_error_rate",
                float(metrics.get("tool_error_rate", 0)),
                float(self.settings.slo_tool_error_rate),
                "<=", float(metrics.get("tool_error_rate", 0)) <= self.settings.slo_tool_error_rate,
                "ratio",
            ),
            SLOStatus(
                "workflow_success_rate",
                float(metrics.get("workflow_success_rate", 1)),
                float(self.settings.slo_workflow_success_rate),
                ">=", float(metrics.get("workflow_success_rate", 1)) >= self.settings.slo_workflow_success_rate,
                "ratio",
            ),
            SLOStatus(
                "approval_failure_rate",
                float(metrics.get("approval_failure_rate", 0)),
                float(self.settings.slo_approval_failure_rate),
                "<=", float(metrics.get("approval_failure_rate", 0)) <= self.settings.slo_approval_failure_rate,
                "ratio",
            ),
            SLOStatus(
                "security_blocks",
                float(metrics.get("security_blocks", 0)),
                float(self.settings.slo_security_blocks_max),
                "<=", float(metrics.get("security_blocks", 0)) <= self.settings.slo_security_blocks_max,
                "events",
            ),
        ]
        return {
            "healthy": all(check.ok for check in checks),
            "checks": [check.to_dict() for check in checks],
            "alerts": [check.to_dict() for check in checks if not check.ok],
        }


_METRIC_NUMBERS = (
    ("events", "pu_agentops_events_total", "counter", "Durable structured AgentOps events.", 0, int),
    ("llm_p95_ms", "pu_llm_p95_latency_ms", "gauge", "Observed LLM p95 latency in milliseconds.", 0, float),
    ("tool_error_rate", "pu_tool_error_rate", "gauge", "Tool execution error ratio.", 0, float),
    ("workflow_success_rate", "pu_workflow_success_rate", "gauge", "Workflow success ratio.", 1, float),
    ("approval_failure_rate", "pu_approval_failure_rate", "gauge", "Approved action execution failure ratio.", 0, float),
    ("security_blocks", "pu_security_blocks_total", "gauge", "Security-policy blocks in retained event window.", 0, int),
)

_SLO_NAMES = frozenset({
    "llm_p95_latency",
    "tool_error_rate",
    "workflow_success_rate",
    "approval_failure_rate",
    "security_blocks",
})


def _metric_number(metrics: dict[str, Any], key: str, default: float, cast):
    value = metrics.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return cast(default)
    return cast(value)


def prometheus_text(metrics: dict[str, Any], slo: dict[str, Any]) -> str:
    """Dependency-free Prometheus exposition of numeric AgentOps series.

    Only allowlisted numbers and SLO names are rendered. Prompts, mail,
    report text, and other payload fields are not series and not labels.
    """
    lines = []
    for key, name, kind, help_text, default, cast in _METRIC_NUMBERS:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f"{name} {_metric_number(metrics, key, default, cast)}")
    lines.append("# HELP pu_slo_healthy Whether every configured SLO is currently healthy.")
    lines.append("# TYPE pu_slo_healthy gauge")
    lines.append(f"pu_slo_healthy {1 if slo.get('healthy') else 0}")
    for check in slo.get("checks", []):
        if not isinstance(check, dict):
            continue
        label_name = check.get("name")
        if label_name not in _SLO_NAMES:
            continue
        label = json.dumps(label_name)
        lines.append(f"pu_slo_check_ok{{name={label}}} {1 if check.get('ok') else 0}")
    return "\n".join(lines) + "\n"

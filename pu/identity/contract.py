"""Typed agent request: principal, owner, workspace, scope, and approval.

A request that lacks a principal or an owner is rejected here, before any
model or tool call. Production code does not substitute a local default.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pu.core.interfaces.tools import ToolContext, ToolHarness, ToolResult
from pu.identity.directory import current_principal
from pu.identity.principal import Principal, PrincipalKind

APPROVAL_STATUSES = frozenset(
    {"not_required", "pending", "approved", "rejected", "expired"}
)

# Labels the single-user code used before a backend UUID existed. A model or
# tool call may not present one of these as its principal.
LEGACY_PRINCIPALS = frozenset(
    {"local-user", "graph-local-user", "local-dashboard-user", "local-human"}
)


class AgentRequestRejected(PermissionError):
    """The request never reached a model or a tool."""


@dataclass(frozen=True)
class AgentRequest:
    principal: Principal | None
    owner_user_id: str = ""
    workspace_id: str = ""
    agent_scopes: frozenset[str] = frozenset()
    tool_scopes: frozenset[str] = frozenset()
    approval_status: str = "not_required"

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", str(self.owner_user_id or ""))
        object.__setattr__(self, "workspace_id", str(self.workspace_id or ""))
        object.__setattr__(self, "agent_scopes", frozenset(self.agent_scopes))
        object.__setattr__(self, "tool_scopes", frozenset(self.tool_scopes))
        object.__setattr__(self, "approval_status", str(self.approval_status or ""))


def is_backend_user_id(value: object) -> bool:
    """True for a canonical UUID. Legacy labels and other strings are not."""
    if not isinstance(value, str) or value in LEGACY_PRINCIPALS:
        return False
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return False
    return str(parsed) == value


def admit(request: AgentRequest) -> AgentRequest:
    """Reject an incomplete request. Call this before a model or a tool."""
    if not isinstance(request, AgentRequest):
        raise AgentRequestRejected("request is missing principal or owner")
    if request.principal is None or not request.owner_user_id.strip():
        raise AgentRequestRejected("request is missing principal or owner")
    if request.principal.kind is PrincipalKind.PLATFORM_ADMIN:
        raise AgentRequestRejected("platform admin cannot own a private request")
    if request.owner_user_id != request.principal.user_id:
        raise AgentRequestRejected("owner does not match principal")
    if not request.workspace_id.strip():
        raise AgentRequestRejected("workspace is required")
    if request.approval_status not in APPROVAL_STATUSES:
        raise AgentRequestRejected("approval status is invalid")
    return request


def request_for_connection(conn, *, scopes, approval_status: str = "not_required") -> AgentRequest:
    """Build a request from the authenticated principal. Never invents an owner."""
    principal = current_principal(conn)
    return admit(
        AgentRequest(
            principal=principal,
            owner_user_id=principal.user_id,
            workspace_id=principal.workspace_id,
            agent_scopes=frozenset(scopes),
            tool_scopes=frozenset(scopes),
            approval_status=approval_status,
        )
    )


def request_from_tool_context(context: ToolContext) -> AgentRequest:
    """Rebuild a request from a context that ``tool_context_from_request`` wrote.

    A bare string such as ``local-user`` has no principal kind or owner and is
    rejected before ``admit``.
    """
    if context is None or not is_backend_user_id(context.principal):
        raise AgentRequestRejected("request is missing principal or owner")
    meta = context.metadata or {}
    kind_name = meta.get("principal_kind")
    try:
        kind = PrincipalKind(kind_name)
        principal = Principal(
            kind,
            str(meta.get("owner_user_id") or ""),
            str(meta.get("workspace_id") or ""),
        )
    except (TypeError, ValueError) as exc:
        raise AgentRequestRejected("request is missing principal or owner") from exc
    if context.principal != principal.user_id:
        raise AgentRequestRejected("owner does not match principal")
    return AgentRequest(
        principal=principal,
        owner_user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        agent_scopes=frozenset(meta.get("agent_scopes") or context.capabilities),
        tool_scopes=frozenset(meta.get("tool_scopes") or context.scopes),
        approval_status=str(meta.get("approval_status") or "not_required"),
    )


def admit_call(
    *,
    contract: AgentRequest | None,
    context: ToolContext | None,
) -> AgentRequest:
    """Admit every model call. A string or legacy principal never qualifies."""
    if context is not None and context.principal and not is_backend_user_id(context.principal):
        raise AgentRequestRejected("request is missing principal or owner")
    if contract is None:
        if context is None:
            raise AgentRequestRejected("request is missing principal or owner")
        contract = request_from_tool_context(context)
    admitted = admit(contract)
    if context is not None and context.principal and context.principal != admitted.principal.user_id:
        raise AgentRequestRejected("owner does not match principal")
    return admitted


def tool_context_from_request(request: AgentRequest, **overrides) -> ToolContext:
    """Tool context for an admitted request. The principal string is the user id."""
    admit(request)
    metadata = {
        "owner_user_id": request.owner_user_id,
        "workspace_id": request.workspace_id,
        "approval_status": request.approval_status,
        "principal_kind": request.principal.kind.value,
        "agent_scopes": sorted(request.agent_scopes),
        "tool_scopes": sorted(request.tool_scopes),
    }
    extra = overrides.pop("metadata", None) or {}
    metadata.update(extra)
    scopes = overrides.pop("scopes", request.tool_scopes)
    capabilities = overrides.pop("capabilities", request.agent_scopes)
    return ToolContext(
        principal=request.principal.user_id,
        scopes=frozenset(scopes),
        capabilities=frozenset(capabilities),
        metadata=metadata,
        **overrides,
    )


def invoke_tool(
    harness: ToolHarness,
    name: str,
    arguments: dict,
    request: AgentRequest,
    **context_kwargs,
) -> ToolResult:
    """Admit the request, then execute. A rejected request does not reach the tool."""
    context = tool_context_from_request(request, **context_kwargs)
    return harness.execute(name, arguments, context)

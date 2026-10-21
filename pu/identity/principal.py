"""Principals issued by the backend.

A client cannot choose, submit, or overwrite ``user_id``. ``WORKER`` has no
identity of its own: the job's ``owner_user_id`` is the only data scope, and
it ends when the job or its lease ends. ``PLATFORM_ADMIN`` does not receive
private rows by default.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class PrincipalKind(str, Enum):
    USER = "USER"
    WORKER = "WORKER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


def issue_user_id() -> str:
    """Return a new backend-generated user id. Callers cannot supply one."""
    return str(uuid.uuid4())


def issue_workspace_id() -> str:
    """Return a new backend-generated personal workspace id."""
    return str(uuid.uuid4())


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    user_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PrincipalKind):
            raise TypeError("kind must be a PrincipalKind")
        _require_uuid(self.user_id, "user_id")
        _require_uuid(self.workspace_id, "workspace_id")


def _require_uuid(value: str, field: str) -> None:
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a backend UUID") from exc
    if str(parsed) != str(value):
        raise ValueError(f"{field} must be a canonical UUID")

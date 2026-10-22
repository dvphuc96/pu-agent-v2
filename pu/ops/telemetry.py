"""Who a telemetry read or write belongs to.

JSONL traces and the usage ledger are files, so they cannot rely on SQL row
ownership. The attached principal, or the worker job grant, decides the file.
A platform admin does not receive another owner's trace content. A client
value named ``owner_user_id`` is never consulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TelemetryScope:
    owner_user_id: str
    local_owner: str
    admin: bool
    denied: bool

    @property
    def isolated(self) -> bool:
        """True when this caller must not use the shared home trace or ledger."""
        if self.admin or self.denied:
            return True
        return bool(self.owner_user_id and self.owner_user_id != self.local_owner)


def telemetry_scope(home: Path) -> TelemetryScope:
    """Resolve the caller. An expired worker grant is denied, not reassigned."""
    from pu.identity.files import database_local_owner
    from pu.identity.principal import PrincipalKind
    from pu.identity.seam import attached_principal
    from pu.identity.worker_job import owner_from_grant

    try:
        local_owner = database_local_owner(home)
    except OSError:
        local_owner = ""
    try:
        granted = owner_from_grant()
    except PermissionError:
        return TelemetryScope("", local_owner, admin=False, denied=True)
    if granted:
        return TelemetryScope(granted, local_owner, admin=False, denied=False)
    attached = attached_principal()
    if attached is not None:
        admin = attached.kind is PrincipalKind.PLATFORM_ADMIN
        return TelemetryScope(attached.user_id, local_owner, admin=admin, denied=False)
    return TelemetryScope(local_owner, local_owner, admin=False, denied=False)


def _owner_dir(home: Path, owner_user_id: str) -> Path:
    from pu.identity.files import owner_root

    return owner_root(home, owner_user_id)


def trace_dir_for(home: Path, scope: TelemetryScope | None = None) -> Path:
    """Directory the caller may read or write. Admin gets an empty private dir."""
    home = Path(home)
    scope = scope or telemetry_scope(home)
    if scope.isolated and scope.owner_user_id:
        return _owner_dir(home, scope.owner_user_id) / "traces"
    if scope.denied or scope.admin:
        return home / "owners" / "_denied" / "traces"
    return home / "traces"


def trace_write_path(home: Path, filename: str) -> Path:
    """File that receives the next trace line. Refuses a denied worker grant."""
    scope = telemetry_scope(home)
    if scope.denied:
        raise PermissionError("telemetry owner is not available")
    directory = trace_dir_for(home, scope)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


def readable_trace_files(home: Path) -> list[Path]:
    """Trace files whose lines the current principal may read."""
    scope = telemetry_scope(home)
    if scope.admin or scope.denied:
        return []
    directory = trace_dir_for(home, scope)
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.jsonl") if path.is_file())


def usage_write_path(home: Path) -> Path:
    scope = telemetry_scope(home)
    if scope.denied:
        raise PermissionError("telemetry owner is not available")
    if scope.isolated and scope.owner_user_id:
        path = _owner_dir(home, scope.owner_user_id) / "usage.jsonl"
    else:
        path = Path(home) / "usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def usage_read_paths(home: Path) -> list[Path]:
    """Ledger files the caller may summarize. Admin reads none of the text here."""
    scope = telemetry_scope(home)
    if scope.admin or scope.denied:
        return []
    if scope.isolated and scope.owner_user_id:
        path = _owner_dir(home, scope.owner_user_id) / "usage.jsonl"
    else:
        path = Path(home) / "usage.jsonl"
    return [path] if path.is_file() else []


def all_usage_files(home: Path) -> list[Path]:
    """Every ledger file on disk. Callers must reduce these to numbers."""
    home = Path(home)
    files: list[Path] = []
    legacy = home / "usage.jsonl"
    if legacy.is_file():
        files.append(legacy)
    owners = home / "owners"
    if owners.is_dir():
        files.extend(sorted(path for path in owners.glob("*/usage.jsonl") if path.is_file()))
    return files

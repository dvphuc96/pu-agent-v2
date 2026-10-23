"""Private files live under an owner root.

New bytes are written only under ``owners/<owner_user_id>/``. A read may
still open a legacy path for the database-local user so older single-user
files keep working. Another owner's file is refused.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

PRIVATE_RELATIVE_PATHS = (
    "usage.jsonl",
    "eval_runs.jsonl",
    "calendar.ics",
    "SOUL.md",
    "MEMORY.md",
    "models.json",
    ".env",
    "credentials.json",
    "gmail-token.json",
    "gmail-send-token.json",
    "calendar-token.json",
    "google-token.json",
    "google-calendar-token.json",
    "drive-token.json",
    "token.json",
)


class OwnershipDenied(PermissionError):
    """The current principal does not own the requested private file."""


def database_local_owner(home: Path) -> str:
    """The single dev/test owner stored in this database, ignoring the session."""
    return _local_owner(Path(home))


def owner_for_home(home: Path) -> str:
    """Owner for a private file.

    A cookieless request raises. It does not fall back to the database-local
    owner or to a legacy path. Outside a request the local owner is used. A
    home that has never opened its identity database returns ``""`` so
    single-user files stay on their legacy paths. That branch is unreachable
    while a request is bound.
    """
    from pu.identity.principal import PrincipalKind
    from pu.identity.session import request_bound, session_principal
    from pu.identity.worker_job import owner_from_grant

    granted = owner_from_grant()
    if granted is not None:
        if not granted:
            raise PermissionError("no authenticated principal")
        return granted
    principal = session_principal()
    if principal is not None:
        if principal.kind is PrincipalKind.PLATFORM_ADMIN or not principal.user_id:
            raise PermissionError("no authenticated principal")
        return principal.user_id
    if request_bound():
        raise PermissionError("no authenticated principal")
    return database_local_owner(home)


def owner_root(home: Path, owner_user_id: str) -> Path:
    return Path(home) / "owners" / owner_user_id


def owned_token_path(home: Path, relative: str) -> Path:
    """Path this owner may read or write for one OAuth token.

    A bound request with no principal raises before any path is returned.
    An existing copy under ``owners/<id>/`` wins. The legacy ``home/<relative>``
    file is returned only for the database-local owner, which is how a
    single-user token stays readable after the identity database appears.
    Every other owner gets ``owners/<id>/<relative>`` and does not receive
    the shared file.
    """
    owner = owner_for_home(home)
    found = private_file(home, relative)
    if found is not None:
        return found
    if owner == database_local_owner(home):
        return Path(home) / relative
    return owner_root(home, owner) / relative


def write_owned_bytes(home: Path, relative: str, data: bytes) -> Path:
    """Write ``relative`` under the current owner root only."""
    owner = owner_for_home(home)
    if not owner:
        raise OwnershipDenied("no principal is available to own this file")
    path = owner_root(home, owner) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _record(home, relative, owner)
    return path


def write_owned_text(home: Path, relative: str, text: str) -> Path:
    return write_owned_bytes(home, relative, text.encode("utf-8"))


def private_file(home: Path, relative: str) -> Path | None:
    """Path the current owner may read.

    A bound request with no principal raises before any path is returned.
    Outside a request, a home with no identity database may still open its
    legacy file. A file claimed by someone else, or a legacy file when this
    user is not the database-local owner, is not returned. Callers treat
    ``None`` as "this user has no such file" and must not open the other copy.
    """
    legacy = Path(home) / relative
    owner = owner_for_home(home)
    if not owner:
        return legacy if legacy.is_file() else None
    owned = owner_root(home, owner) / relative
    if owned.is_file():
        return owned
    if not legacy.is_file():
        return None
    sidecar = legacy.with_name(legacy.name + ".owner")
    claimed = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""
    local = _local_owner(home)
    if claimed and claimed != owner:
        return None
    if not claimed and local and owner != local:
        return None
    return legacy


def claim_private_file(home: Path, relative: str) -> None:
    """Mark a legacy file as the current owner's and mirror it."""
    owner = owner_for_home(home)
    path = Path(home) / relative
    if owner and path.is_file():
        path.with_name(path.name + ".owner").write_text(owner, encoding="utf-8")
    if path.is_file():
        note_written(home, path)


def read_owned_bytes(home: Path, relative: str) -> bytes:
    owner = owner_for_home(home)
    if not owner:
        raise OwnershipDenied("no principal is available to read this file")
    owned = owner_root(home, owner) / relative
    if owned.is_file():
        return owned.read_bytes()
    legacy = Path(home) / relative
    if not legacy.is_file():
        raise OwnershipDenied("private file is not visible to this user")
    sidecar = legacy.with_name(legacy.name + ".owner")
    recorded = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""
    local = _local_owner(home)
    if recorded and recorded != owner:
        raise OwnershipDenied("private file belongs to another user")
    if not recorded and local and owner != local:
        raise OwnershipDenied("private file belongs to another user")
    return legacy.read_bytes()


def note_written(home: Path, path: Path) -> None:
    """Copy a file just written on its legacy path into the current owner root.

    The legacy path stays so existing readers keep working. A failure to copy
    never fails the write that already succeeded.
    """
    try:
        relative = Path(path).resolve().relative_to(Path(home).resolve()).as_posix()
        mirror_existing(Path(home), relative)
    except (OSError, ValueError, sqlite3.Error, AttributeError, PermissionError):
        return


def mirror_existing(home: Path, relative: str) -> None:
    """Copy a legacy file into the current owner's root when it is safe to do so."""
    try:
        owner = owner_for_home(home)
    except (sqlite3.Error, PermissionError):
        return
    if not owner:
        return
    source = Path(home) / relative
    if not source.is_file():
        return
    target = owner_root(home, owner) / relative
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        _record(home, relative, owner)
    except OSError:
        return


def _local_owner(home: Path) -> str:
    database = Path(home) / "state.db"
    if not database.is_file():
        return ""
    conn = sqlite3.connect(database)
    try:
        row = conn.execute(
            "SELECT user_id FROM identity_local WHERE singleton = 1"
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    return row[0] if row else ""


def _record(home: Path, relative: str, owner: str) -> None:
    database = Path(home) / "state.db"
    if not database.is_file():
        return
    conn = sqlite3.connect(database)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO private_files(relative_path, owner_user_id) VALUES(?, ?)",
            (relative, owner),
        )
        conn.commit()
    except sqlite3.Error:
        return
    finally:
        conn.close()

"""Private files live under an owner root.

New bytes are written only under ``owners/<owner_user_id>/``. A read may
still open a legacy path for the database-local user so older single-user
files keep working. Another owner's file is refused.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pu.identity.seam import attached_principal

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


def owner_for_home(home: Path) -> str:
    attached = attached_principal()
    if attached is not None:
        return attached.user_id
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


def owner_root(home: Path, owner_user_id: str) -> Path:
    return Path(home) / "owners" / owner_user_id


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
    except (OSError, ValueError, sqlite3.Error, AttributeError):
        return


def mirror_existing(home: Path, relative: str) -> None:
    """Copy a legacy file into the current owner's root when it is safe to do so."""
    try:
        owner = owner_for_home(home)
    except sqlite3.Error:
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

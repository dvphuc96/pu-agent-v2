"""Owner-scoped bytes for an uploaded document.

The extracted text lives in the workspace. The original bytes live only
under that owner's attachment directory, so another user cannot read or
download them by id.
"""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

_ID = re.compile(r"att-[0-9a-f]{32}")


def store_attachment(home: Path, filename: str, encoded: str) -> str:
    """Persist the original bytes for the current owner. Returns the id."""
    from pu.identity.files import OwnershipDenied, owner_for_home, owner_root

    owner = owner_for_home(home)
    if not owner:
        raise OwnershipDenied("no principal is available to own this file")
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Dữ liệu file không hợp lệ.") from exc
    attachment_id = "att-" + uuid.uuid4().hex
    root = owner_root(home, owner) / "attachments" / attachment_id
    root.mkdir(parents=True)
    safe_name = Path(filename).name or "attachment"
    (root / "name.txt").write_text(safe_name, encoding="utf-8")
    (root / "body").write_bytes(data)
    return attachment_id


def read_attachment(home: Path, attachment_id: str) -> tuple[str, bytes]:
    """Return ``(filename, bytes)`` for an attachment this owner stored.

    Another owner's id raises ``KeyError`` and does not include their bytes.
    """
    from pu.identity.files import OwnershipDenied, owner_for_home, owner_root

    if not isinstance(attachment_id, str) or not _ID.fullmatch(attachment_id):
        raise KeyError("attachment")
    owner = owner_for_home(home)
    if not owner:
        raise OwnershipDenied("no principal is available to read this file")
    root = owner_root(home, owner) / "attachments" / attachment_id
    body = root / "body"
    if not body.is_file():
        raise KeyError("attachment")
    name = (root / "name.txt").read_text(encoding="utf-8")
    return name, body.read_bytes()

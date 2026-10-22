"""Eval homes for two users.

Each user gets a distinct directory, database, and trace folder. The shared
``.pu`` directory is never one of those homes.
"""

from __future__ import annotations

from pathlib import Path

_SHARED = ".pu"
RELEASE_GATE_OWNER = "release-gate"


def assign_eval_homes(root: Path, owner_user_ids: list[str]) -> dict[str, Path]:
    """Return one eval home per owner, under ``root/eval-homes``.

    Homes are distinct paths. None of them is ``root / ".pu"``.
    """
    root = Path(root).resolve()
    if not owner_user_ids:
        raise ValueError("eval owners are required")
    homes: dict[str, Path] = {}
    seen: set[Path] = set()
    shared = (root / _SHARED).resolve()
    for owner_user_id in owner_user_ids:
        home = _one_home(root, owner_user_id)
        if home in seen or home == shared or home.name == _SHARED:
            raise ValueError("eval homes must be distinct and must not be the shared .pu directory")
        seen.add(home)
        homes[owner_user_id] = home
    return homes


def prepare_eval_home(root: Path, owner_user_id: str) -> Path:
    """Create one user's eval home and its own database."""
    home = assign_eval_homes(root, [owner_user_id])[owner_user_id]
    from pu.db import connect

    connect(home).close()
    (home / "traces").mkdir(exist_ok=True)
    return home


def _one_home(root: Path, owner_user_id: str) -> Path:
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise ValueError("eval owner is required")
    if owner_user_id != Path(owner_user_id).name or owner_user_id in {".", "..", _SHARED}:
        raise ValueError("eval owner is not a single path segment")
    home = (root / "eval-homes" / owner_user_id).resolve()
    try:
        home.relative_to(root / "eval-homes")
    except ValueError as exc:
        raise ValueError("eval home escaped the suite root") from exc
    if home.name == _SHARED or home == (root / _SHARED).resolve():
        raise ValueError("eval home must not be the shared .pu directory")
    home.mkdir(parents=True, exist_ok=True)
    return home

"""WORKER authorization lasts only as long as the job and its lease.

The process does not keep an owner after the job ends. A later read through
the same job raises, even while the process is still alive. A database lease
that has already expired fails the same way once the job is armed.
"""

from __future__ import annotations

import sqlite3
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass

from pu.identity.principal import Principal, PrincipalKind
from pu.identity.seam import InternalPrincipalSeam

_GRANT: ContextVar[JobGrant | None] = ContextVar("pu_worker_job", default=None)

_DENIED = "worker job ended or lease expired"


@dataclass
class JobGrant:
    owner_user_id: str
    workspace_id: str
    expires_at: float
    db_path: str = ""
    job_id: str = ""
    closed: bool = False
    watch_db_lease: bool = False

    def allows_read(self) -> bool:
        if self.closed or self.expires_at <= time.time():
            return False
        return not (self.watch_db_lease and _db_lease_expired(self))


def owner_from_grant() -> str | None:
    """Return the job owner, or None when this context is not a worker job.

    A finished or expired job raises. Callers must not fall back to another
    owner after that.
    """
    grant = _GRANT.get()
    if grant is None:
        return None
    if not grant.allows_read():
        raise PermissionError(_DENIED)
    return grant.owner_user_id


def current_grant() -> JobGrant | None:
    """Same check as ``owner_from_grant``, returning the grant itself."""
    owner_from_grant()
    return _GRANT.get()


def arm_worker_lease() -> None:
    """Start enforcing the database lease for the job that is open now."""
    grant = _GRANT.get()
    if grant is not None and not grant.closed:
        grant.watch_db_lease = True


def reset_worker_grant() -> None:
    """Drop a leaked grant. Test isolation calls this between cases."""
    _GRANT.set(None)


class WorkerJob:
    """One owner scope for one job. ``close`` restores the caller's principal."""

    def __init__(self, grant: JobGrant, grant_token: Token, seam_token: Token):
        self.grant = grant
        self._grant_token = grant_token
        self._seam_token = seam_token

    @classmethod
    def open(
        cls,
        *,
        owner_user_id: str,
        workspace_id: str,
        expires_at: float,
        db_path: str = "",
        job_id: str = "",
        watch_db_lease: bool = False,
    ) -> WorkerJob:
        principal = Principal(PrincipalKind.WORKER, owner_user_id, workspace_id)
        grant = JobGrant(
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            expires_at=expires_at,
            db_path=db_path,
            job_id=job_id,
            watch_db_lease=watch_db_lease,
        )
        grant_token = _GRANT.set(grant)
        try:
            seam_token = InternalPrincipalSeam().attach(principal)
        except Exception:
            _GRANT.reset(grant_token)
            raise
        return cls(grant, grant_token, seam_token)

    def assert_live(self) -> None:
        if not self.grant.allows_read():
            raise PermissionError(_DENIED)

    def finish(self) -> None:
        """The job ended. Further reads through this grant fail."""
        self.grant.closed = True

    def expire(self) -> None:
        """The in-memory lease is over. The process may still be running."""
        self.grant.expires_at = 0

    def close(self) -> None:
        """End the job and restore the principal that was current before ``open``."""
        self.grant.closed = True
        if self._seam_token is not None:
            InternalPrincipalSeam().detach(self._seam_token)
            self._seam_token = None
        if self._grant_token is not None:
            _GRANT.reset(self._grant_token)
            self._grant_token = None


def _db_lease_expired(grant: JobGrant) -> bool:
    if not grant.db_path:
        return False
    try:
        conn = sqlite3.connect(grant.db_path, timeout=1)
    except sqlite3.Error:
        return True
    try:
        row = conn.execute(
            """SELECT value FROM briefing_state
               WHERE key='lease_until' AND owner_user_id=?""",
            (grant.owner_user_id,),
        ).fetchone()
    except sqlite3.Error:
        return True
    finally:
        conn.close()
    if row is None or row[0] in (None, ""):
        return False
    try:
        return float(row[0]) <= time.time()
    except (TypeError, ValueError):
        return True

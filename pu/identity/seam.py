"""Phase 1 internal principal seam.

``InternalPrincipalSeam`` lives in front of the tool harness, approval, and
repositories whenever they ask who the caller is. Tests attach a principal
with ``attach``. The seam returns that principal. It never reads
``owner_user_id`` or ``workspace_id`` from a request body.

Phase 6 deletes this module and the ``principal_seam`` field. A request
without an OIDC session cookie must not receive a principal after that cut.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from pu.identity.principal import Principal

_ATTACHED: ContextVar[Principal | None] = ContextVar("pu_internal_principal", default=None)


class InternalPrincipalSeam:
    """Task-local principal used until OIDC sessions exist.

    ``attach`` stores the principal for the current context. ``current``
    returns it. There is no parameter for a request body.
    """

    def attach(self, principal: Principal) -> Token:
        if not isinstance(principal, Principal):
            raise TypeError("attach() accepts a backend Principal, not a request body")
        return _ATTACHED.set(principal)

    def detach(self, token: Token) -> None:
        _ATTACHED.reset(token)

    def current(self) -> Principal | None:
        """Return the principal attached in this context, if any."""
        return _ATTACHED.get()


def attached_principal() -> Principal | None:
    """Read the principal attached by any ``InternalPrincipalSeam`` in this task."""
    return _ATTACHED.get()


def reset_attached_principal() -> None:
    """Drop a leaked attachment. Test isolation calls this between cases."""
    _ATTACHED.set(None)

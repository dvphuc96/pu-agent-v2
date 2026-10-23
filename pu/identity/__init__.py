"""Backend identity for ADR-MU-001.

``user_id`` values are issued by the backend. The caller is the principal
on an authenticated OIDC session, or the worker grant for the current job.
"""

from pu.identity.principal import Principal, PrincipalKind

__all__ = ["Principal", "PrincipalKind"]

"""Backend identity for ADR-MU-001.

Phase 1 issues ``user_id`` values and resolves the caller through
``InternalPrincipalSeam``. Phase 6 removes ``pu.identity.seam`` and the
``principal_seam`` field; after that, the principal comes only from an
authenticated OIDC session.
"""

from pu.identity.principal import Principal, PrincipalKind

__all__ = ["Principal", "PrincipalKind"]

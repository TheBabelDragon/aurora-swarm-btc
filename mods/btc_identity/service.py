"""Back-compat: IdentityService is NodeIdentity."""
from .identity import IdentityService, NodeIdentity

__all__ = ["IdentityService", "NodeIdentity"]

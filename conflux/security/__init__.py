"""Conflux security — AEGIS-42 capability enforcement."""

from conflux.security.authorization import (
    CONFLUX_CAPABILITIES,
    AuthorizationResult,
    authorize_mutation,
    require_capability,
)

__all__ = [
    "CONFLUX_CAPABILITIES",
    "AuthorizationResult",
    "authorize_mutation",
    "require_capability",
]

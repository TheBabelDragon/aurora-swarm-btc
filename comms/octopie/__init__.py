"""Octopie integration boundary for Aurora.

Default: disabled / observe-only. Does not alter mesh admission behaviour
until explicitly enabled. Never imports the Octopie package.
"""

from .contract import CONTRACT_VERSION, DecisionOutcome, TrustOutcome
from .boundary import OctopieBoundary, BoundaryConfig

__all__ = [
    "CONTRACT_VERSION",
    "DecisionOutcome",
    "TrustOutcome",
    "OctopieBoundary",
    "BoundaryConfig",
]

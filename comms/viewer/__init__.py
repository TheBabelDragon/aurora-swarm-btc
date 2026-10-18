"""Aurora HTTPS Viewer — destination-access control plane for dashboard.

This is not an unrestricted network proxy and does not embed arbitrary remote
pages in the dashboard origin. It provides:

* HTTPS URL validation and SSRF/DNS-rebinding defenses
* Viewer sessions with bounded lifecycle
* An adapter over DestinationRoutingService + egress policy
* Optional loopback HTTP CONNECT proxy (127.0.0.1 only) for external browsers

TLS is never terminated or re-signed by Aurora. Public egress remains disabled
unless the operator explicitly enables authorized egress.
"""

from .url_policy import (
    ViewerUrlError,
    normalize_https_url,
    validate_resolved_addresses,
)
from .session import (
    ViewerSession,
    ViewerSessionState,
    ViewerSessionStore,
)
from .service import ViewerService, load_viewer_config, ViewerConfig

__all__ = [
    "ViewerUrlError",
    "normalize_https_url",
    "validate_resolved_addresses",
    "ViewerSession",
    "ViewerSessionState",
    "ViewerSessionStore",
    "ViewerService",
    "ViewerConfig",
    "load_viewer_config",
]

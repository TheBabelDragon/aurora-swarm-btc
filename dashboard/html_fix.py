"""Serve /ux/comms.js reliably (HTML already includes the panel)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from starlette.responses import Response

logger = logging.getLogger("aurora-dashboard.html_fix")


def install_html_fix(app: Any):
    @app.get("/ux/comms.js")
    def ux_comms_js():
        p = Path(__file__).resolve().parent / "ux_comms.js"
        try:
            return Response(
                content=p.read_text(encoding="utf-8"),
                media_type="application/javascript",
                headers={"Cache-Control": "no-store"},
            )
        except Exception as e:
            logger.error(f"ux_comms.js missing: {e}")
            return Response(
                content="console.error('ux_comms.js missing');",
                media_type="application/javascript",
            )

    logger.info("/ux/comms.js route installed")

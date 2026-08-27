"""Serve /ux/comms.js and /ux/mine.js."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from starlette.responses import Response

logger = logging.getLogger("aurora-dashboard.html_fix")


def _js(name: str) -> Response:
    p = Path(__file__).resolve().parent / name
    try:
        return Response(
            content=p.read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as e:
        logger.error("%s missing: %s", name, e)
        return Response(content="console.error('%s missing');" % name, media_type="application/javascript")


def install_html_fix(app: Any):
    @app.get("/ux/comms.js")
    def ux_comms_js():
        return _js("ux_comms.js")

    @app.get("/ux/mine.js")
    def ux_mine_js():
        return _js("ux_mine.js")

    logger.info("/ux/comms.js and /ux/mine.js installed")

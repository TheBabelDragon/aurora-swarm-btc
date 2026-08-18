"""Rewrite dashboard HTML/JS + inject Comms panel script."""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("aurora-dashboard.html_fix")


class StatusJsFixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path != "/":
            return response
        ctype = response.headers.get("content-type", "")
        if "text/html" not in ctype:
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            text = body.decode("utf-8", errors="ignore")
            if "${s.total_ths} TH/s" in text:
                text = text.replace(
                    "${s.total_ths} TH/s",
                    "${s.hashrate_display||(s.mining&&s.mining.hashrate_display)||'0 H/s'}",
                    1,
                )
            if "/bvl/reward_seed" in text:
                text = text.replace("fetch('/bvl/reward_seed'", "fetch('/mining/yearn'")
            if "/ux/comms.js" not in text and "</body>" in text:
                text = text.replace(
                    "</body>",
                    '<script src="/ux/comms.js"></script></body>',
                    1,
                )
            body = text.encode("utf-8")
        except Exception as e:
            logger.debug(f"html fix: {e}")
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )


def install_html_fix(app: Any):
    app.add_middleware(StatusJsFixMiddleware)

    @app.get("/ux/comms.js")
    def ux_comms_js():
        from pathlib import Path

        p = Path(__file__).resolve().parent / "ux_comms.js"
        try:
            return Response(content=p.read_text(), media_type="application/javascript")
        except Exception:
            return Response(content="/* missing */", media_type="application/javascript")

    logger.info("html_fix + comms.js installed")

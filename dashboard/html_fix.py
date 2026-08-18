"""Rewrite embedded dashboard JS so status uses hashrate_display (no TH/s-only flicker)."""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("aurora-dashboard.html_fix")

OLD = (
    "document.getElementById('status').innerHTML=`<div class=\"metric\">${s.active_workers} workers</div>"
    "<p>Entropy ${s.entropy} · ${s.total_ths} TH/s · ${s.mood}</p>`;"
)
# compact form as in file (with space before document)
OLD2 = (
    "document.getElementById('status').innerHTML=`<div class=\"metric\">${s.active_workers} workers</div>"
    "<p>Entropy ${s.entropy} · ${s.total_ths} TH/s · ${s.mood}</p>`;"
)
NEW = (
    "const rate=s.hashrate_display||(s.mining&&s.mining.hashrate_display)||'0 H/s';"
    "document.getElementById('status').innerHTML=`<div class=\"metric\">${s.active_workers} workers</div>"
    "<p>Entropy ${s.entropy} · ${rate} · ${s.mood}</p>`;"
)


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
            if "total_ths} TH/s" in text and "hashrate_display" not in text.split("getElementById('status')")[1][:200]:
                text = text.replace(
                    "${s.total_ths} TH/s",
                    "${s.hashrate_display||s.mining?.hashrate_display||(s.total_ths+' TH/s')}",
                    1,
                )
                body = text.encode("utf-8")
                logger.info("status JS hashrate_display rewrite applied")
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
    logger.info("html_fix middleware installed")

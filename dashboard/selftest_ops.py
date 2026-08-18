"""In-dashboard self-test — replaces any need for curl."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora-dashboard.selftest")


def install_selftest_ops(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_identity: Optional[Callable[[], Any]] = None,
):
    @app.get("/ops/selftest")
    def ops_selftest():
        results = []
        ok_all = True
        comms = get_comms()

        def check(name: str, fn):
            nonlocal ok_all
            try:
                detail = fn()
                results.append({"name": name, "ok": True, "detail": detail})
            except Exception as e:
                ok_all = False
                results.append({"name": name, "ok": False, "detail": str(e)})

        def redis():
            pong = comms.ping() if hasattr(comms, "ping") else bool(comms.r.ping())
            if not pong:
                raise RuntimeError("redis ping failed")
            return {"node_id": comms.node_id, "redis_url": getattr(comms, "redis_url", "")}

        def identity():
            from mods.btc_identity.identity import NodeIdentity

            ident = None
            if get_identity:
                try:
                    ident = get_identity()
                except Exception:
                    ident = None
            if not ident:
                ident = NodeIdentity(comms)
            view = ident.identity_view()
            ident.register_with_identity(capabilities=["dashboard", "btc_identity", "mesh", "chat"])
            return view

        def mesh_register():
            comms.register_node(
                node_type="dashboard",
                capabilities=["dashboard", "mesh", "chat", "mining_engine"],
                metadata={"status": "online", "selftest": True},
            )
            peers = comms.get_active_nodes() or []
            return {"peers": len(peers), "ids": [p.get("node_id") for p in peers[:12]]}

        def chat_roundtrip():
            from comms.chat import MeshChat

            c = MeshChat(comms)
            token = f"selftest-{int(time.time())}"
            out = c.send(token, to=None, room="swarm")
            if not out.get("ok"):
                raise RuntimeError(out.get("error") or "chat send failed")
            hist = c.history(room="swarm", limit=20)
            found = any(m.get("text") == token for m in hist)
            if not found:
                raise RuntimeError("message not in history")
            return {"sent": token, "history_len": len(hist)}

        def bvl():
            from mods.bvl.ledger_service import BabelLedger

            st = BabelLedger(comms).status()
            return {
                "balance": st.get("balance"),
                "supply": st.get("supply"),
                "accounts": len(st.get("balances_global") or {}),
            }

        check("redis", redis)
        check("identity", identity)
        check("mesh_register", mesh_register)
        check("chat_swarm", chat_roundtrip)
        check("bvl", bvl)

        return {
            "ok": ok_all,
            "ts": time.time(),
            "results": results,
            "hint": "All green means the UI is fully live — no terminal needed",
        }

    @app.post("/ops/bootstrap")
    async def ops_bootstrap():
        """One-click: identity + mesh + chat probe."""
        data = ops_selftest()
        return data

    logger.info("selftest_ops mounted")

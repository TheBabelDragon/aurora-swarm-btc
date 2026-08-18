"""Optional self-test — never posts to shared #swarm chat."""

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
            if not comms.ping():
                raise RuntimeError("redis ping failed")
            return {"node_id": comms.node_id}

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
            return ident.identity_view()

        def mesh_register():
            comms.register_node(
                node_type="dashboard",
                capabilities=["dashboard", "mesh", "chat", "mining_engine"],
                metadata={"status": "online"},
            )
            peers = comms.get_active_nodes() or []
            return {"peers": len(peers)}

        def chat_storage():
            """Probe Redis list write — do NOT touch shared swarm room."""
            key = f"aurora:chat:selftest:{comms.node_id}"
            token = f"t-{int(time.time())}"
            comms.r.rpush(key, token)
            comms.r.ltrim(key, -5, -1)
            got = comms.r.lrange(key, -1, -1)
            if not got or (got[-1] != token and got[-1] != token.encode()):
                # decode_responses may vary
                val = got[-1] if got else None
                if isinstance(val, bytes):
                    val = val.decode()
                if val != token:
                    raise RuntimeError("chat storage probe failed")
            return {"ok": True}

        def bvl():
            from mods.bvl.ledger_service import BabelLedger

            st = BabelLedger(comms).status()
            return {"balance": st.get("balance"), "supply": st.get("supply")}

        check("redis", redis)
        check("identity", identity)
        check("mesh_register", mesh_register)
        check("chat_storage", chat_storage)
        check("bvl", bvl)

        return {"ok": ok_all, "ts": time.time(), "results": results}

    @app.post("/ops/bootstrap")
    async def ops_bootstrap():
        # Quiet bootstrap: identity + mesh only, no chat spam
        out = {"ok": True, "steps": []}
        try:
            from mods.btc_identity.identity import NodeIdentity

            ident = NodeIdentity(get_comms())
            ident.register_with_identity(capabilities=["dashboard", "btc_identity", "mesh", "chat"])
            out["steps"].append({"identity": True})
        except Exception as e:
            out["ok"] = False
            out["steps"].append({"identity": False, "error": str(e)})
        try:
            get_comms().register_node(
                node_type="dashboard",
                capabilities=["dashboard", "mesh", "chat"],
                metadata={"status": "online"},
            )
            out["steps"].append({"mesh": True, "peers": len(get_comms().get_active_nodes() or [])})
        except Exception as e:
            out["ok"] = False
            out["steps"].append({"mesh": False, "error": str(e)})
        return out

    logger.info("selftest_ops mounted (quiet)")

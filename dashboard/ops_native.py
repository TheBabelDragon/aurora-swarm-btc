"""
Dashboard-native ops: fleet, BVL transfer, mining start/stop UI.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from fastapi import Form, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("aurora-dashboard.ops_native")

EXTRA_JS = r"""
(function(){
  function el(id){return document.getElementById(id)}
  function ensurePanels(){
    if(el('fleet_card')) return;
    const cards=document.querySelectorAll('.card');
    const host=cards[0];
    if(!host||!host.parentNode) return;
    const wrap=document.createElement('div');
    wrap.className='card';
    wrap.innerHTML='<h2>Mining</h2><div id="mine_status" class="muted">Checking miner…</div><div class="section"><button type="button" onclick="startMining()">Start mining</button><button type="button" class="danger" onclick="stopMining()">Stop mining</button></div><div id="mine_result" style="min-height:18px;margin-top:8px"></div><p class="muted">Pays out to <span class="mono" id="mine_wallet">MINING_WALLET</span> via pool auth (wallet.worker). Requires bfgminer on host or a mesh worker.</p><h2 style="margin-top:18px">Fleet</h2><div id="fleet_card" class="muted">No worker telemetry yet.</div><h2 style="margin-top:18px">BVL transfer</h2><p class="muted">Mesh credit only. Type recipient id twice. Optional: require known node.</p><div class="section"><input id="xfer_to" placeholder="to node id"><input id="xfer_confirm" placeholder="confirm node id"><input id="xfer_amount" type="number" step="any" min="0" placeholder="amount" style="width:120px"><input id="xfer_memo" placeholder="memo (optional)"><label class="muted"><input type="checkbox" id="xfer_known"> require known node</label><button type="button" onclick="bvlTransferSafe()">Transfer BVL</button></div><div id="xfer_result" style="min-height:18px;margin-top:8px"></div>';
    host.parentNode.insertBefore(wrap, host.nextSibling);
  }
  async function refreshFleet(){
    ensurePanels();
    try{
      const d=await fetch('/mining/engine/status').then(r=>r.json());
      const local=d.local||{};
      const w=local.wallet||'';
      if(el('mine_wallet')) el('mine_wallet').textContent=w?w:'(not set — export MINING_WALLET)';
      const parts=[];
      parts.push(w?('wallet '+w.slice(0,12)+'…'):'wallet not set');
      parts.push(local.backend_available?'bfgminer found':'bfgminer missing');
      parts.push(local.running?'RUNNING':'stopped');
      if(local.hashrate_ghs!=null) parts.push(local.hashrate_ghs+' GH/s');
      if(el('mine_status')) el('mine_status').textContent=parts.join(' · ');
      const nodes=d.workers||[];
      if(!nodes.length){
        el('fleet_card').textContent='No mining workers publishing yet.';
      } else {
        let h='<table><tr><th>Worker</th><th>GH/s</th><th>Intensity</th><th>Status</th></tr>';
        for(const n of nodes){
          const hr=n.hashrate_ghs;
          h+='<tr><td class="mono">'+(n.worker_id||'')+'</td><td>'+(hr==null?'—':hr)+'</td><td>'+(n.intensity||'—')+'</td><td>'+(n.paused?'paused':(n.running?'mining':'—'))+'</td></tr>';
        }
        h+='</table>';
        if(d.total_hashrate_ghs!=null) h+='<p class="muted">fleet total: '+d.total_hashrate_ghs+' GH/s</p>';
        el('fleet_card').innerHTML=h;
      }
    }catch(e){
      if(el('fleet_card')) el('fleet_card').textContent='Mining status unavailable';
      if(el('mine_status')) el('mine_status').textContent='status error';
    }
  }
  window.startMining=async function(){
    ensurePanels();
    const data=await fetch('/mining/engine/start',{method:'POST'}).then(r=>r.json());
    const ok=!!data.ok;
    let msg=ok?'Mining start issued':'Start failed';
    if(data.error) msg+=' — '+data.error;
    if(data.local&&data.local.error) msg+=' — local: '+data.local.error;
    if(data.wallet) msg+=' · wallet '+data.wallet.slice(0,14)+'…';
    const out=el('mine_result');
    out.textContent=msg;
    out.className=ok?'success':'error';
    setTimeout(refreshFleet,800);
  };
  window.stopMining=async function(){
    ensurePanels();
    const data=await fetch('/mining/engine/stop',{method:'POST'}).then(r=>r.json());
    const out=el('mine_result');
    out.textContent=data.ok?'Mining stop issued':(data.error||'stop failed');
    out.className=data.ok?'success':'error';
    setTimeout(refreshFleet,800);
  };
  window.bvlTransferSafe=async function(){
    ensurePanels();
    const to=(el('xfer_to').value||'').trim();
    const confirm=(el('xfer_confirm').value||'').trim();
    const amount=el('xfer_amount').value;
    const memo=(el('xfer_memo').value||'').trim();
    const known=el('xfer_known').checked;
    const fd=new FormData();
    fd.append('to_node',to);
    fd.append('confirm_to',confirm);
    fd.append('amount',amount);
    fd.append('memo',memo);
    if(known) fd.append('require_known','1');
    const data=await fetch('/bvl/transfer_safe',{method:'POST',body:fd}).then(r=>r.json());
    const ok=!!(data.ok||data.status==='ok');
    const msg=ok?('Transferred '+data.amount+' → '+data.to+' (fee '+(data.fee||0)+')'):(data.error||data.detail||'transfer failed');
    const out=el('xfer_result');
    out.textContent=msg;
    out.className=ok?'success':'error';
    if(ok && typeof refresh==='function') setTimeout(refresh,400);
  };
  ensurePanels();
  refreshFleet();
  setInterval(refreshFleet,5000);
})();
"""


class _InjectExtraJS(BaseHTTPMiddleware):
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
        if b"/ux/extra.js" not in body and b"</body>" in body:
            body = body.replace(
                b"</body>",
                b'<script src="/ux/extra.js"></script></body>',
                1,
            )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=ctype.split(";")[0] if ctype else "text/html",
        )


def install_ops_native(app: Any, *, get_comms: Callable[[], Any]):
    app.add_middleware(_InjectExtraJS)

    @app.get("/mesh/fleet")
    def mesh_fleet():
        comms = get_comms()
        nodes_out = []
        try:
            raw_nodes = comms.get_active_nodes() or []
        except Exception as e:
            return {"nodes": [], "error": str(e)}

        for n in raw_nodes:
            if not isinstance(n, dict):
                continue
            nid = n.get("node_id") or ""
            meta = n.get("metadata") or {}
            hr = meta.get("hashrate_ghs")
            try:
                st = comms.get_state(f"worker:{nid}:hashrate")
                if isinstance(st, dict) and st.get("hashrate_ghs") is not None:
                    hr = st.get("hashrate_ghs")
                    if not meta.get("status") and st.get("status"):
                        meta = {**meta, "status": st.get("status")}
            except Exception:
                pass
            nodes_out.append(
                {
                    "node_id": nid,
                    "node_type": n.get("node_type"),
                    "capabilities": n.get("capabilities") or [],
                    "hashrate_ghs": hr,
                    "status": meta.get("status"),
                    "intensity": meta.get("intensity"),
                    "pool": meta.get("pool"),
                    "ts": n.get("ts"),
                }
            )

        shares = None
        try:
            shares = comms.get_state("cluster:shares_accepted")
        except Exception:
            pass

        return {
            "nodes": nodes_out,
            "cluster_shares": shares,
            "ts": time.time(),
            "note": "hashrate only shown when a worker publishes it",
        }

    @app.post("/bvl/transfer_safe")
    async def bvl_transfer_safe(
        to_node: str = Form(...),
        confirm_to: str = Form(...),
        amount: float = Form(...),
        memo: str = Form(""),
        require_known: str = Form(""),
    ):
        to_node = (to_node or "").strip()
        confirm_to = (confirm_to or "").strip()
        if not to_node or to_node != confirm_to:
            return JSONResponse(
                {"ok": False, "error": "confirm_to must exactly match to_node"},
                status_code=400,
            )
        require = require_known in ("1", "true", "yes", "on")
        if require:
            try:
                known_ids = {
                    (n.get("node_id") or "")
                    for n in (get_comms().get_active_nodes() or [])
                    if isinstance(n, dict)
                }
            except Exception:
                known_ids = set()
            if to_node not in known_ids:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "recipient not in active mesh (require_known)",
                        "known": sorted(known_ids),
                    },
                    status_code=400,
                )
        try:
            from mods.bvl.ledger_service import BabelLedger

            return BabelLedger(get_comms()).transfer(to_node, float(amount), memo=memo)
        except Exception as e:
            logger.exception("transfer_safe")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/ux/extra.js")
    def ux_extra_js():
        return Response(content=EXTRA_JS, media_type="application/javascript")

    logger.info("ops_native routes installed")

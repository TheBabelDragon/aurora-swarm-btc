"""
Dashboard-native ops: fleet telemetry + controlled BVL transfer.

Security posture (mesh credit, not bank-grade):
- transfer requires explicit confirm_to matching to_node
- optional require_known: recipient must appear in active mesh nodes
- amount/memo validated; no silent self-transfer
- fleet card never invents hashrate — missing means not published
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from fastapi import Form
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("aurora-dashboard.ops_native")

EXTRA_JS = r"""
(function(){
  function el(id){return document.getElementById(id)}
  function ensurePanels(){
    if(el('fleet_card')) return;
    const host=document.querySelector('.card');
    if(!host) return;
    const wrap=document.createElement('div');
    wrap.className='card';
    wrap.innerHTML=`<h2>Fleet</h2>
<div id="fleet_card" class="muted">No worker telemetry yet — start a miner worker to publish hashrate.</div>
<h2 style="margin-top:18px">BVL transfer</h2>
<p class="muted">Mesh credit only. Confirm recipient id exactly. Optional: require known node.</p>
<div class="section">
<input id="xfer_to" placeholder="to node id">
<input id="xfer_confirm" placeholder="confirm node id">
<input id="xfer_amount" type="number" step="any" min="0" placeholder="amount" style="width:120px">
<input id="xfer_memo" placeholder="memo (optional)">
<label class="muted"><input type="checkbox" id="xfer_known"> require known node</label>
<button onclick="bvlTransferSafe()">Transfer BVL</button>
</div>
<div id="xfer_result" style="min-height:18px;margin-top:8px"></div>`;
    // insert after first status card
    host.parentNode.insertBefore(wrap, host.nextSibling);
  }
  async function refreshFleet(){
    ensurePanels();
    try{
      const d=await fetch('/mesh/fleet').then(r=>r.json());
      const nodes=d.nodes||[];
      if(!nodes.length){
        el('fleet_card').innerHTML='No active mesh nodes registered.';
        return;
      }
      let h='<table><tr><th>Node</th><th>Type</th><th>Caps</th><th>Hashrate</th><th>Status</th></tr>';
      for(const n of nodes){
        const hr=n.hashrate_ghs;
        const hrText=(hr==null||hr===undefined)?'—':(hr+' GH/s');
        h+=`<tr><td class="mono">${n.node_id||''}</td><td>${n.node_type||''}</td>
<td class="muted">${(n.capabilities||[]).join(', ')}</td>
<td>${hrText}</td><td>${n.status||'—'}</td></tr>`;
      }
      h+='</table>';
      if(d.cluster_shares!=null) h+=`<p class="muted">cluster shares accepted: ${d.cluster_shares}</p>`;
      el('fleet_card').innerHTML=h;
    }catch(e){
      if(el('fleet_card')) el('fleet_card').innerHTML='Fleet endpoint unavailable';
    }
  }
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
    const msg=ok?`Transferred ${data.amount} → ${data.to} (fee ${data.fee||0})`:(data.error||data.detail||'transfer failed');
    const out=el('xfer_result');
    out.innerText=msg;
    out.className=ok?'success':'error';
    if(ok && typeof refresh==='function') setTimeout(refresh,400);
  };
  ensurePanels();
  refreshFleet();
  setInterval(refreshFleet,5000);
})();
"""


def install_ops_native(app: Any, *, get_comms: Callable[[], Any]):
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
            # Prefer per-node published rate
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
                    "hashrate_ghs": hr,  # None if never published
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
                {
                    "ok": False,
                    "error": "confirm_to must exactly match to_node",
                },
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

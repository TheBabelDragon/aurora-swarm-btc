"""Dashboard ops UI — mining/yearn/jobs/fleet/BVL without curl."""

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
  function rateText(o){
    if(!o) return '—';
    if(o.hashrate_display) return o.hashrate_display;
    if(o.hashrate_hs!=null && o.hashrate_hs>0){
      const hs=o.hashrate_hs;
      if(hs>=1e12) return (hs/1e12).toFixed(3)+' TH/s';
      if(hs>=1e9) return (hs/1e9).toFixed(3)+' GH/s';
      if(hs>=1e6) return (hs/1e6).toFixed(2)+' MH/s';
      if(hs>=1e3) return (hs/1e3).toFixed(2)+' KH/s';
      return Math.round(hs)+' H/s';
    }
    if(o.hashrate_ghs!=null && o.hashrate_ghs>0) return o.hashrate_ghs+' GH/s';
    return '—';
  }
  function ensurePanels(){
    if(el('fleet_card')) return;
    const cards=document.querySelectorAll('.card');
    const host=cards[0];
    if(!host||!host.parentNode) return;
    const wrap=document.createElement('div');
    wrap.className='card';
    wrap.innerHTML=[
      '<h2>Mining</h2>',
      '<div id="mine_status" class="muted">Starting…</div>',
      '<div id="yearn_line" class="muted" style="margin-top:6px"></div>',
      '<div class="section" style="margin-top:10px">',
      '<button type="button" onclick="startMining()">Start mining</button>',
      '<button type="button" class="danger" onclick="stopMining()">Stop mining</button>',
      '</div>',
      '<div id="mine_result" style="min-height:18px;margin-top:8px"></div>',
      '<p class="muted">Wallet <span class="mono" id="mine_wallet">…</span> · auto-starts on boot</p>',
      '<h2 style="margin-top:18px">Jobs</h2>',
      '<div id="jobs_card" class="muted">Waiting for pool jobs…</div>',
      '<h2 style="margin-top:18px">Fleet</h2>',
      '<div id="fleet_card" class="muted">No workers yet.</div>',
      '<h2 style="margin-top:18px">BVL transfer</h2>',
      '<p class="muted">Mesh credit — type recipient twice</p>',
      '<div class="section">',
      '<input id="xfer_to" placeholder="to node id">',
      '<input id="xfer_confirm" placeholder="confirm node id">',
      '<input id="xfer_amount" type="number" step="any" min="0" placeholder="amount" style="width:120px">',
      '<input id="xfer_memo" placeholder="memo">',
      '<label class="muted"><input type="checkbox" id="xfer_known"> require known</label>',
      '<button type="button" onclick="bvlTransferSafe()">Transfer BVL</button>',
      '</div>',
      '<div id="xfer_result" style="min-height:18px;margin-top:8px"></div>'
    ].join('');
    host.parentNode.insertBefore(wrap, host.nextSibling);
  }
  async function refreshStatusCard(){
    try{
      const s=await fetch('/status').then(r=>r.json());
      const box=el('status');
      if(!box) return;
      const rate=s.hashrate_display||rateText(s.mining)||'0 H/s';
      const mine=s.mining||{};
      box.innerHTML='<div class="metric">'+(s.active_workers||0)+' workers</div><p>Entropy '+s.entropy+' · '+rate+' · '+(s.mood||'')+'</p><p class="muted">'+(mine.running?'mining · '+(mine.backend||'')+' · ':'idle · ')+(mine.hashrate_display||rate)+'</p>';
    }catch(e){}
  }
  async function refreshYearnJobs(){
    try{
      const y=await fetch('/mining/yearn').then(r=>r.json());
      if(el('yearn_line')) el('yearn_line').textContent=y.mood||'';
    }catch(e){}
    try{
      const j=await fetch('/mining/jobs?limit=5').then(r=>r.json());
      const st=j.stats||{};
      const items=j.items||[];
      let h='avg score '+(st.avg_score||0)+' · jobs '+(st.count||0);
      if(items.length){
        h+='<ul style="margin:8px 0 0 16px">';
        for(const it of items.slice(0,5)){
          h+='<li class="mono">'+(it.job_id||'?').toString().slice(0,12)+'… score '+(it.score||0)+'</li>';
        }
        h+='</ul>';
      }
      if(el('jobs_card')) el('jobs_card').innerHTML=h;
    }catch(e){
      if(el('jobs_card')) el('jobs_card').textContent='jobs unavailable';
    }
  }
  async function refreshFleet(){
    ensurePanels();
    await refreshStatusCard();
    await refreshYearnJobs();
    try{
      const d=await fetch('/mining/engine/status').then(r=>r.json());
      const local=d.local||{};
      const w=local.wallet||'';
      if(el('mine_wallet')) el('mine_wallet').textContent=w||'(default)';
      const parts=[];
      parts.push(w?('wallet '+w.slice(0,12)+'…'):'wallet default');
      parts.push(local.backend||'…');
      parts.push(local.running?'RUNNING':'stopped');
      parts.push(rateText(local));
      if(el('mine_status')) el('mine_status').textContent=parts.join(' · ');
      const nodes=d.workers||[];
      if(!nodes.length){
        el('fleet_card').textContent=local.running?'Local miner active (no remote workers)':'Waiting for hashrate…';
      } else {
        let h='<table><tr><th>Worker</th><th>Rate</th><th>Status</th></tr>';
        for(const n of nodes){
          h+='<tr><td class="mono">'+(n.worker_id||'')+'</td><td>'+rateText(n)+'</td><td>'+(n.running?'mining':'—')+'</td></tr>';
        }
        h+='</table>';
        el('fleet_card').innerHTML=h;
      }
      // If idle after boot, kick start once from the browser too
      if(!local.running && !window.__aurora_autostart_tried){
        window.__aurora_autostart_tried=true;
        startMining();
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
    let msg=ok?'Mining running':'Start failed';
    if(data.local&&data.local.backend) msg+=' · '+data.local.backend;
    if(data.wallet) msg+=' · '+(data.wallet.slice?data.wallet.slice(0,14)+'…':data.wallet);
    if(data.error) msg+=' — '+data.error;
    if(data.local&&data.local.error) msg+=' — '+data.local.error;
    const out=el('mine_result');
    if(out){ out.textContent=msg; out.className=ok?'success':'error'; }
    setTimeout(refreshFleet,1200);
  };
  window.stopMining=async function(){
    ensurePanels();
    const data=await fetch('/mining/engine/stop',{method:'POST'}).then(r=>r.json());
    const out=el('mine_result');
    if(out){
      out.textContent=data.ok?'Stopped':(data.error||'stop failed');
      out.className=data.ok?'success':'error';
    }
    setTimeout(refreshFleet,800);
  };
  window.bvlTransferSafe=async function(){
    ensurePanels();
    const fd=new FormData();
    fd.append('to_node',(el('xfer_to').value||'').trim());
    fd.append('confirm_to',(el('xfer_confirm').value||'').trim());
    fd.append('amount',el('xfer_amount').value);
    fd.append('memo',(el('xfer_memo').value||'').trim());
    if(el('xfer_known').checked) fd.append('require_known','1');
    const data=await fetch('/bvl/transfer_safe',{method:'POST',body:fd}).then(r=>r.json());
    const ok=!!(data.ok||data.status==='ok');
    const out=el('xfer_result');
    out.textContent=ok?('Transferred '+data.amount+' → '+data.to):(data.error||'failed');
    out.className=ok?'success':'error';
  };
  ensurePanels();
  refreshFleet();
  setInterval(refreshFleet,4000);
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
            hr_disp = meta.get("hashrate_display")
            hr_hs = meta.get("hashrate_hs")
            try:
                st = comms.get_state(f"worker:{nid}:hashrate")
                if isinstance(st, dict):
                    if st.get("hashrate_ghs") is not None:
                        hr = st.get("hashrate_ghs")
                    if st.get("hashrate_display"):
                        hr_disp = st.get("hashrate_display")
                    if st.get("hashrate_hs") is not None:
                        hr_hs = st.get("hashrate_hs")
            except Exception:
                pass
            nodes_out.append(
                {
                    "node_id": nid,
                    "hashrate_ghs": hr,
                    "hashrate_hs": hr_hs,
                    "hashrate_display": hr_disp,
                    "status": meta.get("status"),
                }
            )
        return {"nodes": nodes_out, "ts": time.time()}

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
            return JSONResponse({"ok": False, "error": "confirm must match"}, status_code=400)
        try:
            from mods.bvl.ledger_service import BabelLedger

            return BabelLedger(get_comms()).transfer(to_node, float(amount), memo=memo)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/ux/extra.js")
    def ux_extra_js():
        return Response(content=EXTRA_JS, media_type="application/javascript")

    logger.info("ops_native installed")

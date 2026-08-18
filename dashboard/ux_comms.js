(function(){
  function el(id){return document.getElementById(id)}
  function ensureComms(){
    if(el('comms_card')) return;
    const cards=document.querySelectorAll('.card');
    const host=cards[0];
    if(!host||!host.parentNode) return;
    const wrap=document.createElement('div');
    wrap.className='card';
    wrap.innerHTML='<h2>Comms Layer</h2><div id="comms_card" class="muted">Connecting…</div><div class="section" style="margin-top:8px"><button type="button" onclick="commsRegister()">Register on mesh</button><button type="button" onclick="commsBroadcast()">Broadcast test</button></div><div id="comms_result" style="min-height:18px;margin-top:8px"></div><p class="muted">Shared <span class="mono">REDIS_URL</span> is the swarm. Peers only appear when Redis is shared.</p>';
    host.parentNode.insertBefore(wrap, host);
  }
  async function refreshComms(){
    ensureComms();
    try{
      const d=await fetch('/comms/status').then(r=>r.json());
      const peers=d.peers||[];
      let h='<p><strong>'+(d.redis_ok?'Redis OK':'Redis DOWN')+'</strong> · node <span class="mono">'+(d.node_id||'')+'</span></p>';
      h+='<p class="muted">'+ (d.redis_url||'') +'</p>';
      h+='<p>Peers: <strong>'+(d.peer_count||0)+'</strong> · global compute: <strong>'+(d.global_hashrate_display||'0 H/s')+'</strong></p>';
      if(peers.length){
        h+='<table><tr><th>Node</th><th>Type</th><th>Caps</th></tr>';
        for(const p of peers){
          h+='<tr><td class="mono">'+(p.node_id||'')+'</td><td>'+(p.node_type||'')+'</td><td class="muted">'+((p.capabilities||[]).slice(0,4).join(', '))+'</td></tr>';
        }
        h+='</table>';
      }
      el('comms_card').innerHTML=h;
    }catch(e){
      if(el('comms_card')) el('comms_card').textContent='Comms unavailable';
    }
  }
  window.commsRegister=async function(){
    const d=await fetch('/comms/register',{method:'POST'}).then(r=>r.json());
    const out=el('comms_result');
    if(out){ out.textContent=d.ok?('Registered · peers '+(d.peers||0)):(d.error||'fail'); out.className=d.ok?'success':'error'; }
    refreshComms();
  };
  window.commsBroadcast=async function(){
    const fd=new FormData(); fd.append('message','ping from '+location.hostname+' @ '+Date.now());
    const d=await fetch('/comms/broadcast',{method:'POST',body:fd}).then(r=>r.json());
    const out=el('comms_result');
    if(out){ out.textContent=d.ok?'Broadcast sent':(d.error||'fail'); out.className=d.ok?'success':'error'; }
  };
  ensureComms();
  refreshComms();
  setInterval(refreshComms,5000);
})();

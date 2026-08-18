(function(){
  function el(id){return document.getElementById(id)}
  function ensureComms(){
    if(el('comms_card')) return;
    const cards=document.querySelectorAll('.card');
    const host=cards[0];
    if(!host||!host.parentNode) return;
    const wrap=document.createElement('div');
    wrap.className='card';
    wrap.innerHTML=[
      '<h2>Comms Layer</h2>',
      '<div id="comms_card" class="muted">Connecting…</div>',
      '<div class="section" style="margin-top:8px">',
      '<button type="button" onclick="commsRegister()">Register on mesh</button>',
      '<button type="button" onclick="commsBroadcast()">Broadcast test</button>',
      '<button type="button" onclick="commsExport()">Export join pack</button>',
      '<a href="/comms/export.env" download="aurora-mesh.env"><button type="button">Download .env</button></a>',
      '<a href="/comms/export.sh" download="join-aurora-mesh.sh"><button type="button">Download join.sh</button></a>',
      '</div>',
      '<pre id="comms_export" class="mono muted" style="max-height:160px;overflow:auto;margin-top:8px;white-space:pre-wrap"></pre>',
      '<div id="comms_result" style="min-height:18px;margin-top:8px"></div>',
      '<p class="muted">UDP discovery + shared Redis. Export gives the other machine everything.</p>'
    ].join('');
    host.parentNode.insertBefore(wrap, host);
  }
  async function refreshComms(){
    ensureComms();
    try{
      const d=await fetch('/comms/status').then(r=>r.json());
      const peers=d.peers||[];
      const lan=d.lan_discovered||[];
      let h='<p><strong>'+(d.redis_ok?'Redis OK':'Redis DOWN')+'</strong> · node <span class="mono">'+(d.node_id||'')+'</span></p>';
      h+='<p class="muted">'+ (d.redis_url||'') +' · discovery :'+(d.discovery_port||7379)+'</p>';
      h+='<p>Redis peers: <strong>'+(d.peer_count||0)+'</strong> · LAN beacons: <strong>'+(d.lan_count||0)+'</strong> · global: <strong>'+(d.global_hashrate_display||'0 H/s')+'</strong></p>';
      if(peers.length){
        h+='<p class="muted">Mesh registry</p><table><tr><th>Node</th><th>Type</th><th>Caps</th></tr>';
        for(const p of peers){
          h+='<tr><td class="mono">'+(p.node_id||'')+'</td><td>'+(p.node_type||'')+'</td><td class="muted">'+((p.capabilities||[]).slice(0,4).join(', '))+'</td></tr>';
        }
        h+='</table>';
      }
      if(lan.length){
        h+='<p class="muted">LAN discovery</p><table><tr><th>Node</th><th>From</th><th>REDIS_URL</th></tr>';
        for(const p of lan){
          h+='<tr><td class="mono">'+(p.node_id||'')+'</td><td>'+(p.from_ip||'')+'</td><td class="mono muted">'+(p.redis_url||'')+'</td></tr>';
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
  window.commsExport=async function(){
    const d=await fetch('/comms/export').then(r=>r.json());
    const box=el('comms_export');
    if(box){
      box.textContent=d.env_export||JSON.stringify(d,null,2);
    }
    const out=el('comms_result');
    if(out){ out.textContent=d.REDIS_URL?('Join URL '+d.REDIS_URL):'export failed'; out.className=d.REDIS_URL?'success':'error'; }
  };
  ensureComms();
  refreshComms();
  setInterval(refreshComms,5000);
})();

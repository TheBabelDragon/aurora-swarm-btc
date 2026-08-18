(function(){
  let chatTarget = null; // null = swarm room
  let lastHistSig = '';

  function el(id){return document.getElementById(id)}
  function esc(s){
    return String(s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

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
      '<button type="button" onclick="commsExport()">Export join pack</button>',
      '<a href="/comms/export.env" download="aurora-mesh.env"><button type="button">Download .env</button></a>',
      '<a href="/comms/export.sh" download="join-aurora-mesh.sh"><button type="button">Download join.sh</button></a>',
      '</div>',
      '<pre id="comms_export" class="mono muted" style="max-height:100px;overflow:auto;margin-top:8px;white-space:pre-wrap"></pre>',
      '<div id="comms_result" style="min-height:18px;margin-top:6px"></div>',

      '<h2 style="margin-top:18px">Mesh Chat</h2>',
      '<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:stretch">',
      '  <div style="min-width:180px;flex:0 0 200px">',
      '    <input id="chat_search" placeholder="Search users…" style="width:100%;margin-bottom:6px" oninput="refreshChatUsers()">',
      '    <div id="chat_users" class="muted" style="max-height:220px;overflow:auto;border:1px solid #333;border-radius:6px;padding:6px">Loading…</div>',
      '    <div style="margin-top:8px">',
      '      <input id="chat_external" placeholder="External node id" style="width:100%;margin-bottom:4px">',
      '      <button type="button" class="small" onclick="chatAddExternal()">Add / open</button>',
      '    </div>',
      '  </div>',
      '  <div style="flex:1;min-width:240px;display:flex;flex-direction:column">',
      '    <div id="chat_title" class="muted" style="margin-bottom:4px">#swarm (everyone on shared Redis)</div>',
      '    <div id="chat_log" style="flex:1;min-height:200px;max-height:280px;overflow:auto;border:1px solid #333;border-radius:6px;padding:8px;background:#0b0b0b"></div>',
      '    <div class="section" style="margin-top:8px;display:flex;gap:6px">',
      '      <input id="chat_text" placeholder="Message…" style="flex:1" onkeydown="if(event.key===\'Enter\'){chatSend();}">',
      '      <button type="button" onclick="chatSend()">Send</button>',
      '    </div>',
      '  </div>',
      '</div>',
      '<p class="muted" style="margin-top:8px">Select a peer for DM, or stay on #swarm. External ids work once both share Redis.</p>'
    ].join('');
    host.parentNode.insertBefore(wrap, host);
  }

  async function refreshComms(){
    ensureComms();
    try{
      const d=await fetch('/comms/status').then(r=>r.json());
      let h='<p><strong>'+(d.redis_ok?'Redis OK':'Redis DOWN')+'</strong> · <span class="mono">'+(d.node_id||'')+'</span></p>';
      h+='<p class="muted">'+(d.redis_url||'')+' · discovery :'+(d.discovery_port||7379)+'</p>';
      h+='<p>Peers <strong>'+(d.peer_count||0)+'</strong> · LAN <strong>'+(d.lan_count||0)+'</strong> · global <strong>'+(d.global_hashrate_display||'0 H/s')+'</strong></p>';
      el('comms_card').innerHTML=h;
    }catch(e){
      if(el('comms_card')) el('comms_card').textContent='Comms unavailable';
    }
  }

  window.refreshChatUsers=async function(){
    ensureComms();
    const q=(el('chat_search')&&el('chat_search').value)||'';
    try{
      const d=await fetch('/comms/chat/users?q='+encodeURIComponent(q)).then(r=>r.json());
      const box=el('chat_users');
      if(!box) return;
      const users=d.users||[];
      let h='<div style="margin-bottom:4px"><button type="button" class="small" onclick="chatSelect(null)">#swarm</button></div>';
      for(const u of users){
        if(u.source==='self') continue;
        const on=u.online?'●':'○';
        const cls=chatTarget===u.node_id?'success':'';
        h+='<div style="padding:4px 2px;cursor:pointer" class="'+cls+'" onclick="chatSelect(\''+esc(u.node_id).replace(/'/g,"\\'")+'\')">'+
           '<span class="mono">'+on+' '+esc(u.node_id)+'</span>'+
           '<div class="muted" style="font-size:11px">'+esc(u.source)+(u.from_ip?(' · '+u.from_ip):'')+'</div></div>';
      }
      if(users.filter(u=>u.source!=='self').length===0) h+='<div class="muted">No peers yet — share Redis or export join pack</div>';
      box.innerHTML=h;
    }catch(e){
      if(el('chat_users')) el('chat_users').textContent='users unavailable';
    }
  };

  window.chatSelect=function(nodeId){
    chatTarget=nodeId||null;
    if(el('chat_title')){
      el('chat_title').textContent=chatTarget?('DM → '+chatTarget):'#swarm (everyone on shared Redis)';
    }
    lastHistSig='';
    refreshChatHistory();
    refreshChatUsers();
  };

  window.chatAddExternal=async function(){
    const nid=((el('chat_external')&&el('chat_external').value)||'').trim();
    if(!nid) return;
    const fd=new FormData(); fd.append('node_id',nid);
    await fetch('/comms/chat/add_user',{method:'POST',body:fd});
    chatSelect(nid);
    if(el('chat_external')) el('chat_external').value='';
  };

  async function refreshChatHistory(){
    ensureComms();
    const url=chatTarget
      ?('/comms/chat/history?with_user='+encodeURIComponent(chatTarget)+'&limit=100')
      :('/comms/chat/history?room=swarm&limit=100');
    try{
      const d=await fetch(url).then(r=>r.json());
      const msgs=d.messages||[];
      const sig=msgs.length+':'+(msgs.length?msgs[msgs.length-1].id:'');
      if(sig===lastHistSig) return;
      lastHistSig=sig;
      const log=el('chat_log');
      if(!log) return;
      const me=d.me||'';
      let h='';
      for(const m of msgs){
        const mine=m.from===me;
        const who=mine?'you':esc(m.from);
        const t=m.ts?new Date(m.ts*1000).toLocaleTimeString():'';
        h+='<div style="margin:4px 0;'+(mine?'text-align:right':'')+'">'+'
           '<span class="muted" style="font-size:11px">'+who+' · '+t+'</span><br>'+
           '<span style="display:inline-block;padding:4px 8px;border-radius:8px;background:'+(mine?'#1a3a2a':'#1a1a2a')+'">'+esc(m.text)+'</span></div>';
      }
      if(!msgs.length) h='<div class="muted">No messages yet — say hi</div>';
      log.innerHTML=h;
      log.scrollTop=log.scrollHeight;
    }catch(e){}
  }

  window.chatSend=async function(){
    const input=el('chat_text');
    const text=((input&&input.value)||'').trim();
    if(!text) return;
    const fd=new FormData();
    fd.append('text',text);
    if(chatTarget) fd.append('to',chatTarget);
    else fd.append('room','swarm');
    const d=await fetch('/comms/chat/send',{method:'POST',body:fd}).then(r=>r.json());
    if(input) input.value='';
    lastHistSig='';
    if(d.ok) refreshChatHistory();
    else if(el('comms_result')){ el('comms_result').textContent=d.error||'send failed'; el('comms_result').className='error'; }
  };

  window.commsRegister=async function(){
    const d=await fetch('/comms/register',{method:'POST'}).then(r=>r.json());
    const out=el('comms_result');
    if(out){ out.textContent=d.ok?('Registered · peers '+(d.peers||0)):(d.error||'fail'); out.className=d.ok?'success':'error'; }
    refreshComms(); refreshChatUsers();
  };
  window.commsExport=async function(){
    const d=await fetch('/comms/export').then(r=>r.json());
    if(el('comms_export')) el('comms_export').textContent=d.env_export||JSON.stringify(d,null,2);
    const out=el('comms_result');
    if(out){ out.textContent=d.REDIS_URL?('Join URL '+d.REDIS_URL):'export failed'; out.className=d.REDIS_URL?'success':'error'; }
  };

  ensureComms();
  refreshComms();
  refreshChatUsers();
  refreshChatHistory();
  setInterval(refreshComms,5000);
  setInterval(refreshChatUsers,4000);
  setInterval(refreshChatHistory,2000);
})();

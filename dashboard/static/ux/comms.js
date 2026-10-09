/* Aurora dashboard comms + destination routing helpers */
async function _j(url, opts, ms) {
  ms = ms || 5000;
  var c = new AbortController();
  var t = setTimeout(function () { c.abort(); }, ms);
  try {
    var r = await fetch(url, Object.assign({}, opts || {}, { signal: c.signal }));
    return await r.json();
  } finally { clearTimeout(t); }
}
async function commsRegister() {
  var r = document.getElementById('comms_result');
  try {
    var d = await _j('/comms/register', { method: 'POST' }, 5000);
    if (r) { r.textContent = d.ok ? ('registered ' + d.node_id + ' · peers ' + (d.peers || 0)) : (d.error || 'fail'); r.className = d.ok ? 'success' : 'error'; }
  } catch (e) { if (r) { r.textContent = String(e); r.className = 'error'; } }
}
async function commsExport() {
  var pre = document.getElementById('comms_export');
  try {
    var d = await _j('/comms/export', {}, 5000);
    if (pre) pre.textContent = JSON.stringify(d, null, 2);
  } catch (e) { if (pre) pre.textContent = String(e); }
}
async function chatSend() {
  var input = document.getElementById('chat_text');
  var text = (input && input.value) || '';
  if (!text.trim()) return;
  try {
    await _j('/comms/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    }, 5000);
    if (input) input.value = '';
  } catch (e) {}
}
async function refreshChatUsers() {
  var box = document.getElementById('chat_users');
  if (!box) return;
  try {
    var q = (document.getElementById('chat_search') && document.getElementById('chat_search').value) || '';
    var d = await _j('/comms/chat/users?q=' + encodeURIComponent(q), {}, 4000);
    var users = d.users || [];
    box.innerHTML = users.length ? users.map(function (u) {
      var id = u.node_id || u.id || u;
      return '<div class="mono" style="cursor:pointer;padding:2px 0" onclick="chatOpen(\'' + id + '\')">' + id + '</div>';
    }).join('') : '<span class="muted">No users yet</span>';
  } catch (e) { box.textContent = 'chat users unavailable'; }
}
function chatOpen(id) {
  var t = document.getElementById('chat_title');
  if (t) t.textContent = '@' + id;
  window._chatPeer = id;
}
async function chatAddExternal() {
  var el = document.getElementById('chat_external');
  var nid = (el && el.value || '').trim();
  if (!nid) return;
  var fd = new FormData();
  fd.append('node_id', nid);
  try {
    await fetch('/comms/chat/add_user', { method: 'POST', body: fd });
    chatOpen(nid);
    refreshChatUsers();
  } catch (e) {}
}
async function routeResolve() {
  var t = (document.getElementById('route_target') && document.getElementById('route_target').value || '').trim();
  var out = document.getElementById('routing_out');
  if (!t) { if (out) out.textContent = 'target required'; return; }
  try {
    var d = await _j('/comms/destinations/resolve?target=' + encodeURIComponent(t), {}, 5000);
    if (out) { out.textContent = JSON.stringify(d, null, 2); out.className = 'mono ' + (d.ok || d.resolved ? 'success' : 'error'); }
  } catch (e) { if (out) { out.textContent = 'resolve failed: ' + e; out.className = 'mono error'; } }
}
async function routeList() {
  var t = (document.getElementById('route_target') && document.getElementById('route_target').value || '').trim();
  var q = t ? ('?target=' + encodeURIComponent(t)) : '';
  var out = document.getElementById('routing_out');
  try { var d = await _j('/comms/routes' + q, {}, 5000); if (out) out.textContent = JSON.stringify(d, null, 2); }
  catch (e) { if (out) out.textContent = 'routes failed: ' + e; }
}
async function routeGateways() {
  var out = document.getElementById('routing_out');
  try { var d = await _j('/comms/gateways', {}, 5000); if (out) out.textContent = JSON.stringify(d, null, 2); }
  catch (e) { if (out) out.textContent = 'gateways failed: ' + e; }
}
async function routeNetStatus() {
  var el = document.getElementById('routing_status');
  var out = document.getElementById('routing_out');
  try {
    var d = await _j('/comms/network/status', {}, 4000);
    if (el) {
      var on = !!d.routing_enabled;
      el.className = on ? 'success' : 'muted';
      el.textContent = on
        ? ('Routing ON · egress ' + (d.egress && d.egress.enabled ? 'on' : 'off') + ' · relay ' + (d.egress && d.egress.relay_implemented ? 'yes' : 'not implemented'))
        : 'Routing service ready (mesh resolve/send available)';
    }
    if (out) out.textContent = JSON.stringify(d, null, 2);
  } catch (e) { if (el) { el.className = 'error'; el.textContent = 'routing status unreachable'; } }
}
async function routeSend() {
  var t = (document.getElementById('route_target') && document.getElementById('route_target').value || '').trim();
  var msg = (document.getElementById('route_msg') && document.getElementById('route_msg').value || '').trim() || 'ping';
  var out = document.getElementById('routing_out');
  if (!t) { if (out) out.textContent = 'target required'; return; }
  try {
    var d = await _j('/comms/route_send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: t, payload: { text: msg } })
    }, 8000);
    if (out) { out.textContent = JSON.stringify(d, null, 2); out.className = 'mono ' + (d.ok ? 'success' : 'error'); }
  } catch (e) { if (out) { out.textContent = 'send failed: ' + e; out.className = 'mono error'; } }
}
document.addEventListener('DOMContentLoaded', function () {
  if (document.getElementById('routing_status')) {
    routeNetStatus();
    setInterval(routeNetStatus, 15000);
  }
  if (document.getElementById('chat_users')) refreshChatUsers();
});

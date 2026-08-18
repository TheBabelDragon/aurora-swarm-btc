/* Mesh Comms + Chat — panel is in home_template.html */
(function () {
  var chatTarget = null;
  var lastHistSig = "";

  function el(id) {
    return document.getElementById(id);
  }
  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  window.refreshComms = async function () {
    try {
      var d = await fetch("/comms/status").then(function (r) {
        return r.json();
      });
      var h =
        "<p><strong>" +
        (d.redis_ok ? "Redis OK" : "Redis DOWN") +
        "</strong> · <span class=\"mono\">" +
        esc(d.node_id) +
        "</span></p>";
      h += "<p class=\"muted\">" + esc(d.redis_url || "") + " · discovery :" + (d.discovery_port || 7379) + "</p>";
      h +=
        "<p>Peers <strong>" +
        (d.peer_count || 0) +
        "</strong> · LAN <strong>" +
        (d.lan_count || 0) +
        "</strong> · global <strong>" +
        esc(d.global_hashrate_display || "0 H/s") +
        "</strong></p>";
      var c = el("comms_card");
      if (c) c.innerHTML = h;
    } catch (e) {
      var c2 = el("comms_card");
      if (c2) c2.textContent = "Comms API offline — git pull && rebuild";
    }
  };

  window.refreshChatUsers = async function () {
    var q = (el("chat_search") && el("chat_search").value) || "";
    try {
      var d = await fetch("/comms/chat/users?q=" + encodeURIComponent(q)).then(function (r) {
        return r.json();
      });
      var box = el("chat_users");
      if (!box) return;
      var users = d.users || [];
      var h = '<div style="margin-bottom:4px"><button type="button" class="small" onclick="chatSelect(null)">#swarm</button></div>';
      for (var i = 0; i < users.length; i++) {
        var u = users[i];
        if (u.source === "self") continue;
        var on = u.online ? "●" : "○";
        var id = esc(u.node_id);
        h +=
          '<div style="padding:4px 2px;cursor:pointer" class="chat-user" data-nid="' +
          id +
          '"><span class="mono">' +
          on +
          " " +
          id +
          '</span><div class="muted" style="font-size:11px">' +
          esc(u.source) +
          (u.from_ip ? " · " + esc(u.from_ip) : "") +
          "</div></div>";
      }
      if (!users.filter(function (u) {
        return u.source !== "self";
      }).length)
        h += '<div class="muted">No peers yet — Export join pack</div>';
      box.innerHTML = h;
      var nodes = box.querySelectorAll(".chat-user");
      for (var j = 0; j < nodes.length; j++) {
        nodes[j].onclick = (function (n) {
          return function () {
            chatSelect(n.getAttribute("data-nid"));
          };
        })(nodes[j]);
      }
    } catch (e) {
      var b = el("chat_users");
      if (b) b.textContent = "chat users API offline";
    }
  };

  window.chatSelect = function (nodeId) {
    chatTarget = nodeId || null;
    var t = el("chat_title");
    if (t) t.textContent = chatTarget ? "DM → " + chatTarget : "#swarm";
    lastHistSig = "";
    refreshChatHistory();
    refreshChatUsers();
  };

  window.chatAddExternal = async function () {
    var nid = ((el("chat_external") && el("chat_external").value) || "").trim();
    if (!nid) return;
    var fd = new FormData();
    fd.append("node_id", nid);
    await fetch("/comms/chat/add_user", { method: "POST", body: fd });
    chatSelect(nid);
    if (el("chat_external")) el("chat_external").value = "";
  };

  window.refreshChatHistory = async function () {
    var url = chatTarget
      ? "/comms/chat/history?with_user=" + encodeURIComponent(chatTarget) + "&limit=100"
      : "/comms/chat/history?room=swarm&limit=100";
    try {
      var d = await fetch(url).then(function (r) {
        return r.json();
      });
      var msgs = d.messages || [];
      var sig = msgs.length + ":" + (msgs.length ? msgs[msgs.length - 1].id : "");
      if (sig === lastHistSig) return;
      lastHistSig = sig;
      var log = el("chat_log");
      if (!log) return;
      var me = d.me || "";
      var h = "";
      for (var i = 0; i < msgs.length; i++) {
        var m = msgs[i];
        var mine = m.from === me;
        var who = mine ? "you" : esc(m.from);
        var tm = m.ts ? new Date(m.ts * 1000).toLocaleTimeString() : "";
        h +=
          '<div style="margin:4px 0;' +
          (mine ? "text-align:right" : "") +
          '"><span class="muted" style="font-size:11px">' +
          who +
          " · " +
          tm +
          '</span><br><span style="display:inline-block;padding:4px 8px;border-radius:8px;background:' +
          (mine ? "#1a3a2a" : "#1a1a2a") +
          '">' +
          esc(m.text) +
          "</span></div>";
      }
      if (!msgs.length) h = '<div class="muted">No messages yet — say hi</div>';
      log.innerHTML = h;
      log.scrollTop = log.scrollHeight;
    } catch (e) {}
  };

  window.chatSend = async function () {
    var input = el("chat_text");
    var text = ((input && input.value) || "").trim();
    if (!text) return;
    var fd = new FormData();
    fd.append("text", text);
    if (chatTarget) fd.append("to", chatTarget);
    else fd.append("room", "swarm");
    var d = await fetch("/comms/chat/send", { method: "POST", body: fd }).then(function (r) {
      return r.json();
    });
    if (input) input.value = "";
    lastHistSig = "";
    if (d.ok) refreshChatHistory();
    else {
      var o = el("comms_result");
      if (o) {
        o.textContent = d.error || "send failed";
        o.className = "error";
      }
    }
  };

  window.commsRegister = async function () {
    var d = await fetch("/comms/register", { method: "POST" }).then(function (r) {
      return r.json();
    });
    var o = el("comms_result");
    if (o) {
      o.textContent = d.ok ? "Registered · peers " + (d.peers || 0) : d.error || "fail";
      o.className = d.ok ? "success" : "error";
    }
    refreshComms();
    refreshChatUsers();
  };

  window.commsExport = async function () {
    var d = await fetch("/comms/export").then(function (r) {
      return r.json();
    });
    var x = el("comms_export");
    if (x) x.textContent = d.env_export || JSON.stringify(d, null, 2);
    var o = el("comms_result");
    if (o) {
      o.textContent = d.REDIS_URL ? "Join URL " + d.REDIS_URL : "export failed";
      o.className = d.REDIS_URL ? "success" : "error";
    }
  };

  function boot() {
    refreshComms();
    refreshChatUsers();
    refreshChatHistory();
    setInterval(refreshComms, 5000);
    setInterval(refreshChatUsers, 4000);
    setInterval(refreshChatHistory, 2000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

/* Mesh Comms + shared LAN chat — hardened fetches */
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

  /** Fetch with timeout — never hang the UI on bad resolves */
  async function fetchT(url, opts, ms) {
    ms = ms || 8000;
    var ctrl = new AbortController();
    var t = setTimeout(function () {
      ctrl.abort();
    }, ms);
    try {
      var res = await fetch(url, Object.assign({}, opts || {}, { signal: ctrl.signal }));
      return res;
    } finally {
      clearTimeout(t);
    }
  }
  async function jget(url, ms) {
    var r = await fetchT(url, {}, ms || 8000);
    return r.json();
  }
  async function jpost(url, body, ms) {
    var r = await fetchT(
      url,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      ms || 10000
    );
    return r.json();
  }

  window.refreshComms = async function () {
    try {
      var d = await jget("/comms/status", 6000);
      var shared =
        d.redis_ok && (d.peer_count || 0) + (d.lan_count || 0) > 0
          ? " · <strong>shared LAN window</strong>"
          : "";
      var h =
        "<p><strong>" +
        (d.redis_ok ? "Redis OK" : "Redis DOWN") +
        "</strong> · <span class=\"mono\">" +
        esc(d.node_id) +
        "</span>" +
        shared +
        "</p>";
      h += "<p class=\"muted\">" + esc(d.redis_url || "") + " · discovery :" + (d.discovery_port || 7379) + "</p>";
      h +=
        "<p>Peers <strong>" +
        (d.peer_count || 0) +
        "</strong> · LAN <strong>" +
        (d.lan_count || 0) +
        "</strong> · global <strong>" +
        esc(d.global_hashrate_display || "idle") +
        "</strong></p>";
      if (d.redis_ok)
        h +=
          '<p class="muted">#swarm is one shared log for every node on this Redis. Export join pack so peers share it.</p>';
      var c = el("comms_card");
      if (c) c.innerHTML = h;
      var title = el("chat_title");
      if (title && !chatTarget)
        title.textContent =
          "#swarm · shared LAN room · " + (d.peer_count || 0) + " mesh peer(s)";
    } catch (e) {
      var c2 = el("comms_card");
      if (c2)
        c2.innerHTML =
          '<span class="error">Comms slow/unreachable — will retry</span>';
    }
  };

  window.refreshChatUsers = async function () {
    var q = (el("chat_search") && el("chat_search").value) || "";
    try {
      var d = await jget("/comms/chat/users?q=" + encodeURIComponent(q), 6000);
      var box = el("chat_users");
      if (!box) return;
      var users = d.users || [];
      var h =
        '<div style="margin-bottom:4px"><button type="button" class="small" onclick="chatSelect(null)">#swarm (shared)</button></div>';
      for (var i = 0; i < users.length; i++) {
        var u = users[i];
        if (u.source === "self") continue;
        var on = u.online ? "●" : "○";
        var id = esc(u.node_id);
        var sel = chatTarget === u.node_id ? ' style="background:#1a3a1a"' : "";
        h +
          '';
        h +=
          '<div style="padding:4px 2px;cursor:pointer" class="chat-user" data-nid="' +
          id +
          '"' +
          sel +
          '><span class="mono">' +
          on +
          " " +
          id +
          '</span><div class="muted" style="font-size:11px">' +
          esc(u.source) +
          (u.from_ip ? " · " + esc(u.from_ip) : "") +
          "</div></div>";
      }
      if (
        !users.filter(function (u) {
          return u.source !== "self";
        }).length
      )
        h +=
          '<div class="muted">Only you here — other LAN nodes must use same Redis (Download .env / join.sh)</div>';
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
      if (b) b.innerHTML = '<span class="error">users timeout — retrying</span>';
    }
  };

  window.chatSelect = function (nodeId) {
    chatTarget = nodeId || null;
    var t = el("chat_title");
    if (t)
      t.textContent = chatTarget
        ? "DM → " + chatTarget
        : "#swarm · shared LAN room";
    lastHistSig = "";
    refreshChatHistory();
    refreshChatUsers();
  };

  window.chatAddExternal = async function () {
    var nid = ((el("chat_external") && el("chat_external").value) || "").trim();
    if (!nid) return;
    try {
      await fetchT(
        "/comms/chat/add_user",
        {
          method: "POST",
          body: (function () {
            var fd = new FormData();
            fd.append("node_id", nid);
            return fd;
          })(),
        },
        8000
      );
    } catch (e) {}
    chatSelect(nid);
    if (el("chat_external")) el("chat_external").value = "";
  };

  window.refreshChatHistory = async function () {
    var url = chatTarget
      ? "/comms/chat/history?with_user=" + encodeURIComponent(chatTarget) + "&limit=120"
      : "/comms/chat/history?room=swarm&limit=120";
    try {
      var d = await jget(url, 6000);
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
      if (!msgs.length)
        h =
          '<div class="muted">Shared window empty — first message lands on every peer with this Redis</div>';
      log.innerHTML = h;
      log.scrollTop = log.scrollHeight;
    } catch (e) {
      /* soft fail — next poll */
    }
  };

  window.chatSend = async function () {
    var input = el("chat_text");
    var text = ((input && input.value) || "").trim();
    if (!text) return;
    var body = { text: text, room: "swarm" };
    if (chatTarget) body.to = chatTarget;
    try {
      var d = await jpost("/comms/chat/send", body, 10000);
      if (input) input.value = "";
      lastHistSig = "";
      var o = el("comms_result");
      if (d.ok) {
        if (o) {
          o.textContent = chatTarget
            ? "DM sent → " + chatTarget
            : "Posted to shared #swarm";
          o.className = "success";
        }
        refreshChatHistory();
      } else if (o) {
        o.textContent = d.error || "send failed";
        o.className = "error";
      }
    } catch (e) {
      var o2 = el("comms_result");
      if (o2) {
        o2.textContent = "send timeout — Redis/network slow";
        o2.className = "error";
      }
    }
  };

  window.commsRegister = async function () {
    try {
      var d = await fetchT("/comms/register", { method: "POST" }, 8000).then(function (r) {
        return r.json();
      });
      var o = el("comms_result");
      if (o) {
        o.textContent = d.ok ? "Registered · peers " + (d.peers || 0) : d.error || "fail";
        o.className = d.ok ? "success" : "error";
      }
    } catch (e) {
      var o3 = el("comms_result");
      if (o3) {
        o3.textContent = "register timeout";
        o3.className = "error";
      }
    }
    refreshComms();
    refreshChatUsers();
  };

  window.commsExport = async function () {
    try {
      var d = await jget("/comms/export", 8000);
      var x = el("comms_export");
      if (x) x.textContent = d.env_export || JSON.stringify(d, null, 2);
      var o = el("comms_result");
      if (o) {
        o.textContent = d.REDIS_URL
          ? "Share this Redis with LAN peers for one chat window: " + d.REDIS_URL
          : "export failed";
        o.className = d.REDIS_URL ? "success" : "error";
      }
    } catch (e) {
      var o4 = el("comms_result");
      if (o4) {
        o4.textContent = "export timeout";
        o4.className = "error";
      }
    }
  };

  function boot() {
    refreshComms();
    refreshChatUsers();
    refreshChatHistory();
    setInterval(refreshComms, 5000);
    setInterval(refreshChatUsers, 4000);
    setInterval(refreshChatHistory, 1500); /* shared window feels live */
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

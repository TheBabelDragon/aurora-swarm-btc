/* Mesh Comms + shared LAN chat + join mesh */
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
  async function fetchT(url, opts, ms) {
    ms = ms || 8000;
    var ctrl = new AbortController();
    var t = setTimeout(function () {
      ctrl.abort();
    }, ms);
    try {
      return await fetch(url, Object.assign({}, opts || {}, { signal: ctrl.signal }));
    } finally {
      clearTimeout(t);
    }
  }
  async function jget(url, ms) {
    return (await fetchT(url, {}, ms || 8000)).json();
  }

  window.refreshComms = async function () {
    try {
      var d = await jget("/comms/status", 6000);
      var shared =
        (d.peer_count || 0) > 1
          ? ' · <strong class="success">shared mesh active</strong>'
          : (d.lan_count || 0) > 0
            ? ' · <span class="muted">LAN peers seen — click Join shared mesh</span>'
            : "";
      var h =
        "<p><strong>" +
        (d.redis_ok ? "Redis OK" : "Redis DOWN") +
        "</strong> · <span class=\"mono\">" +
        esc(d.node_id) +
        "</span>" +
        shared +
        "</p>";
      h += "<p class=\"muted\">" + esc(d.redis_url || "") + "</p>";
      h +=
        "<p>Mesh peers <strong>" +
        (d.peer_count || 0) +
        "</strong> · LAN beacons <strong>" +
        (d.lan_count || 0) +
        "</strong> · " +
        esc(d.global_hashrate_display || "idle") +
        "</p>";
      var c = el("comms_card");
      if (c) c.innerHTML = h;
      var title = el("chat_title");
      if (title && !chatTarget)
        title.textContent =
          "#swarm · shared room · " + (d.peer_count || 0) + " on this Redis";
    } catch (e) {
      var c2 = el("comms_card");
      if (c2) c2.innerHTML = '<span class="error">Comms slow — retrying</span>';
    }
  };

  window.joinSharedMesh = async function () {
    var o = el("comms_result");
    if (o) {
      o.textContent = "Joining shared mesh…";
      o.className = "muted";
    }
    try {
      var fd = new FormData();
      var d = await fetchT("/comms/join_mesh", { method: "POST", body: fd }, 15000).then(function (r) {
        return r.json();
      });
      if (o) {
        if (d.ok) {
          o.textContent = d.joined
            ? "Joined " + (d.redis_url || "") + " · peers " + (d.peers || 0)
            : d.already
              ? "Already on shared mesh"
              : d.reason || "ok";
          o.className = "success";
        } else {
          o.textContent = d.error || "join failed";
          o.className = "error";
        }
      }
      refreshComms();
      refreshChatUsers();
      refreshChatHistory();
    } catch (e) {
      if (o) {
        o.textContent = "join timeout";
        o.className = "error";
      }
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
          "</div></div>";
      }
      if (
        !users.filter(function (u) {
          return u.source !== "self";
        }).length
      )
        h +=
          '<div class="muted">Only you on this Redis — Join shared mesh on both machines</div>';
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
      if (b) b.innerHTML = '<span class="error">users timeout</span>';
    }
  };

  window.chatSelect = function (nodeId) {
    chatTarget = nodeId || null;
    var t = el("chat_title");
    if (t) t.textContent = chatTarget ? "DM → " + chatTarget : "#swarm · shared room";
    lastHistSig = "";
    refreshChatHistory();
    refreshChatUsers();
  };

  window.chatAddExternal = async function () {
    var nid = ((el("chat_external") && el("chat_external").value) || "").trim();
    if (!nid) return;
    var fd = new FormData();
    fd.append("node_id", nid);
    try {
      await fetchT("/comms/chat/add_user", { method: "POST", body: fd }, 8000);
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
      if (!msgs.length) h = '<div class="muted">Shared window empty</div>';
      log.innerHTML = h;
      log.scrollTop = log.scrollHeight;
    } catch (e) {}
  };

  window.chatSend = async function () {
    var input = el("chat_text");
    var text = ((input && input.value) || "").trim();
    if (!text) return;
    var body = { text: text, room: "swarm" };
    if (chatTarget) body.to = chatTarget;
    try {
      var d = await fetchT(
        "/comms/chat/send",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
        10000
      ).then(function (r) {
        return r.json();
      });
      if (input) input.value = "";
      lastHistSig = "";
      var o = el("comms_result");
      if (d.ok) {
        if (o) {
          o.textContent = chatTarget ? "DM sent" : "Posted to #swarm";
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
        o2.textContent = "send timeout";
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
    } catch (e) {}
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
        o.textContent = d.REDIS_URL ? "Export ready" : "export failed";
        o.className = d.REDIS_URL ? "success" : "error";
      }
    } catch (e) {}
  };

  function ensureJoinButton() {
    var card = el("comms_card");
    if (!card) return;
    var parent = card.parentNode;
    if (!parent || el("btn_join_mesh")) return;
    var btn = document.createElement("button");
    btn.id = "btn_join_mesh";
    btn.type = "button";
    btn.textContent = "Join shared mesh";
    btn.onclick = function () {
      joinSharedMesh();
    };
    var section = parent.querySelector(".section");
    if (section) section.insertBefore(btn, section.firstChild);
  }

  function boot() {
    ensureJoinButton();
    refreshComms();
    refreshChatUsers();
    refreshChatHistory();
    setInterval(refreshComms, 5000);
    setInterval(refreshChatUsers, 4000);
    setInterval(refreshChatHistory, 1500);
    /* auto-try join once after discovery window */
    setTimeout(function () {
      joinSharedMesh();
    }, 10000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

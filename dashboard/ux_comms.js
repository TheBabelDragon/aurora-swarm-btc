/* Simple shared window: auto-join + plain-English status */
(function () {
  var chatTarget = null;
  var lastHistSig = "";
  var joinAttempted = false;

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

  function renderGuide(d) {
    var peers = d.peer_count || 0;
    var lan = d.lan_count || 0;
    var ok = d.redis_ok;
    var box = el("shared_window_status");
    if (!box) return;

    if (!ok) {
      box.className = "error";
      box.innerHTML =
        "<strong>Redis not reachable on this machine.</strong><br>" +
        "On this PC run: <span class=\"mono\">docker compose -f docker-compose.solo.yml up -d</span>";
      return;
    }
    if (peers >= 2) {
      box.className = "success";
      box.innerHTML =
        "<strong>LIVE SHARED WINDOW</strong> — " +
        peers +
        " nodes on the same mesh. Chat below is shared.";
      return;
    }
    if (lan >= 1) {
      box.className = "muted";
      box.innerHTML =
        "<strong>Other machine seen on LAN.</strong> Connecting to shared mesh… " +
        "If this stays stuck &gt;30s, click <em>Connect shared window</em>.";
      if (!joinAttempted) {
        joinAttempted = true;
        connectSharedWindow();
      }
      return;
    }
    box.className = "muted";
    box.innerHTML =
      "<strong>Waiting for a second Aurora node on this LAN.</strong><br>" +
      "1) On the <em>other</em> PC: install + run the same stack<br>" +
      "2) Both must allow UDP <span class=\"mono\">7379</span> and TCP <span class=\"mono\">6379</span> on the LAN<br>" +
      "3) Open this page on both — they should auto-connect<br>" +
      "You are: <span class=\"mono\">" +
      esc(d.node_id) +
      "</span>";
  }

  window.refreshComms = async function () {
    try {
      var d = await jget("/comms/status", 6000);
      renderGuide(d);
      var c = el("comms_card");
      if (c) {
        c.innerHTML =
          '<span class="mono">' +
          esc(d.node_id) +
          "</span> · Redis " +
          (d.redis_ok ? "OK" : "DOWN") +
          " · mesh " +
          (d.peer_count || 0) +
          " · LAN " +
          (d.lan_count || 0);
      }
      var title = el("chat_title");
      if (title && !chatTarget) {
        title.textContent =
          (d.peer_count || 0) >= 2
            ? "#swarm · LIVE shared window"
            : "#swarm · local only until peers join";
      }
    } catch (e) {
      var box = el("shared_window_status");
      if (box) {
        box.className = "error";
        box.textContent = "Dashboard cannot reach /comms/status — is the container up?";
      }
    }
  };

  window.connectSharedWindow = async function () {
    var o = el("comms_result");
    if (o) {
      o.textContent = "Connecting…";
      o.className = "muted";
    }
    try {
      var d = await fetchT(
        "/comms/join_mesh",
        { method: "POST", body: new FormData() },
        15000
      ).then(function (r) {
        return r.json();
      });
      if (o) {
        if (d.ok && (d.joined || d.already || (d.peers && d.peers >= 1))) {
          o.textContent = d.joined
            ? "Connected to shared mesh"
            : d.already
              ? "Already connected"
              : d.reason || "OK";
          o.className = "success";
        } else {
          o.textContent =
            d.error ||
            d.reason ||
            "No other node found yet — start Aurora on the second machine";
          o.className = d.ok ? "muted" : "error";
        }
      }
    } catch (e) {
      if (o) {
        o.textContent = "Connect timed out";
        o.className = "error";
      }
    }
    refreshComms();
    refreshChatUsers();
    refreshChatHistory();
  };

  window.refreshChatUsers = async function () {
    try {
      var d = await jget("/comms/chat/users", 6000);
      var box = el("chat_users");
      if (!box) return;
      var users = d.users || [];
      var h =
        '<div style="margin-bottom:4px"><button type="button" class="small" onclick="chatSelect(null)">#swarm</button></div>';
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
          "</span></div>";
      }
      if (
        !users.filter(function (u) {
          return u.source !== "self";
        }).length
      )
        h += '<div class="muted">No other users on this mesh yet</div>';
      box.innerHTML = h;
      var nodes = box.querySelectorAll(".chat-user");
      for (var j = 0; j < nodes.length; j++) {
        nodes[j].onclick = (function (n) {
          return function () {
            chatSelect(n.getAttribute("data-nid"));
          };
        })(nodes[j]);
      }
    } catch (e) {}
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
        h +=
          '<div style="margin:4px 0;' +
          (mine ? "text-align:right" : "") +
          '"><span class="muted" style="font-size:11px">' +
          (mine ? "you" : esc(m.from)) +
          " · " +
          (m.ts ? new Date(m.ts * 1000).toLocaleTimeString() : "") +
          '</span><br><span style="display:inline-block;padding:4px 8px;border-radius:8px;background:' +
          (mine ? "#1a3a2a" : "#1a1a2a") +
          '">' +
          esc(m.text) +
          "</span></div>";
      }
      if (!msgs.length) h = '<div class="muted">No messages yet</div>';
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
      if (d.ok) refreshChatHistory();
      else {
        var o = el("comms_result");
        if (o) {
          o.textContent = d.error || "send failed";
          o.className = "error";
        }
      }
    } catch (e) {}
  };

  /* keep legacy names used by HTML buttons */
  window.commsRegister = function () {
    fetchT("/comms/register", { method: "POST" }, 8000).finally(function () {
      refreshComms();
    });
  };
  window.commsExport = async function () {
    try {
      var d = await jget("/comms/export", 8000);
      var x = el("comms_export");
      if (x) x.textContent = d.env_export || JSON.stringify(d, null, 2);
    } catch (e) {}
  };
  window.joinSharedMesh = connectSharedWindow;

  function boot() {
    refreshComms();
    refreshChatUsers();
    refreshChatHistory();
    setInterval(refreshComms, 4000);
    setInterval(refreshChatUsers, 5000);
    setInterval(refreshChatHistory, 1500);
    setTimeout(connectSharedWindow, 8000);
    setTimeout(connectSharedWindow, 20000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

/* Policy & Scheduling Rules — shadow-first, backend-confirmed */
(function () {
  function el(id) { return document.getElementById(id); }
  function jfetch(url, opts, ms) {
    ms = ms || 8000;
    var c = new AbortController();
    var t = setTimeout(function () { c.abort(); }, ms);
    return fetch(url, Object.assign({}, opts || {}, { signal: c.signal }))
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; }); })
      .finally(function () { clearTimeout(t); });
  }
  function payload() {
    return {
      latency_preference: parseInt(el("pol_latency").value, 10),
      load_balancing_preference: parseInt(el("pol_load").value, 10),
      energy_efficiency_preference: parseInt(el("pol_energy").value, 10),
      recovery_strategy: el("pol_recovery").value,
      activation_mode: el("pol_mode").value
    };
  }
  function dirty() {
    el("pol_latency_v").textContent = el("pol_latency").value;
    el("pol_load_v").textContent = el("pol_load").value;
    el("pol_energy_v").textContent = el("pol_energy").value;
    var line = el("policy_status_line");
    if (line) line.textContent = "Unsaved preview changes (not active)";
  }
  window.polDirty = dirty;
  window.polRefresh = function () {
    jfetch("/policy/status", {}, 5000).then(function (res) {
      var d = res.body || {};
      var p = d.preview || {};
      if (p.latency_preference != null) el("pol_latency").value = p.latency_preference;
      if (p.load_balancing_preference != null) el("pol_load").value = p.load_balancing_preference;
      if (p.energy_efficiency_preference != null) el("pol_energy").value = p.energy_efficiency_preference;
      if (p.recovery_strategy) el("pol_recovery").value = p.recovery_strategy;
      if (p.activation_mode) el("pol_mode").value = p.activation_mode;
      dirty();
      var mf = (d.multiflow || {}).availability || "?";
      el("policy_status_line").textContent =
        "Active: " + (d.active_version_id || "none") + " | dirty=" + !!d.preview_dirty + " | multiflow=" + mf;
      el("policy_out").textContent = JSON.stringify(d, null, 2);
    }).catch(function (e) {
      el("policy_status_line").textContent = "Policy service unavailable";
      el("policy_out").textContent = String(e);
    });
  };
  window.polSaveDraft = function () {
    jfetch("/policy/draft/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload())
    }, 8000).then(function (res) {
      el("policy_out").textContent = JSON.stringify(res.body, null, 2);
      window.polRefresh();
    }).catch(function (e) { el("policy_out").textContent = "save failed: " + e; });
  };
  window.polDiscard = function () {
    jfetch("/policy/draft/discard", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 5000)
      .then(function () { window.polRefresh(); });
  };
  window.polSimulate = function () {
    jfetch("/policy/draft/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload())
    }, 8000).then(function () {
      return jfetch("/policy/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 15000);
    }).then(function (res) {
      el("policy_out").textContent = JSON.stringify(res.body, null, 2);
    }).catch(function (e) { el("policy_out").textContent = "simulate failed: " + e; });
  };
  window.polValidate = function () {
    jfetch("/policy/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 8000)
      .then(function (res) { el("policy_out").textContent = JSON.stringify(res.body, null, 2); })
      .catch(function (e) { el("policy_out").textContent = String(e); });
  };
  window.polActivate = function () {
    if (!confirm("Request policy activation? Shadow mode does not change live execution.")) return;
    jfetch("/policy/activate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: true })
    }, 8000).then(function (res) {
      el("policy_out").textContent = JSON.stringify(res.body, null, 2);
      window.polRefresh();
    }).catch(function (e) { el("policy_out").textContent = String(e); });
  };
  function inject() {
    if (el("policy_rules_panel")) return;
    var routing = el("routing_panel");
    if (!routing || !routing.parentNode) return;
    var card = document.createElement("div");
    card.className = "card";
    card.id = "policy_rules_panel";
    card.innerHTML =
      "<h2>Policy & Scheduling Rules</h2>" +
      "<p class=\"muted\">Editable preferences (not hard constraints). Unsaved draft does not change active policy. Default mode: <strong>shadow</strong>.</p>" +
      "<div id=\"policy_status_line\" class=\"muted\">Loading policy status…</div>" +
      "<div style=\"margin-top:10px;display:grid;gap:8px;max-width:520px\">" +
      "<label>Latency preference <input type=\"range\" id=\"pol_latency\" min=\"0\" max=\"100\" value=\"65\" oninput=\"polDirty()\"> <span id=\"pol_latency_v\">65</span></label>" +
      "<label>Worker load-balancing <input type=\"range\" id=\"pol_load\" min=\"0\" max=\"100\" value=\"75\" oninput=\"polDirty()\"> <span id=\"pol_load_v\">75</span></label>" +
      "<label>Energy efficiency <input type=\"range\" id=\"pol_energy\" min=\"0\" max=\"100\" value=\"30\" oninput=\"polDirty()\"> <span id=\"pol_energy_v\">30</span></label>" +
      "<label>Recovery strategy <select id=\"pol_recovery\" onchange=\"polDirty()\"><option value=\"fast\">fast</option><option value=\"balanced\" selected>balanced</option><option value=\"conservative\">conservative</option></select></label>" +
      "<label>Activation mode <select id=\"pol_mode\" onchange=\"polDirty()\"><option value=\"shadow\" selected>shadow</option><option value=\"approval\">approval</option><option value=\"controlled\">controlled</option></select></label>" +
      "</div>" +
      "<div style=\"margin-top:10px;display:flex;flex-wrap:wrap;gap:6px\">" +
      "<button type=\"button\" onclick=\"polSaveDraft()\">Save draft</button>" +
      "<button type=\"button\" onclick=\"polDiscard()\">Discard</button>" +
      "<button type=\"button\" onclick=\"polSimulate()\">Simulate (dry-run)</button>" +
      "<button type=\"button\" onclick=\"polValidate()\">Validate</button>" +
      "<button type=\"button\" onclick=\"polActivate()\">Request activation</button>" +
      "<button type=\"button\" onclick=\"polRefresh()\">Refresh</button>" +
      "</div>" +
      "<pre id=\"policy_out\" class=\"mono muted\" style=\"max-height:220px;overflow:auto;margin-top:10px;white-space:pre-wrap\"></pre>" +
      "<p class=\"muted\" style=\"font-size:12px\">Hard constraints (health, AEGIS quarantine, capacity) are not overridden by these sliders. MultiFlow: <a href=\"https://github.com/TheBabelDragon/MultiFlow\" target=\"_blank\" rel=\"noopener\">MultiFlow</a></p>";
    routing.parentNode.insertBefore(card, routing.nextSibling);
    setTimeout(window.polRefresh, 600);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", inject);
  else inject();
})();

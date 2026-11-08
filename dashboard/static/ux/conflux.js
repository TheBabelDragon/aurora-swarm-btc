/* Conflux lifecycle panel — overview + read lists + gated mutations */
(function () {
  function $(id) { return document.getElementById(id); }
  function set(id, text) {
    var n = $(id);
    if (n) n.textContent = text;
  }
  function apiKey() {
    var n = $("conflux_api_key");
    return n ? n.value.trim() : "";
  }
  function actorId() {
    var n = $("conflux_actor_id");
    return n ? n.value.trim() : "";
  }
  function headers(mut) {
    var h = { "Content-Type": "application/json" };
    var k = apiKey();
    if (k) h["X-API-Key"] = k;
    if (mut) {
      var a = actorId();
      if (a) h["X-Actor-Id"] = a;
    }
    return h;
  }
  function showMsg(ok, text) {
    var el = $("conflux_msg");
    if (!el) return;
    el.textContent = text;
    el.className = ok ? "success" : "error";
  }
  function fillTable(tbodyId, rows, cols) {
    var tb = $(tbodyId);
    if (!tb) return;
    if (!rows || !rows.length) {
      tb.innerHTML = '<tr><td colspan="' + cols + '" class="muted">None</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(function (r) {
      return "<tr>" + r.map(function (c) {
        return "<td class=\"mono\">" + (c == null ? "" : String(c)) + "</td>";
      }).join("") + "</tr>";
    }).join("");
  }

  async function loadStatus() {
    try {
      var st = await fetch("/conflux/status").then(function (r) { return r.json(); });
      set("conflux-version", st.version || "?");
      set("conflux-runner", st.runner_enabled ? "enabled" : "disabled");
      set("conflux-deploy", st.local_deploy_enabled ? "local allowed" : "dry-run only");
      var ev = st.evidence || {};
      set("conflux-evidence", (ev.available ? "available" : "off") + " · " + (ev.backend || "?") + " · n=" + (ev.count || 0));
      set("conflux-caps", (st.capabilities || []).join(", "));
    } catch (e) {
      set("conflux-version", "unavailable");
    }
    try {
      var m = await fetch("/conflux-mount/status").then(function (r) { return r.json(); });
      set("conflux-mounted", m.mounted ? "yes" : "no");
      if (m.error) set("conflux-mount-error", m.error);
    } catch (e) {}
  }

  async function loadProjects() {
    try {
      var d = await fetch("/conflux/projects?limit=20").then(function (r) { return r.json(); });
      var rows = (d.projects || []).map(function (p) {
        return [p.project_id, p.name, p.created_by || "", (p.sources || []).length];
      });
      fillTable("conflux_projects_body", rows, 4);
      var sel = $("conflux_project_sel");
      if (sel) {
        var cur = sel.value;
        sel.innerHTML = '<option value="">— project —</option>';
        (d.projects || []).forEach(function (p) {
          var o = document.createElement("option");
          o.value = p.project_id;
          o.textContent = p.name + " · " + p.project_id;
          if (p.project_id === cur) o.selected = true;
          sel.appendChild(o);
        });
      }
    } catch (e) {}
  }

  async function loadLists() {
    var pid = ($("conflux_project_sel") || {}).value || "";
    var q = pid ? ("?project_id=" + encodeURIComponent(pid) + "&limit=15") : "?limit=15";
    try {
      var cs = await fetch("/conflux/changesets" + q).then(function (r) { return r.json(); });
      fillTable("conflux_cs_body", (cs.changesets || []).map(function (c) {
        return [c.changeset_id, c.status, c.author || c.agent_id || "", (c.files || []).length];
      }), 4);
    } catch (e) {}
    try {
      var b = await fetch("/conflux/builds" + q).then(function (r) { return r.json(); });
      fillTable("conflux_builds_body", (b.builds || []).map(function (x) {
        return [x.build_id, x.status, x.manifest_id, (x.output_artifact_ids || []).length];
      }), 4);
    } catch (e) {}
    try {
      var a = await fetch("/conflux/artifacts" + q).then(function (r) { return r.json(); });
      fillTable("conflux_arts_body", (a.artifacts || []).map(function (x) {
        return [x.artifact_id, (x.content_hash || "").slice(0, 12), x.name, x.size_bytes];
      }), 4);
    } catch (e) {}
    try {
      var r = await fetch("/conflux/releases" + q).then(function (r) { return r.json(); });
      fillTable("conflux_rels_body", (r.releases || []).map(function (x) {
        return [x.release_id, x.version, x.status, x.promoted_by || ""];
      }), 4);
    } catch (e) {}
    try {
      var d = await fetch("/conflux/deployments" + q).then(function (r) { return r.json(); });
      fillTable("conflux_deps_body", (d.deployments || []).map(function (x) {
        return [x.deployment_id, x.status, x.release_id, x.target_id];
      }), 4);
    } catch (e) {}
  }

  async function createProject() {
    var name = ($("conflux_proj_name") || {}).value;
    if (!name) { showMsg(false, "project name required"); return; }
    try {
      var r = await fetch("/conflux/projects", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({ name: name, created_by: actorId() })
      });
      var d = await r.json().catch(function () { return {}; });
      if (r.ok) { showMsg(true, "project " + (d.project && d.project.project_id)); loadProjects(); }
      else showMsg(false, d.detail || d.error || ("HTTP " + r.status));
    } catch (e) { showMsg(false, String(e)); }
  }

  async function createRelease() {
    var pid = ($("conflux_project_sel") || {}).value;
    var ver = ($("conflux_rel_ver") || {}).value || "0.1.0";
    var rev = ($("conflux_rel_rev") || {}).value || "HEAD";
    if (!pid) { showMsg(false, "select project"); return; }
    try {
      var r = await fetch("/conflux/releases", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          project_id: pid,
          version: ver,
          source_revision_id: rev,
          created_by: actorId()
        })
      });
      var d = await r.json().catch(function () { return {}; });
      if (r.ok) { showMsg(true, "release " + (d.release && d.release.release_id)); loadLists(); }
      else showMsg(false, d.detail || ("HTTP " + r.status));
    } catch (e) { showMsg(false, String(e)); }
  }

  async function planDryRun() {
    var pid = ($("conflux_project_sel") || {}).value;
    var rid = ($("conflux_dep_release") || {}).value;
    if (!pid || !rid) { showMsg(false, "project + release_id required"); return; }
    try {
      var r = await fetch("/conflux/deployments/plan", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify({
          project_id: pid,
          release_id: rid,
          target_id: "local-dry",
          adapter: "dry_run",
          created_by: actorId()
        })
      });
      var d = await r.json().catch(function () { return {}; });
      if (r.ok) {
        showMsg(true, "plan " + (d.plan && d.plan.plan_id));
        if (d.plan && d.plan.plan_id) {
          var ex = await fetch("/conflux/deployments/execute", {
            method: "POST",
            headers: headers(true),
            body: JSON.stringify({ plan_id: d.plan.plan_id, authorized_by: actorId() })
          });
          var ed = await ex.json().catch(function () { return {}; });
          showMsg(ex.ok, ex.ok ? ("deploy " + ((ed.deployment && ed.deployment.status) || "ok")) : (ed.detail || "execute failed"));
        }
        loadLists();
      } else showMsg(false, d.detail || ("HTTP " + r.status));
    } catch (e) { showMsg(false, String(e)); }
  }

  function loadAll() {
    loadStatus();
    loadProjects();
    loadLists();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadAll);
  } else {
    loadAll();
  }

  window.ConfluxPanel = {
    reload: loadAll,
    createProject: createProject,
    createRelease: createRelease,
    planDryRun: planDryRun,
    loadLists: loadLists
  };
})();

/* Conflux lifecycle panel — read-only overview + status */
(function () {
  function el(id) { return document.getElementById(id); }
  function set(id, text) {
    var n = el(id);
    if (n) n.textContent = text;
  }
  function load() {
    fetch("/conflux/status")
      .then(function (r) { return r.json(); })
      .then(function (st) {
        set("conflux-version", st.version || "?");
        set("conflux-runner", st.runner_enabled ? "enabled" : "disabled");
        set("conflux-caps", (st.capabilities || []).join(", "));
      })
      .catch(function () {
        set("conflux-version", "unavailable");
      });
    fetch("/conflux/projects?limit=10")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var list = el("conflux-projects");
        if (!list) return;
        list.innerHTML = "";
        var projects = data.projects || [];
        if (!projects.length) {
          list.innerHTML = "<li class=\"empty\">No projects registered</li>";
          return;
        }
        projects.forEach(function (p) {
          var li = document.createElement("li");
          li.textContent = p.name + " (" + p.project_id + ")";
          list.appendChild(li);
        });
      })
      .catch(function () {});
    fetch("/conflux-mount/status")
      .then(function (r) { return r.json(); })
      .then(function (m) {
        set("conflux-mounted", m.mounted ? "yes" : "no");
        if (m.error) set("conflux-mount-error", m.error);
      })
      .catch(function () {});
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
  window.ConfluxPanel = { reload: load };
})();

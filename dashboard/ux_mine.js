/* Official miner log — additive; does not replace Start/Stop. */
(function () {
  function el(id) {
    return document.getElementById(id);
  }
  function ensure() {
    var box = el("mine_status");
    if (!box || el("mine_log")) return;
    var parent = box.parentNode;
    var pre = document.createElement("pre");
    pre.id = "mine_log";
    pre.className = "mono muted";
    pre.style.maxHeight = "240px";
    pre.style.overflow = "auto";
    pre.style.whiteSpace = "pre-wrap";
    pre.style.marginTop = "10px";
    pre.textContent = "mining log…";
    parent.appendChild(pre);
  }
  async function tick() {
    ensure();
    var box = el("mine_status");
    var log = el("mine_log");
    try {
      var d = await fetch("/mining/engine/status").then(function (r) {
        return r.json();
      });
      if (box && d && d.wallet) {
        var sh = d.shares || {};
        var extra =
          '<div class="muted">wallet <span class="mono">' +
          (d.wallet || "") +
          "</span></div>" +
          '<div class="muted">user <span class="mono">' +
          (d.user || "") +
          "</span> · auth " +
          (d.authorized ? "YES" : "no") +
          " · job " +
          (d.job_ready ? "YES" : "wait") +
          " · shares acc/rej/sub " +
          (sh.accepted || 0) +
          "/" +
          (sh.rejected || 0) +
          "/" +
          (sh.submitted || 0) +
          "</div>";
        if (box.innerHTML.indexOf("wallet") === -1) box.innerHTML += extra;
        else {
          /* keep metric from refreshMine; append once is enough */
        }
      }
      var L = await fetch("/mining/engine/log?lines=60").then(function (r) {
        return r.json();
      });
      if (log && L && L.lines) {
        log.textContent = (L.lines || []).join("\n") || "no events yet";
        log.scrollTop = log.scrollHeight;
      }
    } catch (e) {}
  }
  setInterval(tick, 2500);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick);
  else tick();
})();

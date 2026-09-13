/**
 * Fleet UI — vanilla JS utilities.
 *
 * No build step required.  Loaded by base.html for every page.
 * Provides:
 *   - Auto-dismiss flash messages after 6 s
 *   - Confirm-before-submit helper (already done inline with onclick,
 *     but available for future use)
 *   - Polling helper for deployment status refresh
 *   - Refresh timestamp display
 */

// ─── Flash auto-dismiss ────────────────────────────────────────────
(function () {
  const AUTO_DISMISS_MS = 6000;
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity .4s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 450);
    }, AUTO_DISMISS_MS);
  });
})();

// ─── Refresh timestamp ────────────────────────────────────────────
(function () {
  var el = document.getElementById("refresh-time");
  if (el) {
    el.textContent = new Date().toLocaleTimeString();
  }
})();

// ─── Deployment status polling ───────────────────────────────────
/**
 * Poll the Fleet API for deployment status every `intervalMs`.
 *
 * @param {string} deploymentId
 * @param {number} intervalMs   default 10 000
 * @param {function(object):void} onUpdate   called with parsed JSON on each poll
 * @returns {{ stop: function }}  call stop() to halt polling
 */
function pollDeployment(deploymentId, intervalMs, onUpdate) {
  intervalMs = intervalMs || 10000;
  var tid = setInterval(function () {
    fetch("/api-proxy/deployments/" + deploymentId, {
      credentials: "same-origin",
    })
      .then(function (r) {
        if (r.status === 401) {
          window.location.href = "/login";
          return null;
        }
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data && typeof onUpdate === "function") onUpdate(data);
        if (data && (data.status === "success" || data.status === "failed" || data.status === "rolled_back")) {
          clearInterval(tid);
        }
      })
      .catch(function () {
        /* network error — keep polling */
      });
  }, intervalMs);
  return { stop: function () { clearInterval(tid); } };
}

// ─── Device filter / search ───────────────────────────────────────
/**
 * Filter a table's rows by a text input value.
 * inputId: id of <input>, tableId: id of <table>.
 */
function wireTableFilter(inputId, tableId) {
  var input = document.getElementById(inputId);
  var table = document.getElementById(tableId);
  if (!input || !table) return;
  input.addEventListener("input", function () {
    var q = input.value.toLowerCase();
    table.querySelectorAll("tbody tr").forEach(function (row) {
      row.style.display = row.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });
}

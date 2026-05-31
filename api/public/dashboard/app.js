/**
 * HouseAccount Pricing Dashboard — app.js
 * Vanilla JS, no external deps, no secrets.
 */

/* ======================================================
   CONSTANTS & STATE
   ====================================================== */
const CONCURRENCY_CAP = 4;

const SAMPLE_BOOKING = {
  job_id: "demo-plumbing-001",
  service_category: "Plumbing",
  zip_code: "78704",
  job_description:
    "50-gallon gas water heater stopped working, pilot won't stay lit. Need replacement.",
  original_estimate: 1850
};

/* ======================================================
   UTILITY HELPERS
   ====================================================== */

function usd(n) {
  return "$" + Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
  });
}

function pct(n) {
  return (Number(n) * 100).toFixed(1) + "%";
}

function clamp(val, lo, hi) {
  return Math.max(lo, Math.min(hi, val));
}

function el(id) {
  return document.getElementById(id);
}

function show(elem) {
  if (elem) elem.classList.remove("hidden");
}

function hide(elem) {
  if (elem) elem.classList.add("hidden");
}

/* ======================================================
   TOAST NOTIFICATIONS
   ====================================================== */

function showToast(message, type) {
  // type: "error" | "warn" | "success"
  var container = el("toast-container");
  var toast = document.createElement("div");
  toast.className = "toast toast-" + (type || "error");
  toast.innerHTML =
    '<span class="toast-msg">' + escapeHtml(message) + "</span>" +
    '<button class="toast-close" aria-label="Dismiss">&times;</button>';

  toast.querySelector(".toast-close").addEventListener("click", function () {
    toast.remove();
  });

  container.appendChild(toast);

  // Auto-dismiss after 6 s
  setTimeout(function () {
    if (toast.parentNode) toast.remove();
  }, 6000);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ======================================================
   TAB NAVIGATION
   ====================================================== */

function initTabs() {
  var buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = btn.dataset.panel;

      // Update button states
      buttons.forEach(function (b) {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");

      // Swap panels
      document.querySelectorAll(".panel").forEach(function (p) {
        p.classList.add("hidden");
      });
      show(el("panel-" + target));

      // Trigger load on Results tab
      if (target === "results") {
        loadResults();
      }
    });
  });
}

/* ======================================================
   API STATUS PROBE
   ====================================================== */

function probeApiStatus() {
  var dot = el("status-dot");
  var label = el("status-label");
  var badge = el("model-badge");

  fetch("/dashboard/metrics")
    .then(function (res) {
      if (!res.ok) throw new Error("status " + res.status);
      return res.json();
    })
    .then(function (data) {
      dot.className = "status-dot online";
      label.textContent = "API connected";
      var v = data.model_version || "unknown";
      badge.textContent = v;
      el("footer-version").textContent = v;
    })
    .catch(function () {
      dot.className = "status-dot offline";
      label.textContent = "API offline";
    });
}

/* ======================================================
   PREDICT PANEL (U5)
   ====================================================== */

function initPredict() {
  el("load-sample-btn").addEventListener("click", function () {
    el("booking-input").value = JSON.stringify(SAMPLE_BOOKING, null, 2);
    hide(el("json-error"));
  });

  el("predict-btn").addEventListener("click", function () {
    var raw = el("booking-input").value.trim();
    var parsed;

    // Client-side JSON validation
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      var errEl = el("json-error");
      errEl.textContent = "Invalid JSON: " + e.message;
      show(errEl);
      return;
    }
    hide(el("json-error"));

    runPredict(parsed);
  });
}

function runPredict(booking) {
  var btn = el("predict-btn");
  var btnText = btn.querySelector(".btn-text");
  var spinner = el("predict-spinner");

  // Loading state
  btn.disabled = true;
  btnText.textContent = "Predicting…";
  show(spinner);
  hide(el("result-card"));

  fetch("/dashboard/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(booking)
  })
    .then(function (res) {
      return res.json().then(function (body) {
        return { status: res.status, body: body };
      });
    })
    .then(function (resp) {
      if (resp.status === 429) {
        var retry = resp.body.retry_after ? " Retry in " + resp.body.retry_after + "s." : "";
        showToast("Rate limit exceeded." + retry, "warn");
      } else if (resp.status >= 400) {
        showToast(resp.body.error || "Error " + resp.status, "error");
      } else {
        renderResultCard(resp.body);
      }
    })
    .catch(function (err) {
      showToast("Network error: " + err.message, "error");
    })
    .finally(function () {
      btn.disabled = false;
      btnText.textContent = "Predict";
      hide(spinner);
    });
}

function renderResultCard(data) {
  var card = el("result-card");
  var lo = Number(data.estimate_lo);
  var mid = Number(data.estimate_midpoint);
  var hi = Number(data.estimate_hi);
  var conf = Number(data.confidence);

  // Version badge
  el("result-version").textContent = data.model_version || "";

  // Low-confidence banner
  if (conf < 0.5) {
    show(el("ood-banner"));
  } else {
    hide(el("ood-banner"));
  }

  // Interval labels
  el("label-lo").textContent = usd(lo);
  el("label-mid").textContent = usd(mid);
  el("label-hi").textContent = usd(hi);

  // Interval bar: position midpoint tick as % along [lo, hi]
  var range = hi - lo;
  var midPct = range > 0 ? ((mid - lo) / range) * 100 : 50;
  el("midpoint-tick").style.left = clamp(midPct, 2, 98) + "%";
  // Fill bar shows the full range (cosmetic — always 100% of the track)
  el("interval-fill").style.width = "100%";

  // Confidence meter
  var confPct = clamp(conf * 100, 0, 100);
  el("confidence-value").textContent = confPct.toFixed(1) + "%";
  var fill = el("confidence-fill");
  fill.style.width = confPct + "%";
  fill.className = "confidence-fill";
  if (conf >= 0.8) {
    fill.classList.add("conf-high");
  } else if (conf >= 0.5) {
    fill.classList.add("conf-mid");
  } else {
    fill.classList.add("conf-low");
  }

  // Uncertainties
  var listEl = el("uncertainties-list");
  listEl.innerHTML = "";
  var uncertainties = data.uncertainties;
  if (uncertainties) {
    // May be a string (comma-separated) or an array
    var items = Array.isArray(uncertainties)
      ? uncertainties
      : String(uncertainties)
          .split(/[,;|]+/)
          .map(function (s) { return s.trim(); })
          .filter(Boolean);

    if (items.length > 0) {
      items.forEach(function (item) {
        var li = document.createElement("li");
        li.className = "uncertainty-item";
        li.textContent = item;
        listEl.appendChild(li);
      });
      show(el("uncertainties-section"));
    } else {
      hide(el("uncertainties-section"));
    }
  } else {
    hide(el("uncertainties-section"));
  }

  show(card);
}

/* ======================================================
   CSV PARSER — pure function (U6)
   ====================================================== */

/**
 * Parse CSV text into an array of booking objects.
 * First row is treated as headers.
 * Returns an array of plain objects; rows that are blank are skipped.
 */
function csvToBookings(text) {
  var lines = text.split(/\r?\n/);
  if (lines.length < 2) return [];

  var headers = parseCsvRow(lines[0]);
  var bookings = [];

  for (var i = 1; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) continue;

    var values = parseCsvRow(line);
    var obj = {};
    headers.forEach(function (h, idx) {
      var key = h.trim().toLowerCase().replace(/\s+/g, "_");
      var val = values[idx] !== undefined ? values[idx] : "";
      // Coerce numeric fields
      if (key === "original_estimate" && val !== "") {
        var num = parseFloat(val);
        obj[key] = isNaN(num) ? val : num;
      } else {
        obj[key] = val;
      }
    });
    bookings.push(obj);
  }
  return bookings;
}

/** Parse a single CSV row respecting quoted fields. */
function parseCsvRow(row) {
  var fields = [];
  var cur = "";
  var inQuote = false;

  for (var i = 0; i < row.length; i++) {
    var ch = row[i];
    if (ch === '"') {
      if (inQuote && row[i + 1] === '"') {
        cur += '"';
        i++;
      } else {
        inQuote = !inQuote;
      }
    } else if (ch === "," && !inQuote) {
      fields.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  fields.push(cur);
  return fields;
}

/** Validate that a booking object has the required fields. */
function validateBooking(b) {
  var required = ["service_category", "zip_code", "job_description"];
  var missing = required.filter(function (k) { return !b[k]; });
  if (missing.length > 0) {
    return "Missing fields: " + missing.join(", ");
  }
  return null; // valid
}

/* ======================================================
   BATCH PANEL (U6)
   ====================================================== */

var batchBookings = [];
var batchResults = [];

function initBatch() {
  var fileInput = el("csv-file-input");
  var dropzone = el("dropzone");

  // File input change
  fileInput.addEventListener("change", function () {
    var file = fileInput.files[0];
    if (file) loadCsvFile(file);
  });

  // Drag-and-drop
  dropzone.addEventListener("dragover", function (e) {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  });
  dropzone.addEventListener("dragleave", function () {
    dropzone.classList.remove("drag-over");
  });
  dropzone.addEventListener("drop", function (e) {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
    var file = e.dataTransfer.files[0];
    if (file) loadCsvFile(file);
  });

  el("batch-run-btn").addEventListener("click", runBatch);

  // Drawer close
  el("drawer-close").addEventListener("click", closeDrawer);
  el("drawer-overlay").addEventListener("click", closeDrawer);
}

function loadCsvFile(file) {
  var errEl = el("csv-error");
  hide(errEl);

  var reader = new FileReader();
  reader.onload = function (e) {
    try {
      batchBookings = csvToBookings(e.target.result);
      if (batchBookings.length === 0) {
        errEl.textContent = "Couldn't parse CSV — no data rows found.";
        show(errEl);
        return;
      }
      // Show filename
      var fnEl = el("dropzone-filename");
      fnEl.textContent = file.name + " — " + batchBookings.length + " rows";
      show(fnEl);

      // Show JSON preview (cap at 20 rows for display)
      var preview = batchBookings.slice(0, 20);
      el("json-preview").textContent = JSON.stringify(preview, null, 2);
      el("json-row-count").textContent = "(" + batchBookings.length + " rows" +
        (batchBookings.length > 20 ? ", showing first 20" : "") + ")";
      show(el("json-preview-section"));

      // Enable run button
      el("batch-run-btn").disabled = false;

      // Reset previous results
      hide(el("batch-table-wrap"));
      hide(el("batch-summary"));
      el("batch-tbody").innerHTML = "";
    } catch (err) {
      errEl.textContent = "Couldn't parse CSV: " + err.message;
      show(errEl);
    }
  };
  reader.readAsText(file);
}

function runBatch() {
  if (!batchBookings.length) return;

  batchResults = [];
  var btn = el("batch-run-btn");
  var progress = el("batch-progress");
  var tbody = el("batch-tbody");
  tbody.innerHTML = "";

  btn.disabled = true;
  show(progress);
  hide(el("batch-table-wrap"));
  hide(el("batch-summary"));

  var total = batchBookings.length;
  var done = 0;
  var idx = 0;

  function updateProgress() {
    progress.textContent = done + " / " + total + " scored";
  }

  updateProgress();

  function scoreNext() {
    if (idx >= total) return;

    var i = idx;
    idx++;

    var booking = batchBookings[i];
    var validErr = validateBooking(booking);

    if (validErr) {
      // Client validation failure — flag row, don't abort
      var result = {
        booking: booking,
        error: validErr,
        status: "invalid"
      };
      batchResults[i] = result;
      appendBatchRow(tbody, result, i);
      done++;
      updateProgress();
      if (done === total) finishBatch();
      return;
    }

    fetch("/dashboard/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(booking)
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (resp) {
        var result;
        if (resp.status >= 400) {
          result = {
            booking: booking,
            error: resp.body.error || "HTTP " + resp.status,
            status: "api-error"
          };
        } else {
          result = {
            booking: booking,
            prediction: resp.body,
            status: "ok"
          };
        }
        batchResults[i] = result;
        appendBatchRow(tbody, result, i);
      })
      .catch(function (err) {
        var result = {
          booking: booking,
          error: "Network: " + err.message,
          status: "api-error"
        };
        batchResults[i] = result;
        appendBatchRow(tbody, result, i);
      })
      .finally(function () {
        done++;
        updateProgress();
        if (done === total) finishBatch();
      });
  }

  // Launch up to CONCURRENCY_CAP concurrent requests
  function pump() {
    var active = idx - (total - done) < 0 ? 0 : idx - (total - done);
    while (idx < total && (idx - done) < CONCURRENCY_CAP) {
      scoreNext();
    }
  }

  // Monkey-patch scoreNext to re-pump after each completion
  var origScoreNext = scoreNext;
  function scoreNextAndPump(i) {
    var booking = batchBookings[i];
    var validErr = validateBooking(booking);

    if (validErr) {
      var result = { booking: booking, error: validErr, status: "invalid" };
      batchResults[i] = result;
      appendBatchRow(tbody, result, i);
      done++;
      updateProgress();
      if (done === total) { finishBatch(); return; }
      launchOne();
      return;
    }

    fetch("/dashboard/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(booking)
    })
      .then(function (res) {
        return res.json().then(function (body) { return { status: res.status, body: body }; });
      })
      .then(function (resp) {
        var result;
        if (resp.status >= 400) {
          result = { booking: booking, error: resp.body.error || "HTTP " + resp.status, status: "api-error" };
        } else {
          result = { booking: booking, prediction: resp.body, status: "ok" };
        }
        batchResults[i] = result;
        appendBatchRow(tbody, result, i);
      })
      .catch(function (err) {
        var result = { booking: booking, error: "Network: " + err.message, status: "api-error" };
        batchResults[i] = result;
        appendBatchRow(tbody, result, i);
      })
      .finally(function () {
        done++;
        updateProgress();
        if (done === total) { finishBatch(); return; }
        launchOne();
      });
  }

  var nextIdx = 0;

  function launchOne() {
    if (nextIdx >= total) return;
    var i = nextIdx;
    nextIdx++;
    scoreNextAndPump(i);
  }

  // Launch initial wave
  var initialCount = Math.min(CONCURRENCY_CAP, total);
  for (var k = 0; k < initialCount; k++) {
    launchOne();
  }
}

function appendBatchRow(tbody, result, rowIdx) {
  var tr = document.createElement("tr");
  tr.className = "results-row" + (result.status !== "ok" ? " row-error" : "");
  tr.dataset.rowIdx = rowIdx;

  var b = result.booking;
  var shortDesc = b.job_description
    ? b.job_description.substring(0, 60) + (b.job_description.length > 60 ? "…" : "")
    : "—";

  if (result.status === "ok") {
    var p = result.prediction;
    var conf = Number(p.confidence);
    var confClass = conf >= 0.8 ? "conf-chip-high" : conf >= 0.5 ? "conf-chip-mid" : "conf-chip-low";

    tr.innerHTML =
      "<td>" + escapeHtml(b.service_category || "—") + "</td>" +
      "<td>" + escapeHtml(b.zip_code || "—") + "</td>" +
      "<td class='desc-cell'>" + escapeHtml(shortDesc) + "</td>" +
      "<td>" + usd(p.estimate_lo) + "</td>" +
      "<td class='mid-cell'>" + usd(p.estimate_midpoint) + "</td>" +
      "<td>" + usd(p.estimate_hi) + "</td>" +
      "<td><span class='conf-chip " + confClass + "'>" + pct(conf) + "</span></td>" +
      "<td><span class='status-chip ok'>&#10003;</span></td>";
  } else {
    tr.innerHTML =
      "<td>" + escapeHtml(b.service_category || "—") + "</td>" +
      "<td>" + escapeHtml(b.zip_code || "—") + "</td>" +
      "<td class='desc-cell'>" + escapeHtml(shortDesc) + "</td>" +
      "<td colspan='4' class='error-cell'>" + escapeHtml(result.error || "Error") + "</td>" +
      "<td><span class='status-chip warn'>&#9888;</span></td>";
  }

  tr.addEventListener("click", function () {
    openDrawer(result, rowIdx);
  });

  tbody.appendChild(tr);
}

function finishBatch() {
  el("batch-run-btn").disabled = false;
  show(el("batch-table-wrap"));

  var ok = batchResults.filter(function (r) { return r && r.status === "ok"; }).length;
  var failed = batchResults.length - ok;
  var summary = el("batch-summary");
  summary.textContent = ok + " scored" + (failed > 0 ? ", " + failed + " skipped (flagged above)" : "");
  show(summary);
}

function openDrawer(result, rowIdx) {
  var drawer = el("detail-drawer");
  var body = el("drawer-body");
  body.innerHTML = "";

  if (result.status === "ok") {
    var p = result.prediction;
    var conf = Number(p.confidence);

    // Render a mini version of the result card inside the drawer
    var confPct = clamp(conf * 100, 0, 100).toFixed(1);
    var confClass = conf >= 0.8 ? "conf-high" : conf >= 0.5 ? "conf-mid" : "conf-low";

    var uncertaintiesHtml = "";
    if (p.uncertainties) {
      var items = Array.isArray(p.uncertainties)
        ? p.uncertainties
        : String(p.uncertainties).split(/[,;|]+/).map(function (s) { return s.trim(); }).filter(Boolean);
      if (items.length) {
        uncertaintiesHtml = "<div class='drawer-section-title'>Why it might vary</div><ul class='uncertainties-list'>" +
          items.map(function (u) { return "<li class='uncertainty-item'>" + escapeHtml(u) + "</li>"; }).join("") +
          "</ul>";
      }
    }

    body.innerHTML =
      "<div class='drawer-kv'><span class='kv-label'>Category</span><span>" + escapeHtml(p.service_category || result.booking.service_category || "—") + "</span></div>" +
      "<div class='drawer-kv'><span class='kv-label'>ZIP</span><span>" + escapeHtml(result.booking.zip_code || "—") + "</span></div>" +
      "<div class='drawer-kv'><span class='kv-label'>Model</span><span>" + escapeHtml(p.model_version || "—") + "</span></div>" +
      "<div class='drawer-interval'>" +
        "<div class='drawer-interval-row'><span class='kv-label'>Low</span><strong>" + usd(p.estimate_lo) + "</strong></div>" +
        "<div class='drawer-interval-row'><span class='kv-label'>Midpoint</span><strong class='mid-cell'>" + usd(p.estimate_midpoint) + "</strong></div>" +
        "<div class='drawer-interval-row'><span class='kv-label'>High</span><strong>" + usd(p.estimate_hi) + "</strong></div>" +
      "</div>" +
      "<div class='drawer-conf-row'><span class='kv-label'>Confidence</span>" +
        "<div class='confidence-track'><div class='confidence-fill " + confClass + "' style='width:" + confPct + "%'></div></div>" +
        "<span>" + confPct + "%</span>" +
      "</div>" +
      (conf < 0.5 ? "<div class='ood-banner'>Low confidence — out-of-distribution signal.</div>" : "") +
      uncertaintiesHtml;
  } else {
    body.innerHTML =
      "<div class='drawer-error'>" +
        "<div class='drawer-section-title'>Error</div>" +
        "<p>" + escapeHtml(result.error || "Unknown error") + "</p>" +
        "<div class='drawer-section-title'>Booking</div>" +
        "<pre class='json-preview'>" + escapeHtml(JSON.stringify(result.booking, null, 2)) + "</pre>" +
      "</div>";
  }

  show(el("drawer-overlay"));
  show(drawer);
}

function closeDrawer() {
  hide(el("detail-drawer"));
  hide(el("drawer-overlay"));
}

/* ======================================================
   RESULTS PANEL (U7)
   ====================================================== */

var resultsLoaded = false;

function loadResults() {
  if (resultsLoaded) return;

  // Load metrics
  fetch("/dashboard/metrics")
    .then(function (res) {
      if (res.status === 503 || res.status === 404) {
        throw new Error("unavailable");
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (data) {
      renderMetricCards(data);
      renderComparisonChart(data);
    })
    .catch(function (err) {
      if (err.message === "unavailable" || err.message.includes("404")) {
        showMetricsUnavailable();
      } else {
        showMetricsUnavailable();
      }
    });

  // Load predictions
  fetch("/dashboard/predictions")
    .then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function (rows) {
      renderPredictionsTable(rows);
    })
    .catch(function () {
      // Predictions table just stays hidden — non-critical
    });

  resultsLoaded = true;
}

function showMetricsUnavailable() {
  hide(el("stat-cards"));
  hide(el("chart-section"));
  show(el("metrics-unavailable"));
}

function renderMetricCards(data) {
  el("metrics-unavailable") && hide(el("metrics-unavailable"));

  // Remove skeleton class from all cards
  document.querySelectorAll(".stat-card").forEach(function (c) {
    c.classList.remove("skeleton");
  });

  // Blended MAPE
  var blended = Number(data.blended);
  var baseBlended = Number(data.baseline_blended);
  var blendedDelta = baseBlended - blended; // positive = improvement
  el("sc-blended-val").textContent = (blended * 100).toFixed(1) + "%";
  el("sc-blended-base").textContent = "Baseline: " + (baseBlended * 100).toFixed(1) + "%";
  el("sc-blended-delta").textContent = blendedDelta >= 0
    ? "▼ " + (blendedDelta * 100).toFixed(1) + "% improvement"
    : "▲ " + (Math.abs(blendedDelta) * 100).toFixed(1) + "% worse";
  el("sc-blended-delta").className = "stat-card-delta " + (blendedDelta >= 0 ? "delta-good" : "delta-bad");
  el("sc-blended-check").textContent = blended < baseBlended ? "✓ Pass" : "✗ Fail";
  el("sc-blended-check").className = "stat-card-check " + (blended < baseBlended ? "check-pass" : "check-fail");

  // Real-only MAPE
  var real = Number(data.real_only);
  var baseReal = Number(data.baseline_real);
  var realDelta = baseReal - real;
  el("sc-real-val").textContent = (real * 100).toFixed(1) + "%";
  el("sc-real-base").textContent = "Baseline: " + (baseReal * 100).toFixed(1) + "%";
  el("sc-real-delta").textContent = realDelta >= 0
    ? "▼ " + (realDelta * 100).toFixed(1) + "% improvement"
    : "▲ " + (Math.abs(realDelta) * 100).toFixed(1) + "% worse";
  el("sc-real-delta").className = "stat-card-delta " + (realDelta >= 0 ? "delta-good" : "delta-bad");
  el("sc-real-check").textContent = real < baseReal ? "✓ Pass" : "✗ Fail";
  el("sc-real-check").className = "stat-card-check " + (real < baseReal ? "check-pass" : "check-fail");

  // Coverage
  var cov = Number(data.coverage);
  var targetCov = 0.80; // target >= 80%
  el("sc-cov-val").textContent = (cov * 100).toFixed(1) + "%";
  el("sc-cov-base").textContent = "Target: ≥80%";
  el("sc-cov-delta").textContent = cov >= targetCov
    ? "+" + ((cov - targetCov) * 100).toFixed(1) + "% above target"
    : ((cov - targetCov) * 100).toFixed(1) + "% below target";
  el("sc-cov-delta").className = "stat-card-delta " + (cov >= targetCov ? "delta-good" : "delta-bad");
  el("sc-cov-check").textContent = cov >= targetCov ? "✓ Pass" : "✗ Fail";
  el("sc-cov-check").className = "stat-card-check " + (cov >= targetCov ? "check-pass" : "check-fail");

  show(el("stat-cards"));
}

function renderComparisonChart(data) {
  var blended = Number(data.blended) * 100;
  var baseBlended = Number(data.baseline_blended) * 100;
  var real = Number(data.real_only) * 100;
  var baseReal = Number(data.baseline_real) * 100;

  // Max value for scaling bars (cap at reasonable max)
  var maxVal = Math.max(blended, baseBlended, real, baseReal, 1);
  var scale = 100 / maxVal; // scale to fill 100% of bar width at most

  var chartEl = el("chart-bars");
  chartEl.innerHTML =
    renderBarGroup("Blended MAPE", blended, baseBlended, scale) +
    renderBarGroup("Real-only MAPE", real, baseReal, scale);

  show(el("chart-section"));
}

function renderBarGroup(label, modelVal, baseVal, scale) {
  var mPct = clamp(modelVal * scale, 1, 100).toFixed(1);
  var bPct = clamp(baseVal * scale, 1, 100).toFixed(1);
  return (
    "<div class='bar-group'>" +
      "<div class='bar-group-label'>" + escapeHtml(label) + "</div>" +
      "<div class='bar-row'>" +
        "<span class='bar-key'>Model</span>" +
        "<div class='bar-track'><div class='bar-fill bar-model' style='width:" + mPct + "%'></div></div>" +
        "<span class='bar-val'>" + modelVal.toFixed(1) + "%</span>" +
      "</div>" +
      "<div class='bar-row'>" +
        "<span class='bar-key'>Baseline</span>" +
        "<div class='bar-track'><div class='bar-fill bar-baseline' style='width:" + bPct + "%'></div></div>" +
        "<span class='bar-val'>" + baseVal.toFixed(1) + "%</span>" +
      "</div>" +
    "</div>"
  );
}

function renderPredictionsTable(rows) {
  if (!rows || rows.length === 0) return;

  var tbody = el("predictions-tbody");
  tbody.innerHTML = "";

  // Cap display at 200 rows
  var display = rows.slice(0, 200);

  display.forEach(function (row) {
    var conf = Number(row.confidence);
    var confClass = conf >= 0.8 ? "conf-chip-high" : conf >= 0.5 ? "conf-chip-mid" : "conf-chip-low";
    var tr = document.createElement("tr");
    tr.innerHTML =
      "<td class='mono-cell'>" + escapeHtml((row.job_id || "").substring(0, 12)) + "</td>" +
      "<td>" + escapeHtml(row.service_category || "—") + "</td>" +
      "<td>" + usd(row.estimate_lo) + "</td>" +
      "<td class='mid-cell'>" + usd(row.estimate_midpoint) + "</td>" +
      "<td>" + usd(row.estimate_hi) + "</td>" +
      "<td><span class='conf-chip " + confClass + "'>" + pct(conf) + "</span></td>" +
      "<td>" + (String(row.is_labeled) === "true" || row.is_labeled === true ? "✓" : "—") + "</td>";
    tbody.appendChild(tr);
  });

  show(el("predictions-section"));
}

/* ======================================================
   INIT
   ====================================================== */

document.addEventListener("DOMContentLoaded", function () {
  initTabs();
  initPredict();
  initBatch();
  probeApiStatus();
});

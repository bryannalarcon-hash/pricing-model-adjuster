// HouseAccount Pricing Dashboard — app.js
// Vanilla JS SPA: wires the design-token UI to the real same-origin API.
// No framework, no build step, no secrets in client code (proxy injects auth).
// Collaborators: index.html (structure), styles.css (tokens/components).
// Features: Predict / Batch / Results / Conversions panels.
// Booking flow: Control 1 (#website-autosend-toggle) for dashboard sends;
//               Control 2 (#api-autosend-toggle in #settings-popover) for API calls;
//               Control 3 (#live-mode-toggle) real vs simulated sends + #live-indicator badge.
// Results charts are tap-to-enlarge: initChartExpand clones #compare-chart /
// #scatter-svg into #chart-modal-scrim (Esc / scrim-click / × to close).

'use strict';

/* ============================================================
   CONSTANTS
   ============================================================ */

const CONCURRENCY_CAP = 4;

const REQUIRED_FIELDS = ['job_id', 'service_category', 'zip_code', 'job_description'];

const SAMPLES = {
  cleaning: {
    name: 'Cleaning · standard (high confidence)',
    payload: {
      job_id: 'cl-7a21c4',
      service_category: 'Cleaning',
      service_subtype: 'House cleaning',
      zip_code: '75062',
      job_description: 'Standard 2 bedroom apartment cleaning',
      deadline: 'I\'m flexible',
      booking_month: '2026-05',
      original_estimate: 160
    }
  },
  hvac: {
    name: 'HVAC · tune-up',
    payload: {
      job_id: 'hv-3c0822',
      service_category: 'HVAC',
      service_subtype: 'Maintenance',
      zip_code: '33324',
      job_description: 'AC tune-up and filter replacement',
      deadline: 'Within 1-2 weeks',
      booking_month: '2026-05',
      original_estimate: 200
    }
  },
  remodel: {
    name: 'Remodel · large (low conf)',
    payload: {
      job_id: 'rm-77c0e2',
      service_category: 'Remodeling',
      service_subtype: 'Kitchen remodel',
      zip_code: '75062',
      job_description: 'Full kitchen remodel — cabinets, counters, flooring, some plumbing',
      deadline: 'I\'m flexible',
      booking_month: '2026-05',
      original_estimate: 7200
    }
  },
  auto: {
    name: 'Auto · out-of-category',
    payload: {
      job_id: 'au-19fd3b',
      service_category: 'Auto',
      service_subtype: 'Mobile detailing',
      zip_code: '33324',
      job_description: 'Full interior + exterior detail, midsize SUV',
      deadline: 'I\'m flexible',
      booking_month: '2026-04',
      original_estimate: 280
    }
  }
};

const SAMPLE_CSV = `job_id,service_category,service_subtype,zip_code,booking_month,job_description,original_estimate,deadline
b-1001,Plumbing,Water Heater Replacement,78704,2026-05,50-gal gas water heater replacement,1850,Within 1-2 weeks
b-1002,Pest Control,Bed bugs,33324,2026-04,Bed bug heat treatment 2BR apartment,828,Within 1 week
b-1003,Cleaning,Window washing (exterior),75062,2026-03,Exterior window wash 2-story 20 windows,258,I'm flexible
b-1004,Electrical,Panel,30307,2026-05,Replace 200A electrical panel and breakers,2100,As soon as possible
b-1005,Handyman,Tv Mounting,90011,2026-04,Mount 65 inch TV on drywall conceal cables,140,As soon as possible
b-1006,Remodeling,Kitchen remodel,75062,2026-05,Full kitchen remodel cabinets counters flooring,7200,I'm flexible
b-1007,Landscaping,Lawn care,33463,2026-03,Weekly lawn mowing and edging small yard,80,I'm flexible
b-1008,HVAC,AC repair,33484,2026-04,AC not cooling needs diagnostic and recharge,,Within 1-2 weeks
b-1009,Auto,Detailing,33324,2026-04,Full interior detail midsize SUV,280,I'm flexible
b-1010,Roofing,Repair,30307,2026-05,Repair roof leak around chimney flashing,950,As soon as possible
b-1011,Painting,Interior painting,33463,2026-03,Bathroom walls painting project,,As soon as possible
b-1012,,Misc,33484,2026-04,Various small fixes around the house,200,I'm flexible`;

/* ============================================================
   UTILITY
   ============================================================ */

function el(id) { return document.getElementById(id); }

function show(elem) { if (elem) elem.classList.remove('hidden'); }
function hide(elem) { if (elem) elem.classList.add('hidden'); }

function usd(n) {
  return '$' + Math.round(Number(n)).toLocaleString('en-US');
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** confidence → band metadata */
function band(conf) {
  if (conf >= 0.8) return { key: 'high', label: 'High confidence', tone: 'ok',   note: 'Above the 0.80 threshold — homeowners and providers can book on this.' };
  if (conf >= 0.5) return { key: 'mid',  label: 'Ambiguous',       tone: 'amber', note: 'Between 0.50 and 0.80 — usable, but worth a human glance before quoting.' };
  return            { key: 'low',  label: 'Low confidence',   tone: 'bad',   note: 'Below 0.50 — outside the training distribution. Route for manual review.' };
}

const TONE_COLOR = {
  ok:    'var(--ok)',
  amber: 'var(--warn)',
  bad:   'var(--bad)'
};

const FLAG_HELP = {
  'Scope inferred from free text': 'No structured scope fields exist — the model reads square footage, fixture count and complexity out of the description text.',
  'Scope ambiguous from description': 'The description is short or vague, so the model widened the range to cover plausible scopes.',
  'Wide range — interval over 3× median': 'The predicted interval is wider than 3× the median observed range — an out-of-distribution signal.',
  'Outside production category': 'This service category is outside the current 10 production verticals, so confidence is reduced.',
  'Large job outside typical range': 'Midpoint is above the $5,000 95th-percentile of training data — passed through, but flagged low-confidence.'
};

function flagHelp(label) {
  if (FLAG_HELP[label]) return FLAG_HELP[label];
  if (/^Original estimate differs/.test(label)) return 'The model\'s midpoint diverges from the previous-model estimate by this amount.';
  return label;
}

/* ============================================================
   SVG ICONS (inline strings for innerHTML use)
   ============================================================ */
const ICON = {
  check:    '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5l3.2 3.2L13 4.5"/></svg>',
  x:        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
  info:     '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="8" cy="8" r="6.4"/><path d="M8 7.3v3.4" stroke-linecap="round"/><circle cx="8" cy="5" r=".5" fill="currentColor" stroke="none"/></svg>',
  alert:    '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1.7L15 14H1z"/><path d="M8 6.3v3.2"/><circle cx="8" cy="11.6" r=".6" fill="currentColor" stroke="none"/></svg>',
  spinner:  '<svg class="ha-spin" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M8 1.6a6.4 6.4 0 106.4 6.4" opacity="1"/></svg>'
};

/* ============================================================
   TOAST NOTIFICATIONS
   ============================================================ */

function pushToast({ tone, title, body, retry }) {
  // tone: 'bad' | 'amber' | 'ok' | 'info'
  const toneColor = { bad: 'var(--bad)', amber: 'var(--warn)', ok: 'var(--ok)', info: 'var(--blue)' };
  const toneIcon  = { bad: ICON.alert,   amber: ICON.alert,    ok: ICON.check,  info: ICON.info   };
  const color = toneColor[tone] || toneColor.info;
  const icon  = toneIcon[tone]  || ICON.info;
  const autoDismiss = retry ? 9000 : 6000;

  const toast = document.createElement('div');
  toast.className = 'ha-toast';
  toast.style.borderLeftColor = color;

  const iconSpan = document.createElement('span');
  iconSpan.className = 'ha-toast-icon';
  iconSpan.style.color = color;
  iconSpan.innerHTML = icon;

  const bodyDiv = document.createElement('div');
  bodyDiv.className = 'ha-toast-body';

  const titleDiv = document.createElement('div');
  titleDiv.className = 'ha-toast-title';
  titleDiv.textContent = title;
  bodyDiv.appendChild(titleDiv);

  if (body) {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'ha-toast-msg';
    msgDiv.textContent = body;
    bodyDiv.appendChild(msgDiv);

    // Countdown for retry toasts
    if (retry) {
      let left = retry;
      const iv = setInterval(function() {
        left--;
        if (left <= 0) { clearInterval(iv); return; }
        msgDiv.textContent = body.replace(/\d+s/, left + 's');
      }, 1000);
    }
  }

  const closeBtn = document.createElement('button');
  closeBtn.className = 'ha-toast-close';
  closeBtn.innerHTML = ICON.x;
  closeBtn.addEventListener('click', function() { toast.remove(); });

  toast.appendChild(iconSpan);
  toast.appendChild(bodyDiv);
  toast.appendChild(closeBtn);

  const container = el('toast-container');
  container.appendChild(toast);

  setTimeout(function() { if (toast.parentNode) toast.remove(); }, autoDismiss);
}

/* ============================================================
   CONFIDENCE RING (vanilla DOM)
   ============================================================ */

function renderConfidenceRing(containerEl, conf, size) {
  size = size || 66;
  const b = band(conf);
  const deg = conf * 360;
  const inner = size - 16;
  containerEl.style.width  = size + 'px';
  containerEl.style.height = size + 'px';
  containerEl.style.background = 'conic-gradient(' + TONE_COLOR[b.tone] + ' ' + deg + 'deg, #eef2f5 0)';
  containerEl.style.borderRadius = '50%';
  containerEl.style.display = 'grid';
  containerEl.style.placeItems = 'center';
  containerEl.style.flexShrink = '0';
  containerEl.style.position = 'relative';

  // Clear previous inner
  containerEl.innerHTML = '';
  const inner_el = document.createElement('i');
  inner_el.className = 'ha-ring-inner ha-num';
  inner_el.style.width  = inner + 'px';
  inner_el.style.height = inner + 'px';
  inner_el.style.fontSize = Math.round(size * 0.26) + 'px';
  inner_el.innerHTML = Math.round(conf * 100) + '<span style="font-size:' + Math.round(size * 0.16) + 'px">%</span>';
  containerEl.appendChild(inner_el);
}

/* ============================================================
   FLAG CHIPS
   ============================================================ */

function renderFlagChips(container, flags, tone) {
  container.innerHTML = '';
  flags.forEach(function(label) {
    const wrap = document.createElement('span');
    wrap.className = 'ha-tip-wrap';

    const chip = document.createElement('span');
    chip.className = 'ha-flag';

    const dot = document.createElement('span');
    dot.className = 'ha-flag-dot';
    dot.style.background = TONE_COLOR[tone === 'ok' ? 'amber' : tone];

    const text = document.createTextNode(label);
    chip.appendChild(dot);
    chip.appendChild(text);
    wrap.appendChild(chip);

    // Tooltip
    const tipText = flagHelp(label);
    if (tipText) {
      let tip = null;
      wrap.addEventListener('mouseenter', function() {
        tip = document.createElement('span');
        tip.className = 'ha-tip';
        tip.textContent = tipText;
        wrap.appendChild(tip);
      });
      wrap.addEventListener('mouseleave', function() {
        if (tip) { tip.remove(); tip = null; }
      });
    }

    container.appendChild(wrap);
  });
}

/* ============================================================
   TAB NAVIGATION
   ============================================================ */

const PANEL_TITLES = {
  predict:     ['Predict',     'Paste or compose one booking, get one estimate with a confidence interval.'],
  batch:       ['Batch',       'Upload a CSV of bookings, convert to the API shape, and score them in bulk.'],
  results:     ['Results',     'How the model performs against the previous pricing baseline.'],
  conversions: ['Conversions', 'Booking flow sends from this dashboard and programmatic API calls.']
};

let activeTab = 'predict';

function initTabs() {
  const buttons = document.querySelectorAll('.tab-btn');
  buttons.forEach(function(btn) {
    btn.addEventListener('click', function() {
      const target = btn.dataset.panel;
      if (target === activeTab) return;
      activeTab = target;

      buttons.forEach(function(b) {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');

      document.querySelectorAll('.panel').forEach(function(p) { p.classList.add('hidden'); });
      show(el('panel-' + target));

      // Update page title
      const titles = PANEL_TITLES[target];
      el('page-h1').textContent = titles[0];
      el('page-sub').textContent = titles[1];

      if (target === 'results') {
        loadResults();
      }
      if (target === 'conversions') {
        loadConversions();
      }
    });
  });
}

/* ============================================================
   API STATUS PROBE
   ============================================================ */

let apiOnline = false;
let modelVersion = 'gauntlet-v2.1.0';

function probeApiStatus() {
  const dot   = el('status-dot');
  const label = el('status-label');
  const badge = el('model-badge');

  label.textContent = 'Checking…';
  dot.className = 'ha-status-dot';

  fetch('/dashboard/metrics')
    .then(function(res) {
      if (!res.ok) throw new Error('status ' + res.status);
      return res.json();
    })
    .then(function(data) {
      apiOnline = true;
      dot.className = 'ha-status-dot online';
      label.textContent = 'API connected';
      var v = data.model_version || 'gauntlet-v2.1.0';
      modelVersion = v;
      badge.textContent = v;
      el('footer-version').textContent = v;
      hide(el('offline-banner'));
    })
    .catch(function() {
      apiOnline = false;
      dot.className = 'ha-status-dot offline';
      label.textContent = 'API offline';
      show(el('offline-banner'));
    });
}

/* ============================================================
   CSV PARSER  (pure function — csvToBookings)
   ============================================================ */

/**
 * csvToBookings — parse CSV text into booking objects.
 * First row is headers; blank rows are skipped.
 * Required by: batch panel, Playwright test hooks.
 */
function csvToBookings(text) {
  var lines = text.split(/\r?\n/);
  if (lines.length < 2) return [];
  var headers = parseCsvRow(lines[0]);
  var out = [];
  for (var i = 1; i < lines.length; i++) {
    var line = lines[i].trim();
    if (!line) continue;
    var cells = parseCsvRow(line);
    var obj = {};
    headers.forEach(function(h, idx) {
      var key = h.trim().toLowerCase().replace(/\s+/g, '_');
      var val = cells[idx] !== undefined ? cells[idx].trim() : '';
      if (key === 'original_estimate' && val !== '') {
        var n = parseFloat(val);
        obj[key] = isNaN(n) ? val : n;
      } else {
        obj[key] = val;
      }
    });
    out.push(obj);
  }
  return out;
}

/** Parse one CSV row handling double-quoted fields. */
function parseCsvRow(row) {
  var fields = [], cur = '', inQ = false;
  for (var i = 0; i < row.length; i++) {
    var ch = row[i];
    if (ch === '"') {
      if (inQ && row[i + 1] === '"') { cur += '"'; i++; }
      else inQ = !inQ;
    } else if (ch === ',' && !inQ) {
      fields.push(cur); cur = '';
    } else {
      cur += ch;
    }
  }
  fields.push(cur);
  return fields;
}

/**
 * validateBooking — check required fields.
 * Returns null if valid, error string if invalid.
 */
function validateBooking(b) {
  for (var i = 0; i < REQUIRED_FIELDS.length; i++) {
    var f = REQUIRED_FIELDS[i];
    if (!b[f] || String(b[f]).trim() === '') return f + ' required';
  }
  return null;
}

/* ============================================================
   PREDICT PANEL
   ============================================================ */

let predictPhase = 'empty'; // empty | loading | done

function initPredict() {
  // Sample dropdown toggle
  const trigger = el('load-sample-btn');
  const dropdown = el('sample-dropdown');

  trigger.addEventListener('click', function(e) {
    e.stopPropagation();
    dropdown.classList.toggle('hidden');
  });

  document.addEventListener('pointerdown', function(e) {
    if (!el('sample-menu-wrap').contains(e.target)) hide(dropdown);
  });

  // Sample items
  document.querySelectorAll('.ha-sample-item').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var key = btn.dataset.sample;
      var sample = SAMPLES[key];
      if (sample) {
        el('booking-input').value = JSON.stringify(sample.payload, null, 2);
        hideJsonError();
      }
      hide(dropdown);
    });
  });

  // Predict button
  el('predict-btn').addEventListener('click', runPredict);

  // Cmd/Ctrl+Enter
  el('booking-input').addEventListener('keydown', function(e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') runPredict();
  });

  // Clear error on type
  el('booking-input').addEventListener('input', function() { hideJsonError(); });
}

function showJsonError(msg) {
  el('json-error-text').textContent = msg;
  show(el('json-error'));
  // Ensure it includes "Invalid JSON" when appropriate
}

function hideJsonError() { hide(el('json-error')); }

function setPredictLoading(on) {
  var btn = el('predict-btn');
  var content = el('predict-btn-content');
  btn.disabled = on;
  if (on) {
    content.innerHTML = ICON.spinner + ' Predicting…';
  } else {
    content.innerHTML = 'Predict price <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h10M9 4l4 4-4 4"/></svg>';
  }
}

function showPredictState(state) {
  hide(el('result-empty'));
  hide(el('result-loading'));
  hide(el('result-card'));
  if (state === 'empty')   show(el('result-empty'));
  if (state === 'loading') show(el('result-loading'));
  if (state === 'done')    show(el('result-card'));
}

function runPredict() {
  hideJsonError();

  var raw = el('booking-input').value.trim();
  if (!raw) {
    showJsonError('Paste a payload or Load sample first.');
    // Show error but do NOT fire network request
    return;
  }

  var payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    // Must include "Invalid JSON" per test hook spec
    showJsonError('Invalid JSON — ' + e.message);
    return; // DO NOT fire network request on malformed JSON
  }

  // Validate required fields
  for (var i = 0; i < REQUIRED_FIELDS.length; i++) {
    var f = REQUIRED_FIELDS[i];
    if (!payload[f] || String(payload[f]).trim() === '') {
      showJsonError(f + ' required');
      return;
    }
  }

  predictPhase = 'loading';
  showPredictState('loading');
  setPredictLoading(true);

  fetch('/dashboard/predict', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(function(res) {
      return res.json().then(function(body) { return { status: res.status, body: body }; });
    })
    .then(function(resp) {
      if (resp.status === 429) {
        var ra = resp.body.retry_after ? ' Retry in ' + resp.body.retry_after + 's.' : '';
        pushToast({ tone: 'amber', title: '429 Rate limit exceeded', body: 'Rate limit hit.' + ra, retry: resp.body.retry_after || 60 });
        showPredictState('empty');
      } else if (resp.status >= 400) {
        pushToast({ tone: 'bad', title: 'Error ' + resp.status, body: resp.body.error || 'Request failed.' });
        showPredictState('empty');
      } else {
        renderResultCard(resp.body, payload);
        // Website auto-send is handled SERVER-SIDE now (DashboardController#predict honors the
        // persisted website_auto_send flag), so no client send here — both would double-record.
      }
    })
    .catch(function(err) {
      pushToast({ tone: 'bad', title: 'Network error', body: err.message });
      showPredictState('empty');
    })
    .finally(function() {
      setPredictLoading(false);
      predictPhase = 'done';
    });
}

function renderResultCard(data, submittedPayload) {
  var lo   = Number(data.estimate_lo);
  var mid  = Number(data.estimate_midpoint);
  var hi   = Number(data.estimate_hi);
  var conf = Number(data.confidence);

  var b = band(conf);

  // Category chip
  var category = (submittedPayload && submittedPayload.service_category) || data.service_category || '';
  var subtype  = (submittedPayload && (submittedPayload.service_subtype || submittedPayload.service_category)) || category;
  var zip      = (submittedPayload && submittedPayload.zip_code) || '';

  el('result-category-chip').textContent = category;

  // OOD banner
  if (conf < 0.5) {
    el('ood-banner-text').textContent =
      'Out-of-distribution — confidence ' + Math.round(conf * 100) +
      '%. Pass it through, but route for manual review rather than auto-quoting.';
    show(el('ood-banner'));
    pushToast({ tone: 'amber', title: 'Low-confidence estimate', body: category + ' flagged out-of-distribution (' + Math.round(conf * 100) + '%).' });
  } else {
    hide(el('ood-banner'));
  }

  // Midpoint
  el('label-mid').textContent = usd(mid);
  el('result-sub').textContent = subtype + ' · ZIP ' + zip;

  // Interval labels
  el('label-lo').textContent = usd(lo);
  el('label-hi').textContent = usd(hi);

  // Interval bar midpoint marker
  var range = hi - lo;
  var midPct = range > 0 ? ((mid - lo) / range) * 100 : 50;
  el('interval-mid-marker').style.left = 'calc(' + clamp(midPct, 2, 97) + '% - 2.5px)';

  // Confidence ring
  var ringEl = el('conf-ring');
  renderConfidenceRing(ringEl, conf, 66);

  // Band label: set the visible text as a text node before the child span
  var bandLabelEl = el('conf-band-label');
  bandLabelEl.style.color = TONE_COLOR[b.tone];
  // Keep the #confidence-value child span; update the preceding text node
  var confValEl = el('confidence-value');
  var confPctText = (conf * 100).toFixed(1) + '%';
  if (confValEl) {
    confValEl.textContent = confPctText;
  }
  // Set band label text via firstChild or prepend text node
  // Remove any existing text nodes before the span
  var childNodes = Array.from(bandLabelEl.childNodes);
  childNodes.forEach(function(node) {
    if (node.nodeType === Node.TEXT_NODE) node.remove();
  });
  bandLabelEl.insertBefore(
    document.createTextNode(b.label + ' · ' + confPctText + ' '),
    bandLabelEl.firstChild
  );
  el('conf-band-note').textContent = b.note;

  // Uncertainties / flags
  var uncertaintiesSection = el('uncertainties-section');
  var uncertaintiesList    = el('uncertainties-list');

  // API returns uncertainties as a STRING joined by "; "
  var flags = [];
  if (data.uncertainties) {
    var raw = String(data.uncertainties).trim();
    if (raw) {
      flags = raw.split(/\s*;\s*/).filter(Boolean);
    }
  }

  if (flags.length > 0) {
    renderFlagChips(uncertaintiesList, flags, b.tone);
    show(uncertaintiesSection);
  } else {
    hide(uncertaintiesSection);
  }

  // Footer
  el('result-model-version').textContent = data.model_version || modelVersion;
  el('result-job-id').textContent = data.job_id || '';

  // Send-to-booking button: ALWAYS available after a prediction (manual send), decoupled
  // from the auto-send toggle so toggling can never leave it stuck hidden. Re-sendable.
  var sendWrap = el('send-booking-wrap');
  var sendBtn  = el('send-booking-btn');
  var sendStatus = el('send-booking-status');
  var sendLabel = 'Send to booking flow <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8h10M9 4l4 4-4 4"/></svg>';

  sendBtn.disabled = false;
  sendBtn.style.display = '';        // clear any inline hide left by a prior send
  sendBtn.innerHTML = sendLabel;
  hide(sendStatus);
  show(sendWrap);

  var capturedPayload = submittedPayload;
  var capturedResult  = data;
  sendBtn.onclick = function() {
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending…';
    sendToBookingFlow({ source: 'manual', payload: capturedPayload, result: capturedResult })
      .then(function(resp) {
        // A live send only "succeeded" if staging accepted it (resp.ok); a rejected
        // live send (e.g. HTTP 401 — bad/absent signing key) is a FAILED state, not a tick.
        if (!resp.live) {
          sendStatus.textContent = 'Sent ✓ — simulated';
          sendStatus.style.color = '';
        } else if (resp.ok) {
          sendStatus.textContent = 'Sent ✓ — live (HTTP ' + resp.status + ')';
          sendStatus.style.color = 'var(--ok-text, #1a7a55)';
        } else {
          sendStatus.textContent = 'Failed ✗ — live send rejected (HTTP ' + resp.status + ')';
          sendStatus.style.color = 'var(--bad-text, #b42318)';
          pushToast({ tone: 'bad', title: 'Booking send failed',
            body: 'Staging rejected the booking (HTTP ' + resp.status + '). Check HOUSEACCOUNT_SIGNING_KEY.' });
        }
        show(sendStatus);
        sendBtn.disabled = false;     // keep it available for a re-send (never inline-hidden)
        sendBtn.innerHTML = sendLabel;
        loadConversionsIfActive();
      })
      .catch(function() {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Retry send';
      });
  };

  predictPhase = 'done';
  showPredictState('done');
}

/* ============================================================
   BATCH PANEL
   ============================================================ */

var batchState = {
  fileName: null,
  rows: null,       // raw parsed CSV rows
  phase: 'empty',  // empty | parsed | scoring | done
  results: [],
  drawerEntry: null
};

function initBatch() {
  // Dropzone drag-and-drop
  var dz = el('batch-dropzone');
  dz.addEventListener('dragover', function(e) { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', function() { dz.classList.remove('drag-over'); });
  dz.addEventListener('drop', function(e) {
    e.preventDefault();
    dz.classList.remove('drag-over');
    var file = e.dataTransfer.files[0];
    if (file) loadBatchFile(file);
  });

  // File input
  el('csv-file-input').addEventListener('change', function() {
    var file = el('csv-file-input').files[0];
    if (file) loadBatchFile(file);
  });

  // Toolbar buttons
  el('batch-run-btn').addEventListener('click', runBatch);
  el('batch-replace-btn').addEventListener('click', resetBatch);
  el('batch-view-json-btn').addEventListener('click', openJsonModal);
  el('batch-expand-json-btn').addEventListener('click', openJsonModal);
  el('use-sample-csv-btn').addEventListener('click', loadSampleCsv);
  el('batch-export-btn').addEventListener('click', exportBatchCsv);

  // Drawer
  el('drawer-close').addEventListener('click', closeDrawer);
  el('drawer-scrim').addEventListener('click', closeDrawer);

  // JSON modal
  el('json-modal-close').addEventListener('click', closeJsonModal);
  el('json-modal-scrim').addEventListener('click', function(e) {
    if (e.target === el('json-modal-scrim')) closeJsonModal();
  });
}

function loadSampleCsv() {
  var rows = csvToBookings(SAMPLE_CSV);
  setBatchLoaded('houseaccount_sample.csv', rows);
}

function loadBatchFile(file) {
  if (!/\.csv$/i.test(file.name)) {
    pushToast({ tone: 'bad', title: "Couldn’t parse CSV", body: 'Expected a .csv file. Got "' + escHtml(file.name) + '".' });
    return;
  }
  var reader = new FileReader();
  reader.onload = function(e) {
    try {
      var rows = csvToBookings(String(e.target.result));
      if (!rows.length) throw new Error('no rows');
      setBatchLoaded(file.name, rows);
    } catch (err) {
      pushToast({ tone: 'bad', title: "Couldn’t parse CSV", body: 'The file didn’t match the expected booking columns.' });
    }
  };
  reader.readAsText(file);
}

function setBatchLoaded(fileName, rows) {
  batchState.fileName = fileName;
  batchState.rows     = rows;
  batchState.phase    = 'parsed';
  batchState.results  = [];

  // Hide dropzone, show toolbar
  hide(el('batch-dropzone'));
  show(el('batch-toolbar'));
  el('batch-filename').textContent   = fileName;
  el('batch-toolbar-sub').textContent = rows.length + ' bookings · converted to API payload';

  // Show JSON preview
  var payloads = rows.map(rowToPayload);
  var previewJson = JSON.stringify(payloads.slice(0, 2), null, 2);
  if (payloads.length > 2) previewJson += '\n  … +' + (payloads.length - 2) + ' more';
  el('json-preview').textContent = previewJson;
  el('json-row-count').textContent = rows.length + ' rows';
  show(el('json-preview-section'));

  // Reset results table
  hide(el('batch-table-wrap'));
  el('batch-tbody').innerHTML = '';
  hide(el('batch-summary'));

  // Enable run
  el('batch-run-btn').disabled = false;
  hide(el('batch-export-btn'));
  show(el('batch-replace-btn'));

  // Progress hidden
  hide(el('batch-progress-wrap'));
}

function resetBatch() {
  batchState = { fileName: null, rows: null, phase: 'empty', results: [], drawerEntry: null };
  show(el('batch-dropzone'));
  hide(el('batch-toolbar'));
  hide(el('json-preview-section'));
  hide(el('batch-table-wrap'));
  hide(el('batch-summary'));
  el('batch-tbody').innerHTML = '';
  el('csv-file-input').value = '';
}

function rowToPayload(r) {
  var o = { job_id: r.job_id, service_category: r.service_category };
  if (r.service_subtype) o.service_subtype = r.service_subtype;
  o.zip_code = r.zip_code;
  o.job_description = r.job_description;
  if (r.booking_month) o.booking_month = r.booking_month;
  if (r.original_estimate != null && r.original_estimate !== '' && !isNaN(Number(r.original_estimate)))
    o.original_estimate = Number(r.original_estimate);
  if (r.deadline) o.deadline = r.deadline;
  return o;
}

function runBatch() {
  if (!batchState.rows || !batchState.rows.length) return;

  batchState.phase   = 'scoring';
  batchState.results = [];

  // UI: hide preview, show table, show progress
  hide(el('json-preview-section'));
  el('batch-tbody').innerHTML = '';
  hide(el('batch-summary'));
  hide(el('batch-export-btn'));

  var progressWrap = el('batch-progress-wrap');
  var progressFill = el('batch-progress-fill');
  var progressLabel = el('batch-progress-label');
  show(progressWrap);

  var tableWrap = el('batch-table-wrap');
  show(tableWrap);

  el('batch-run-btn').disabled = true;
  hide(el('batch-replace-btn'));

  var total   = batchState.rows.length;
  var done    = 0;
  var nextIdx = 0;
  var accum   = new Array(total);

  function updateProgress() {
    var pct = total > 0 ? (done / total * 100) : 0;
    progressFill.style.width = pct + '%';
    progressLabel.textContent = done + ' / ' + total + ' scored';
  }
  updateProgress();

  function appendRow(entry, idx) {
    var tr = buildBatchRow(entry, idx);
    el('batch-tbody').appendChild(tr);
  }

  function finish() {
    batchState.phase   = 'done';
    batchState.results = Array.from(accum);
    hide(progressWrap);

    var scored  = accum.filter(function(e) { return e && e.result; }).length;
    var skipped = accum.filter(function(e) { return e && e.error;  }).length;

    // Summary pills
    var pills = el('batch-summary-pills');
    pills.innerHTML =
      '<span class="ha-pill-ok">' + scored + ' scored</span>' +
      (skipped > 0 ? '<span class="ha-pill-bad">' + skipped + ' skipped</span>' : '');

    // Summary bar (for test hook: text contains "scored" and "skipped"/"flagged")
    var summaryBar = el('batch-summary');
    summaryBar.textContent = scored + ' scored' + (skipped > 0 ? ', ' + skipped + ' skipped' : '');
    show(summaryBar);

    el('batch-run-btn').disabled = false;
    show(el('batch-replace-btn'));
    if (scored > 0) show(el('batch-export-btn'));

    // "Send all scored" is always available after scoring (decoupled from the auto-send toggle)
    if (scored > 0) {
      var sendAllBtn = el('batch-send-all-btn');
      sendAllBtn.textContent = 'Send all scored (' + scored + ')';
      sendAllBtn.style.display = '';
      show(sendAllBtn);
    }

    pushToast({
      tone: skipped > 0 ? 'amber' : 'ok',
      title: 'Batch complete',
      body: scored + ' scored' + (skipped > 0 ? ', ' + skipped + ' skipped.' : '.')
    });
  }

  function launchOne() {
    if (nextIdx >= total) return;
    var i = nextIdx++;
    var row = batchState.rows[i];
    var validErr = validateBooking(row);

    if (validErr) {
      var entry = { row: row, error: validErr };
      accum[i] = entry;
      appendRow(entry, i);
      done++;
      updateProgress();
      if (done === total) finish();
      else launchOne();
      return;
    }

    var payload = rowToPayload(row);
    fetch('/dashboard/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function(res) {
        return res.json().then(function(body) { return { status: res.status, body: body }; });
      })
      .then(function(resp) {
        var entry;
        if (resp.status >= 400) {
          entry = { row: row, error: resp.body.error || 'HTTP ' + resp.status };
        } else {
          // Coerce values to numbers
          var b = resp.body;
          b.estimate_lo        = Number(b.estimate_lo);
          b.estimate_midpoint  = Number(b.estimate_midpoint);
          b.estimate_hi        = Number(b.estimate_hi);
          b.confidence         = Number(b.confidence);
          entry = { row: row, result: b };
          // Website auto-send is server-side now — each /dashboard/predict honors the flag.
        }
        accum[i] = entry;
        appendRow(entry, i);
      })
      .catch(function(err) {
        var entry = { row: row, error: 'Network: ' + err.message };
        accum[i] = entry;
        appendRow(entry, i);
      })
      .finally(function() {
        done++;
        updateProgress();
        if (done === total) finish();
        else launchOne();
      });
  }

  // Launch initial wave (concurrency-capped)
  var initialWave = Math.min(CONCURRENCY_CAP, total);
  for (var k = 0; k < initialWave; k++) {
    launchOne();
  }
}

function buildBatchRow(entry, idx) {
  var tr = document.createElement('tr');
  tr.className = 'ha-tr' + (entry.error ? ' row-error' : '');

  if (entry.error) {
    tr.innerHTML =
      '<td class="ha-td-num ha-mono">' + (idx + 1) + '</td>' +
      '<td colspan="2">' +
        '<div class="ha-td-cat">' + escHtml(entry.row.service_category || '—') + '</div>' +
        '<div class="ha-td-subdesc">' + escHtml((entry.row.job_description || '').substring(0, 80)) + '</div>' +
      '</td>' +
      '<td colspan="2" style="text-align:right">' +
        '<span class="ha-error-chip">' + ICON.alert + ' skipped — ' + escHtml(entry.error) + '</span>' +
      '</td>';
    return tr;
  }

  var r    = entry.result;
  var b    = band(r.confidence);
  var conf = r.confidence;

  // Build confidence bar
  var confBarHtml =
    '<div class="ha-td-conf-wrap">' +
      '<div style="flex:1;min-width:54px">' +
        '<div class="ha-ring-bar"><div class="ha-ring-barfill" style="width:' + (conf * 100).toFixed(1) + '%;background:' + TONE_COLOR[b.tone] + '"></div></div>' +
      '</div>' +
      '<span class="ha-td-conf-pct" style="color:' + TONE_COLOR[b.tone] + '">' + Math.round(conf * 100) + '%</span>' +
    '</div>';

  tr.innerHTML =
    '<td class="ha-td-num ha-mono">' + (idx + 1) + '</td>' +
    '<td>' +
      '<div class="ha-td-cat">' + escHtml(entry.row.service_category) + '</div>' +
      '<div class="ha-td-subdesc ha-td-desc">' + escHtml((entry.row.job_description || '').substring(0, 80)) + '</div>' +
    '</td>' +
    '<td class="ha-td-zip ha-mono">' + escHtml(entry.row.zip_code || '') + '</td>' +
    '<td class="ha-td-right">' +
      '<div class="ha-td-mid ha-num">' + usd(r.estimate_midpoint) + '</div>' +
      '<div class="ha-td-range">' + usd(r.estimate_lo) + '–' + usd(r.estimate_hi) + '</div>' +
    '</td>' +
    '<td style="width:140px">' + confBarHtml + '</td>';

  tr.addEventListener('click', function() { openDrawer(entry); });
  tr.addEventListener('mouseenter', function() { tr.style.background = 'var(--bg-soft)'; });
  tr.addEventListener('mouseleave', function() { tr.style.background = entry.error ? 'var(--bad-tint)' : 'transparent'; });

  return tr;
}

/* ---- Drawer ---- */

function openDrawer(entry) {
  batchState.drawerEntry = entry;
  var row = entry.row;
  var r   = entry.result;
  var b   = r ? band(r.confidence) : null;

  el('drawer-title').innerHTML =
    escHtml(row.service_category || '—') +
    '<span class="muted"> · ' + escHtml(row.service_subtype || '—') + '</span>';

  var bodyEl = el('drawer-body');
  bodyEl.innerHTML = '';

  if (entry.error) {
    var errDiv = document.createElement('div');
    errDiv.innerHTML =
      '<div class="ha-eyebrow" style="margin-bottom:8px">Error</div>' +
      '<p style="font-size:13px;color:var(--muted)">' + escHtml(entry.error) + '</p>' +
      '<div class="ha-eyebrow" style="margin:12px 0 8px">Booking</div>' +
      '<pre class="ha-mono" style="font-size:11.5px;color:var(--ink-soft);white-space:pre-wrap">' + escHtml(JSON.stringify(row, null, 2)) + '</pre>';
    bodyEl.appendChild(errDiv);
  } else {
    // Description
    var descDiv = document.createElement('div');
    descDiv.style.cssText = 'font-size:13px;color:var(--muted);line-height:1.5';
    descDiv.textContent = row.job_description || '';
    bodyEl.appendChild(descDiv);

    // ZIP / Deadline / Month
    var metaDiv = document.createElement('div');
    metaDiv.style.cssText = 'display:flex;gap:18px;font-size:12.5px';
    metaDiv.innerHTML =
      '<div><div class="ha-eyebrow">ZIP</div><div style="font-weight:700;margin-top:3px" class="ha-mono">' + escHtml(row.zip_code || '—') + '</div></div>' +
      '<div><div class="ha-eyebrow">Deadline</div><div style="font-weight:700;margin-top:3px">' + escHtml(row.deadline || '—') + '</div></div>' +
      '<div><div class="ha-eyebrow">Month</div><div style="font-weight:700;margin-top:3px" class="ha-mono">' + escHtml(row.booking_month || '—') + '</div></div>';
    bodyEl.appendChild(metaDiv);

    // Divider
    bodyEl.appendChild(Object.assign(document.createElement('div'), { className: 'ha-divider' }));

    // Midpoint
    var midDiv = document.createElement('div');
    midDiv.innerHTML =
      '<div class="ha-num" style="font-size:42px;font-weight:800;letter-spacing:-.02em;line-height:1">' + usd(r.estimate_midpoint) + '</div>' +
      '<div style="font-size:12.5px;color:var(--muted);margin-top:5px">estimate midpoint</div>';
    bodyEl.appendChild(midDiv);

    // Interval bar
    var ivDiv = document.createElement('div');
    ivDiv.className = 'ha-iv';
    var range  = r.estimate_hi - r.estimate_lo;
    var midPct = range > 0 ? ((r.estimate_midpoint - r.estimate_lo) / range * 100) : 50;
    ivDiv.innerHTML =
      '<div class="ha-iv-track">' +
        '<div class="ha-iv-fill"></div>' +
        '<div class="ha-iv-mid" style="left:calc(' + clamp(midPct, 2, 97) + '% - 2.5px)"></div>' +
      '</div>' +
      '<div class="ha-iv-ends ha-num"><span>low&nbsp; <b>' + usd(r.estimate_lo) + '</b></span><span>high&nbsp; <b>' + usd(r.estimate_hi) + '</b></span></div>';
    bodyEl.appendChild(ivDiv);

    // Divider
    bodyEl.appendChild(Object.assign(document.createElement('div'), { className: 'ha-divider' }));

    // Confidence ring + band
    var confRow = document.createElement('div');
    confRow.className = 'ha-conf-row';

    var ringEl = document.createElement('div');
    ringEl.className = 'ha-ring';
    renderConfidenceRing(ringEl, r.confidence, 62);

    var bandDiv = document.createElement('div');
    bandDiv.innerHTML =
      '<div style="font-size:14px;font-weight:800;color:' + TONE_COLOR[b.tone] + '">' + b.label + ' · ' + Math.round(r.confidence * 100) + '%</div>' +
      '<div style="font-size:12.5px;color:var(--muted);margin-top:3px;line-height:1.45">' + b.note + '</div>';

    confRow.appendChild(ringEl);
    confRow.appendChild(bandDiv);
    bodyEl.appendChild(confRow);

    // Flags
    if (r.uncertainties) {
      var flagsDiv = document.createElement('div');
      var flagLabel = document.createElement('div');
      flagLabel.className = 'ha-eyebrow';
      flagLabel.style.marginBottom = '9px';
      flagLabel.textContent = 'Why it might vary';
      flagsDiv.appendChild(flagLabel);

      var flagsWrap = document.createElement('div');
      flagsWrap.className = 'ha-flags';
      var flagList = String(r.uncertainties).split(/\s*;\s*/).filter(Boolean);
      renderFlagChips(flagsWrap, flagList, b.tone);
      flagsDiv.appendChild(flagsWrap);
      bodyEl.appendChild(flagsDiv);
    }
  }

  show(el('drawer-scrim'));
  show(el('detail-drawer'));
}

function closeDrawer() {
  hide(el('detail-drawer'));
  hide(el('drawer-scrim'));
  batchState.drawerEntry = null;
}

/* ---- JSON modal ---- */

function openJsonModal() {
  if (!batchState.rows) return;
  var payloads = batchState.rows.map(rowToPayload);
  el('json-modal-sub').textContent = payloads.length + ' bookings → JSON array';
  el('json-modal-pre').textContent = JSON.stringify(payloads, null, 2);
  show(el('json-modal-scrim'));
}

function closeJsonModal() {
  hide(el('json-modal-scrim'));
}

/* ---- Chart expand modal: clone a results chart into an enlarged overlay ---- */

function initChartExpand() {
  document.querySelectorAll('.ha-chart-expand-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
      openChartModal(btn.dataset.chart, btn.dataset.chartTitle);
    });
  });
  el('chart-modal-close').addEventListener('click', closeChartModal);
  el('chart-modal-scrim').addEventListener('click', function(e) {
    if (e.target === el('chart-modal-scrim')) closeChartModal();
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeChartModal(); closeJsonModal(); closeDrawer(); }
  });
}

function openChartModal(which, title) {
  var src = el(which === 'scatter' ? 'scatter-svg' : 'compare-chart');
  if (!src) return;
  var body = el('chart-modal-body');
  body.innerHTML = '';
  var clone = src.cloneNode(true);
  clone.removeAttribute('id');
  if (which === 'scatter') clone.setAttribute('style', 'display:block;width:100%;height:auto');
  body.appendChild(clone);
  el('chart-modal-title').textContent = title || 'Chart';
  show(el('chart-modal-scrim'));
}

function closeChartModal() {
  hide(el('chart-modal-scrim'));
  el('chart-modal-body').innerHTML = '';
}

/* ---- Export CSV ---- */

function exportBatchCsv() {
  var head = 'job_id,service_category,zip_code,estimate_lo,estimate_midpoint,estimate_hi,confidence,model_version';
  var lines = batchState.results
    .filter(function(e) { return e && e.result; })
    .map(function(e) {
      var r = e.result;
      return [
        e.row.job_id, e.row.service_category, e.row.zip_code,
        r.estimate_lo, r.estimate_midpoint, r.estimate_hi,
        r.confidence, r.model_version
      ].join(',');
    });
  var blob = new Blob([head + '\n' + lines.join('\n')], { type: 'text/csv' });
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'scored_bookings.csv';
  a.click();
  pushToast({ tone: 'ok', title: 'Export ready', body: 'scored_bookings.csv downloaded.' });
}

/* ============================================================
   RESULTS PANEL
   ============================================================ */

var resultsLoaded = false;

function loadResults() {
  if (resultsLoaded) return;
  resultsLoaded = true;

  // Show skeleton, hide loaded
  show(el('results-skeleton'));
  hide(el('results-loaded'));
  hide(el('metrics-unavailable'));

  // Fetch metrics + predictions in parallel
  Promise.all([
    fetch('/dashboard/metrics').then(function(res) {
      if (!res.ok) throw { status: res.status };
      return res.json();
    }),
    fetch('/dashboard/predictions').then(function(res) {
      if (!res.ok) return [];
      return res.json();
    }).catch(function() { return []; })
  ]).then(function(vals) {
    var metrics     = vals[0];
    var predictions = vals[1];

    // Small artificial delay to let skeleton shimmer (design says ~950ms)
    setTimeout(function() {
      hide(el('results-skeleton'));
      show(el('results-loaded'));
      renderStatCards(metrics);
      renderCompareChart(metrics);
      renderScatter(predictions);
      renderPredictionsTable(predictions);

      // Update caption
      var v = metrics.model_version || modelVersion;
      el('results-caption-sub').textContent = '411-row priced subset · ' + v;
      el('footer-version').textContent = v;
    }, 950);
  }).catch(function() {
    hide(el('results-skeleton'));
    show(el('metrics-unavailable'));
  });
}

/* ---- Stat cards ---- */

function renderStatCards(data) {
  // Values are ALREADY PERCENTAGES — do NOT multiply by 100
  var blended    = Number(data.blended);
  var baseBlended = Number(data.baseline_blended);
  var real       = Number(data.real_only);
  var baseReal   = Number(data.baseline_real);
  var cov        = Number(data.coverage);
  var targetCov  = 80;

  // Blended MAPE — pass = model < baseline
  var blendedPass = blended < baseBlended;
  var blendedDelta = blended - baseBlended; // negative = improvement
  renderStatCard(
    'sc-blended-val', 'sc-blended-base', 'sc-blended-delta', 'sc-blended-check',
    blended.toFixed(1) + '%',
    baseBlended.toFixed(1) + '%',
    blendedDelta,
    blendedPass,
    true   // goodWhenNegative
  );
  // Remove skeleton from card-blended
  var cardBlended = el('card-blended');
  if (cardBlended) cardBlended.classList.remove('skeleton');

  // Real-only MAPE
  var realPass = real < baseReal;
  var realDelta = real - baseReal;
  renderStatCard(
    'sc-real-val', 'sc-real-base', 'sc-real-delta', 'sc-real-check',
    real.toFixed(1) + '%',
    baseReal.toFixed(1) + '%',
    realDelta,
    realPass,
    true
  );
  var cardReal = el('card-real');
  if (cardReal) cardReal.classList.remove('skeleton');

  // Coverage — pass = cov >= 80
  var covPass = cov >= targetCov;
  var covDelta = cov - targetCov;
  renderStatCard(
    'sc-cov-val', 'sc-cov-base', 'sc-cov-delta', 'sc-cov-check',
    cov.toFixed(1) + '%',
    '≥80%',
    covDelta,
    covPass,
    false  // goodWhenPositive for coverage
  );
  var cardCov = el('card-cov');
  if (cardCov) cardCov.classList.remove('skeleton');
}

function renderStatCard(valId, baseId, deltaId, checkId, val, base, delta, pass, goodWhenNegative) {
  el(valId).textContent  = val;
  el(baseId).textContent = base;

  var good = goodWhenNegative ? delta < 0 : delta > 0;
  var arrow = delta < 0 ? '↓' : '↑';
  el(deltaId).textContent = arrow + ' ' + Math.abs(delta).toFixed(1) + 'pp vs baseline';
  el(deltaId).className = 'ha-stat-delta ' + (good ? 'good' : 'bad');

  var checkEl = el(checkId);
  checkEl.className = 'ha-pass-badge ' + (pass ? 'pass' : 'fail');
  checkEl.innerHTML = (pass ? ICON.check : ICON.x) + ' ' + (pass ? 'Pass' : 'Fail');
}

/* ---- Compare chart (grouped vertical bars) ---- */

function renderCompareChart(data) {
  var blended    = Number(data.blended);
  var baseBlended = Number(data.baseline_blended);
  var real       = Number(data.real_only);
  var baseReal   = Number(data.baseline_real);

  var chartEl = el('compare-chart');
  chartEl.innerHTML = '';

  var groups = [
    { name: 'Blended MAPE',  model: blended,  baseline: baseBlended },
    { name: 'Real-only MAPE', model: real,     baseline: baseReal   }
  ];

  var MAX_H = 158; // px for 100% bar (scale to max ~40%)
  var maxVal = Math.max(blended, baseBlended, real, baseReal, 1);

  groups.forEach(function(g) {
    var groupDiv = document.createElement('div');
    groupDiv.className = 'ha-bar-group';

    var pairDiv = document.createElement('div');
    pairDiv.className = 'ha-bar-pair';

    [
      { key: 'model',    color: 'var(--amber)', textColor: 'var(--ink)',   val: g.model    },
      { key: 'baseline', color: '#c6d0d8',      textColor: 'var(--muted)', val: g.baseline }
    ].forEach(function(bar) {
      var h = Math.round((bar.val / maxVal) * MAX_H);
      var colDiv = document.createElement('div');
      colDiv.className = 'ha-bar-col';

      var label = document.createElement('span');
      label.className = 'ha-bar-val-label';
      label.style.color = bar.textColor;
      label.textContent = bar.val.toFixed(1) + '%';

      var rect = document.createElement('div');
      rect.className = 'ha-bar-rect';
      rect.style.cssText = 'width:52px;height:0;background:' + bar.color + ';border-radius:7px 7px 0 0;transition:height .5s cubic-bezier(.2,.8,.3,1)';

      // Tooltip
      var tipText = (bar.key === 'model' ? 'Model' : 'Baseline') + ': ' + bar.val.toFixed(1) + '%';
      rect.title = tipText;

      colDiv.appendChild(label);
      colDiv.appendChild(rect);
      pairDiv.appendChild(colDiv);

      // Animate height
      setTimeout(function() { rect.style.height = h + 'px'; }, 80);
    });

    var groupLabel = document.createElement('div');
    groupLabel.className = 'ha-bar-group-label';
    groupLabel.textContent = g.name;

    groupDiv.appendChild(pairDiv);
    groupDiv.appendChild(groupLabel);
    chartEl.appendChild(groupDiv);
  });
}

/* ---- Scatter: predicted midpoint by confidence ---- */

function renderScatter(predictions) {
  var svg = el('scatter-svg');
  svg.innerHTML = '';

  var tooltip = el('scatter-tooltip');

  // Filter to rows with a parseable midpoint
  var pts = (predictions || []).map(function(row) {
    return {
      midpoint:   Number(row.estimate_midpoint),
      confidence: Number(row.confidence),
      job_id:     row.job_id,
      lo:         Number(row.estimate_lo),
      hi:         Number(row.estimate_hi)
    };
  }).filter(function(p) { return p.midpoint > 0 && p.confidence >= 0 && p.confidence <= 1; });

  if (!pts.length) {
    // No data — show a placeholder message
    var nodata = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    nodata.setAttribute('x', '240');
    nodata.setAttribute('y', '140');
    nodata.setAttribute('text-anchor', 'middle');
    nodata.setAttribute('font-size', '13');
    nodata.setAttribute('fill', 'var(--faint)');
    nodata.textContent = 'No prediction data available';
    svg.appendChild(nodata);
    return;
  }

  // Log10 scale: x = midpoint, y = midpoint (log)
  var W = 480, H = 280, padL = 44, padB = 36, padT = 12, padR = 12;

  var allMids = pts.map(function(p) { return p.midpoint; });
  var domMin  = Math.max(50,   Math.min.apply(null, allMids));
  var domMax  = Math.min(20000, Math.max.apply(null, allMids));
  if (domMin >= domMax) { domMax = domMin * 10; }

  var lmin = Math.log10(domMin * 0.8);
  var lmax = Math.log10(domMax * 1.2);

  function sx(v) { return padL + (Math.log10(Math.max(v, 1)) - lmin) / (lmax - lmin) * (W - padL - padR); }
  function sy(v) { return (H - padB) - (Math.log10(Math.max(v, 1)) - lmin) / (lmax - lmin) * (H - padT - padB); }

  // Grid lines + ticks
  var ticks = [100, 300, 500, 1000, 3000, 5000, 10000].filter(function(t) {
    return t > domMin * 0.5 && t < domMax * 2;
  }).slice(0, 6);

  ticks.forEach(function(t) {
    var yy = sy(t);
    if (yy < padT || yy > H - padB) return;

    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', padL); line.setAttribute('y1', yy);
    line.setAttribute('x2', W - padR); line.setAttribute('y2', yy);
    line.setAttribute('stroke', 'var(--line-soft)'); line.setAttribute('stroke-width', '1');
    svg.appendChild(line);

    var label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', padL - 6); label.setAttribute('y', yy + 3);
    label.setAttribute('text-anchor', 'end'); label.setAttribute('font-size', '9');
    label.setAttribute('fill', 'var(--faint)');
    label.setAttribute('font-family', 'var(--mono)');
    label.textContent = t >= 1000 ? '$' + (t / 1000) + 'k' : '$' + t;
    svg.appendChild(label);

    // X-axis ticks (same values on x)
    var xx = sx(t);
    if (xx > padL && xx < W - padR) {
      var xl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      xl.setAttribute('x', xx); xl.setAttribute('y', H - padB + 14);
      xl.setAttribute('text-anchor', 'middle'); xl.setAttribute('font-size', '9');
      xl.setAttribute('fill', 'var(--faint)');
      xl.setAttribute('font-family', 'var(--mono)');
      xl.textContent = t >= 1000 ? '$' + (t / 1000) + 'k' : '$' + t;
      svg.appendChild(xl);
    }
  });

  // Axis labels
  var yLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  yLabel.setAttribute('x', padL - 6); yLabel.setAttribute('y', padT + 4);
  yLabel.setAttribute('text-anchor', 'end'); yLabel.setAttribute('font-size', '9');
  yLabel.setAttribute('fill', 'var(--muted)'); yLabel.setAttribute('font-weight', '700');
  yLabel.textContent = 'midpoint →';
  svg.appendChild(yLabel);

  var xLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  xLabel.setAttribute('x', W - padR); xLabel.setAttribute('y', H - padB + 28);
  xLabel.setAttribute('text-anchor', 'end'); xLabel.setAttribute('font-size', '9');
  xLabel.setAttribute('fill', 'var(--muted)'); xLabel.setAttribute('font-weight', '700');
  xLabel.textContent = 'predicted →';
  svg.appendChild(xLabel);

  // Points
  pts.forEach(function(p, i) {
    var b    = band(p.confidence);
    var cx   = sx(p.midpoint);
    var cy   = sy(p.midpoint); // y = midpoint too (no actual prices)
    if (isNaN(cx) || isNaN(cy)) return;

    var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', cx.toFixed(1));
    circle.setAttribute('cy', cy.toFixed(1));
    circle.setAttribute('r', '4.5');
    circle.setAttribute('fill', TONE_COLOR[b.tone]);
    circle.setAttribute('fill-opacity', '0.85');
    circle.setAttribute('stroke', '#fff');
    circle.setAttribute('stroke-width', '1.4');
    circle.style.cursor = 'pointer';
    circle.style.transition = 'r .1s';

    circle.addEventListener('mouseenter', function() {
      circle.setAttribute('r', '7');
      tooltip.innerHTML =
        'pred ' + usd(p.midpoint) + '<br>confidence ' + Math.round(p.confidence * 100) + '%';
      show(tooltip);
    });
    circle.addEventListener('mouseleave', function() {
      circle.setAttribute('r', '4.5');
      hide(tooltip);
    });

    svg.appendChild(circle);
  });
}

/* ---- Predictions table ---- */

function renderPredictionsTable(rows) {
  if (!rows || !rows.length) return;

  var tbody = el('predictions-tbody');
  tbody.innerHTML = '';

  var display = rows.slice(0, 200);

  display.forEach(function(row) {
    var conf = Number(row.confidence);
    var b    = band(conf);
    var tr   = document.createElement('tr');
    tr.className = 'ha-tr';
    tr.innerHTML =
      '<td class="ha-mono" style="font-size:11px;color:var(--faint)">' + escHtml((row.job_id || '').substring(0, 14)) + '</td>' +
      '<td>' + escHtml(row.service_category || '—') + '</td>' +
      '<td style="text-align:right;font-variant-numeric:tabular-nums">' + usd(row.estimate_lo) + '</td>' +
      '<td style="text-align:right;font-weight:800;font-variant-numeric:tabular-nums">' + usd(row.estimate_midpoint) + '</td>' +
      '<td style="text-align:right;font-variant-numeric:tabular-nums">' + usd(row.estimate_hi) + '</td>' +
      '<td style="font-weight:800;color:' + TONE_COLOR[b.tone] + ';font-variant-numeric:tabular-nums">' + Math.round(conf * 100) + '%</td>';
    tbody.appendChild(tr);
  });

  show(el('predictions-section'));
}

/* ============================================================
   BOOKING FLOW — Control 1: Website → Booking
   ============================================================ */

/** Global state: whether website auto-send is currently enabled. */
var websiteAutosendOn = false;

/**
 * sendToBookingFlow — POST to /dashboard/booking.
 * Returns a Promise resolving to the server response JSON.
 * source: "website" | "manual"
 */
function sendToBookingFlow(opts) {
  return fetch('/dashboard/booking', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source:  opts.source  || 'manual',
      payload: opts.payload || {},
      result:  opts.result  || {}
    })
  }).then(function(res) {
    return res.json();
  });
}

/** Reload conversions only when the tab is active. */
function loadConversionsIfActive() {
  if (activeTab === 'conversions') loadConversions();
}

function initWebsiteAutosend() {
  var toggle = el('website-autosend-toggle');
  if (!toggle) return;

  toggle.addEventListener('click', function() {
    // Persist server-side so ANY /dashboard/predict (browser or curl) auto-sends when on.
    var next = !(toggle.getAttribute('aria-checked') === 'true');
    setSwitch(toggle, next);                      // optimistic; server response is authoritative
    fetch('/dashboard/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ website_auto_send: next })
    })
      .then(function(res) { return res.json(); })
      .then(function(cfg) {
        websiteAutosendOn = !!cfg.website_auto_send;
        setSwitch(toggle, websiteAutosendOn);
      })
      .catch(function() {
        setSwitch(toggle, !next);                 // revert on failure
        pushToast({ tone: 'bad', title: 'Could not update', body: 'Website auto-send change failed.' });
      });
  });
}

/* ============================================================
   SETTINGS POPOVER — Control 2: API → Booking, Control 3: Live mode
   ============================================================ */

/** Reflect a boolean on a ha-switch (aria-checked + .on class). */
function setSwitch(toggleEl, on) {
  if (!toggleEl) return;
  toggleEl.setAttribute('aria-checked', String(!!on));
  if (on) toggleEl.classList.add('on');
  else toggleEl.classList.remove('on');
}

/** Show/hide the header LIVE indicator badge based on live-mode state. */
function reflectLiveIndicator(on) {
  var ind = el('live-indicator');
  if (!ind) return;
  if (on) show(ind);
  else hide(ind);
}

function initSettings() {
  var settingsBtn = el('settings-btn');
  var popover     = el('settings-popover');
  var apiToggle   = el('api-autosend-toggle');
  var liveToggle  = el('live-mode-toggle');

  if (!settingsBtn || !popover) return;

  // Fetch initial config state — set BOTH toggles + the LIVE indicator
  fetch('/dashboard/config')
    .then(function(res) { return res.json(); })
    .then(function(cfg) {
      setSwitch(apiToggle, !!cfg.api_auto_send);
      setSwitch(liveToggle, !!cfg.live);
      reflectLiveIndicator(!!cfg.live);
      setSwitch(el('website-autosend-toggle'), !!cfg.website_auto_send);
      websiteAutosendOn = !!cfg.website_auto_send;
    })
    .catch(function() { /* best-effort */ });

  // Gear button opens/closes popover
  settingsBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    popover.classList.toggle('hidden');
  });

  // Close on outside click
  document.addEventListener('pointerdown', function(e) {
    var wrap = el('settings-wrap');
    if (wrap && !wrap.contains(e.target)) {
      hide(popover);
    }
  });

  // API auto-send toggle (Control 2)
  apiToggle.addEventListener('click', function() {
    var current = apiToggle.getAttribute('aria-checked') === 'true';
    var next    = !current;
    setSwitch(apiToggle, next);

    fetch('/dashboard/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_auto_send: next })
    })
      .then(function(res) { return res.json(); })
      .then(function(cfg) {
        setSwitch(apiToggle, !!cfg.api_auto_send);
      })
      .catch(function() {
        setSwitch(apiToggle, current); // revert
        pushToast({ tone: 'bad', title: 'Config update failed', body: 'Could not save API auto-send setting.' });
      });
  });

  // Live mode toggle (Control 3) — DANGEROUS: real staging bookings
  if (liveToggle) {
    liveToggle.addEventListener('click', function() {
      var current = liveToggle.getAttribute('aria-checked') === 'true';
      var next    = !current;

      // Turning ON requires explicit confirmation
      if (next) {
        var ok = window.confirm('Turn ON live mode? Sends will create REAL bookings on HouseAccount staging.');
        if (!ok) {
          // Cancelled — revert (keep OFF) and do nothing
          setSwitch(liveToggle, current);
          return;
        }
      }

      // Optimistic UI; server response is authoritative
      setSwitch(liveToggle, next);
      reflectLiveIndicator(next);

      fetch('/dashboard/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ live: next })
      })
        .then(function(res) { return res.json(); })
        .then(function(cfg) {
          var confirmed = !!cfg.live;
          setSwitch(liveToggle, confirmed);
          reflectLiveIndicator(confirmed);
          if (confirmed) {
            pushToast({ tone: 'amber', title: 'Live mode ON', body: 'Sends now create REAL bookings on staging.' });
          }
        })
        .catch(function() {
          setSwitch(liveToggle, current); // revert
          reflectLiveIndicator(current);
          pushToast({ tone: 'bad', title: 'Config update failed', body: 'Could not change live mode.' });
        });
    });
  }
}

/* ============================================================
   BATCH SEND-ALL BUTTON
   ============================================================ */

function initBatchSendAll() {
  var btn = el('batch-send-all-btn');
  if (!btn) return;

  btn.addEventListener('click', function() {
    var scored = batchState.results.filter(function(e) { return e && e.result; });
    if (!scored.length) return;

    btn.disabled = true;
    btn.textContent = 'Sending 0 / ' + scored.length + '…';

    var sent = 0;
    var promises = scored.map(function(entry) {
      return sendToBookingFlow({
        source:  'manual',
        payload: rowToPayload(entry.row),
        result:  entry.result
      }).then(function() {
        sent++;
        btn.textContent = 'Sending ' + sent + ' / ' + scored.length + '…';
      }).catch(function() {
        sent++;
      });
    });

    Promise.all(promises).then(function() {
      btn.textContent = 'Sent ' + sent + ' ✓';
      pushToast({ tone: 'ok', title: 'Batch sent', body: sent + ' row(s) sent to booking flow.' });
      loadConversionsIfActive();
    });
  });
}

/* ============================================================
   CONVERSIONS PANEL (4th tab)
   ============================================================ */

/**
 * loadConversions — GET /dashboard/conversions and render the table.
 * Called when the Conversions tab is opened or after any manual send.
 */
function loadConversions() {
  var loading  = el('conversions-loading');
  var empty    = el('conversions-empty');
  var tableWrap = el('conversions-table-wrap');
  var tbody    = el('conversions-tbody');

  if (!loading || !tbody) return;

  hide(empty);
  hide(tableWrap);
  show(loading);

  fetch('/dashboard/conversions')
    .then(function(res) {
      if (!res.ok) throw new Error('status ' + res.status);
      return res.json();
    })
    .then(function(rows) {
      hide(loading);
      tbody.innerHTML = '';

      if (!rows || !rows.length) {
        show(empty);
        return;
      }

      show(tableWrap);
      rows.forEach(function(row) {
        var tr = document.createElement('tr');
        tr.className = 'ha-tr';

        // Time: recorded_at (ISO string), show as local time
        var timeStr = '—';
        if (row.recorded_at) {
          try {
            var d = new Date(row.recorded_at);
            timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          } catch (_) { timeStr = String(row.recorded_at).substring(0, 19); }
        }

        // Source badge
        var srcLabel = escHtml(row.source || 'manual');

        // Category / job_id
        var cat   = escHtml(row.category || row.service_category || '—');
        var jobId = escHtml((row.job_id || '').substring(0, 18));

        // Midpoint
        var midStr = row.midpoint ? usd(row.midpoint) : '—';

        // Confidence
        var confPct = row.confidence ? Math.round(Number(row.confidence) * 100) + '%' : '—';

        // Live / Simulated / Failed badge. A live send is only LIVE if staging accepted it
        // (2xx); a non-2xx (e.g. 401 — rejected) is a FAILED send, not a success.
        var isLive = row.live === true;
        var statusOk = Number(row.status) >= 200 && Number(row.status) < 300;
        var badge = (isLive && !statusOk)
          ? '<span class="ha-conv-badge ha-conv-badge--failed">FAILED</span>'
          : isLive
            ? '<span class="ha-conv-badge ha-conv-badge--live">LIVE</span>'
            : '<span class="ha-conv-badge ha-conv-badge--sim">SIMULATED</span>';

        tr.innerHTML =
          '<td class="ha-mono" style="font-size:12px;color:var(--faint);white-space:nowrap">' + timeStr + '</td>' +
          '<td><span class="ha-conv-source">' + srcLabel + '</span></td>' +
          '<td>' +
            '<div class="ha-td-cat">' + cat + '</div>' +
            '<div class="ha-td-subdesc ha-mono">' + jobId + '</div>' +
          '</td>' +
          '<td style="text-align:right" class="ha-num">' + midStr + '</td>' +
          '<td class="ha-num" style="font-weight:700">' + confPct + '</td>' +
          '<td>' + badge + '</td>';

        tbody.appendChild(tr);
      });
    })
    .catch(function() {
      hide(loading);
      show(empty);
    });
}

/* ============================================================
   INIT
   ============================================================ */

document.addEventListener('DOMContentLoaded', function() {
  initTabs();
  initPredict();
  initBatch();
  initWebsiteAutosend();
  initSettings();
  initBatchSendAll();
  initChartExpand();
  probeApiStatus();
});

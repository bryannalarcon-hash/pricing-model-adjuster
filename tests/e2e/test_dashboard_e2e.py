"""
HouseAccount Pricing Dashboard — End-to-End Tests
Covers all functional paths via headless Chromium + Playwright.
Run: python3 -m pytest tests/e2e/test_dashboard_e2e.py -q
Stack must be live at http://127.0.0.1:3007/
"""

import csv
import json
import os
import re
import tempfile
import time

import pytest
import requests
from playwright.sync_api import sync_playwright, Page, expect

BASE_URL = "http://127.0.0.1:3007"
# The SPA is correctly served at /dashboard: relative asset paths (styles.css, app.js)
# resolve to /dashboard/styles.css and /dashboard/app.js which have routes.
# Serving at / also works in browsers but relative paths break (no /styles.css route).
SPA_URL = "http://127.0.0.1:3007/dashboard/"
BEARER_SECRET = "demo-secret"

# ---------------------------------------------------------------------------
# Shared browser fixture (one browser per module, one context per test)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    # Use /dashboard (not /) so that relative asset paths (styles.css, app.js)
    # resolve to /dashboard/styles.css and /dashboard/app.js, which the Rails
    # server routes correctly. The / route serves index.html with
    # Content-Disposition: attachment which Playwright interprets as a download.
    pg.goto(SPA_URL, wait_until="domcontentloaded")
    # Wait until the JS bundle has run (DOMContentLoaded fires initTabs)
    pg.wait_for_selector(".tab-btn.active", timeout=10000)
    yield pg
    ctx.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_csv(rows: list[dict]) -> str:
    """Write rows to a temp CSV file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        fieldnames = ["job_id", "service_category", "zip_code", "job_description", "original_estimate"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


GOOD_ROWS = [
    {
        "job_id": f"e2e-batch-{i}",
        "service_category": cat,
        "zip_code": "78704",
        "job_description": desc,
        "original_estimate": est,
    }
    for i, (cat, desc, est) in enumerate([
        ("Plumbing", "Leaky faucet repair in kitchen", 250),
        ("Electrical", "Install new ceiling fan in bedroom", 300),
        ("HVAC", "AC filter replacement and tune-up", 150),
        ("Painting", "Interior wall painting for living room", 800),
    ])
]

# One malformed row: missing job_description (required by validateBooking)
MALFORMED_ROW = {
    "job_id": "e2e-bad-row",
    "service_category": "",
    "zip_code": "00000",
    "job_description": "",
    "original_estimate": 100,
}

ALL_ROWS = GOOD_ROWS + [MALFORMED_ROW]


# ===========================================================================
# TEST 1: Page loads — header status, model badge, three tabs
# ===========================================================================

def test_page_load_header_status_and_tabs(page: Page):
    """Page loads; status dot goes 'online'; model badge appears; three tabs visible."""
    # Wait for API probe to complete
    page.wait_for_function(
        "() => document.getElementById('status-label').textContent !== 'Checking…'",
        timeout=8000,
    )

    status_label = page.locator("#status-label")
    assert status_label.inner_text() == "API connected", (
        f"Expected 'API connected', got: {status_label.inner_text()!r}"
    )

    status_dot = page.locator("#status-dot")
    assert "online" in (status_dot.get_attribute("class") or ""), (
        "Status dot should have class 'online'"
    )

    model_badge = page.locator("#model-badge")
    badge_text = model_badge.inner_text()
    assert badge_text and badge_text != "—", (
        f"Model badge should show version, got: {badge_text!r}"
    )

    # Three tabs
    for label in ["Predict", "Batch", "Results"]:
        btn = page.locator(f".tab-btn[data-panel]", has_text=label)
        assert btn.count() == 1, f"Tab '{label}' not found"
        assert btn.is_visible(), f"Tab '{label}' is not visible"


# ===========================================================================
# TEST 2: Predict happy path — Load sample → Predict → result card
# ===========================================================================

def test_predict_happy_path(page: Page):
    """Load sample → Predict → result card shows lo/midpoint/hi, confidence, uncertainties."""
    page.click("#load-sample-btn")

    # Verify textarea is populated
    raw = page.eval_on_selector("#booking-input", "el => el.value")
    booking = json.loads(raw)
    assert booking.get("service_category") == "Plumbing"

    # No request fired yet — intercept the next one
    with page.expect_response(lambda r: "/dashboard/predict" in r.url) as resp_info:
        page.click("#predict-btn")

    resp = resp_info.value
    assert resp.status == 200, f"Predict returned HTTP {resp.status}"
    data = resp.json()

    # Wait for result card to appear
    page.wait_for_selector("#result-card:not(.hidden)", timeout=8000)

    # estimate_lo
    lo_text = page.locator("#label-lo").inner_text()
    assert lo_text.startswith("$"), f"Low label should be a USD amount, got: {lo_text!r}"
    lo_val = float(lo_text.replace("$", "").replace(",", ""))
    assert abs(lo_val - data["estimate_lo"]) < 1, (
        f"Rendered lo {lo_val} != API lo {data['estimate_lo']}"
    )

    # estimate_midpoint
    mid_text = page.locator("#label-mid").inner_text()
    mid_val = float(mid_text.replace("$", "").replace(",", ""))
    assert abs(mid_val - data["estimate_midpoint"]) < 1, (
        f"Rendered mid {mid_val} != API mid {data['estimate_midpoint']}"
    )

    # estimate_hi
    hi_text = page.locator("#label-hi").inner_text()
    hi_val = float(hi_text.replace("$", "").replace(",", ""))
    assert abs(hi_val - data["estimate_hi"]) < 1, (
        f"Rendered hi {hi_val} != API hi {data['estimate_hi']}"
    )

    # Confidence %
    conf_text = page.locator("#confidence-value").inner_text()
    assert conf_text.endswith("%"), f"Confidence should end with %, got: {conf_text!r}"
    conf_pct = float(conf_text.replace("%", ""))
    expected_pct = data["confidence"] * 100
    assert abs(conf_pct - expected_pct) < 0.2, (
        f"Rendered confidence {conf_pct}% != expected {expected_pct:.1f}%"
    )

    # Uncertainties text present
    uncertainties_section = page.locator("#uncertainties-section")
    assert not uncertainties_section.get_attribute("class", timeout=2000).__contains__("hidden"), (
        "Uncertainties section should be visible"
    )
    uncertainty_items = page.locator("#uncertainties-list li")
    assert uncertainty_items.count() > 0, "At least one uncertainty item expected"


# ===========================================================================
# TEST 3: Predict malformed JSON — inline error, NO network request (AE1)
# ===========================================================================

def test_predict_malformed_json_no_network_call(page: Page):
    """Invalid JSON → inline error shown; no network request to /dashboard/predict."""
    requests_fired = []

    def capture_request(req):
        if "/dashboard/predict" in req.url:
            requests_fired.append(req.url)

    page.on("request", capture_request)

    # Put invalid JSON in the textarea
    page.fill("#booking-input", '{"job_id": "bad", "broken": }')
    page.click("#predict-btn")

    # Small wait to ensure any network call would have been observed
    page.wait_for_timeout(500)

    # Error element should be visible and contain a message
    err_el = page.locator("#json-error")
    assert "hidden" not in (err_el.get_attribute("class") or ""), (
        "json-error element should be visible"
    )
    err_text = err_el.inner_text()
    assert "Invalid JSON" in err_text or len(err_text) > 0, (
        f"Error message expected, got: {err_text!r}"
    )

    # Critically: no network request fired
    assert len(requests_fired) == 0, (
        f"AE1 violation: network request(s) fired on malformed JSON: {requests_fired}"
    )


# ===========================================================================
# TEST 4: Predict low-confidence / OOD — amber banner shows (confidence < 0.5)
# ===========================================================================

def test_predict_ood_low_confidence_banner(page: Page):
    """Booking with original_estimate ~7000 → low-confidence amber banner visible."""
    ood_booking = {
        "job_id": "e2e-ood-001",
        "service_category": "HVAC",
        "zip_code": "10001",
        "job_description": "Full commercial HVAC system overhaul, large building",
        "original_estimate": 7500,
    }

    page.fill("#booking-input", json.dumps(ood_booking, indent=2))

    with page.expect_response(lambda r: "/dashboard/predict" in r.url) as resp_info:
        page.click("#predict-btn")

    resp = resp_info.value
    data = resp.json()

    # Verify the API actually returned low confidence
    assert data["confidence"] < 0.5, (
        f"Expected confidence < 0.5 for OOD booking, got {data['confidence']}"
    )

    page.wait_for_selector("#result-card:not(.hidden)", timeout=8000)

    ood_banner = page.locator("#ood-banner")
    assert "hidden" not in (ood_banner.get_attribute("class") or ""), (
        f"OOD/low-confidence banner should be visible for confidence={data['confidence']}"
    )


# ===========================================================================
# TEST 5: No bearer secret in client source (AE2)
# ===========================================================================

def test_no_secret_in_client_source(page: Page):
    """The served page HTML and app.js must not contain the bearer secret."""
    # Check the HTML page source
    html_source = page.content()
    assert "demo-secret" not in html_source, "AE2: bearer secret found in page HTML"
    assert "Authorization: Bearer" not in html_source, (
        "AE2: Authorization header pattern found in page HTML"
    )

    # Check app.js content via HTTP
    js_resp = requests.get(f"{BASE_URL}/dashboard/app.js")
    assert js_resp.status_code == 200, "Could not fetch app.js"
    js_source = js_resp.text
    assert "demo-secret" not in js_source, "AE2: bearer secret found in app.js"
    assert "GAUNTLET_PRICING_SECRET" not in js_source, (
        "AE2: secret env var name found in app.js"
    )
    # Broad check: no Authorization Bearer pattern
    assert "Authorization" not in js_source or "Bearer" not in js_source, (
        "AE2: Authorization Bearer pattern found in app.js"
    )


# ===========================================================================
# TEST 6: Batch — CSV upload, JSON preview, run, good rows scored, bad row flagged,
#          detail drawer opens on scored row (AE3)
# ===========================================================================

def test_batch_csv_upload_and_run(page: Page, browser):
    """Upload CSV with 4 good + 1 bad row; batch runs; bad row flagged; drawer opens."""
    # Switch to Batch tab
    page.click(".tab-btn[data-panel='batch']")
    page.wait_for_selector("#panel-batch:not(.hidden)", timeout=3000)

    csv_path = _make_csv(ALL_ROWS)

    try:
        # Use file chooser to upload
        with page.expect_file_chooser() as fc_info:
            page.click("label[for='csv-file-input']")
        fc = fc_info.value
        fc.set_files(csv_path)

        # JSON preview section should appear
        page.wait_for_selector("#json-preview-section:not(.hidden)", timeout=5000)

        preview_text = page.locator("#json-preview").inner_text()
        assert len(preview_text) > 10, "JSON preview should have content"

        # Row count indicator
        row_count_text = page.locator("#json-row-count").inner_text()
        assert "5" in row_count_text, (
            f"Expected 5 rows in count label, got: {row_count_text!r}"
        )

        # Run batch button enabled
        run_btn = page.locator("#batch-run-btn")
        assert not run_btn.is_disabled(), "Run batch button should be enabled after CSV load"

        # Run batch — wait for table to appear
        run_btn.click()
        page.wait_for_selector("#batch-table-wrap:not(.hidden)", timeout=30000)

        # Count rows
        rows = page.locator("#batch-tbody tr")
        assert rows.count() == 5, f"Expected 5 rows in batch table, got {rows.count()}"

        # Find scored (ok) rows — should have status chip with checkmark
        ok_rows = page.locator("#batch-tbody tr:not(.row-error)")
        error_rows = page.locator("#batch-tbody tr.row-error")

        assert ok_rows.count() >= 4, (
            f"Expected >=4 scored rows, got {ok_rows.count()}"
        )
        assert error_rows.count() >= 1, (
            f"Expected >=1 error/flagged row, got {error_rows.count()}"
        )

        # Summary shows scored count
        summary_text = page.locator("#batch-summary").inner_text()
        assert "scored" in summary_text, (
            f"Batch summary should mention 'scored', got: {summary_text!r}"
        )
        assert "skipped" in summary_text or "flagged" in summary_text, (
            f"Batch summary should mention skipped/flagged row, got: {summary_text!r}"
        )

        # Click a scored row → detail drawer opens
        first_ok = ok_rows.first
        first_ok.click()

        page.wait_for_selector("#detail-drawer:not(.hidden)", timeout=3000)
        drawer_body = page.locator("#drawer-body")
        drawer_text = drawer_body.inner_text()
        assert "$" in drawer_text, "Drawer should show USD estimate values"
        assert "Confidence" in drawer_text or "%" in drawer_text, (
            "Drawer should show confidence"
        )
        # Uncertainties in drawer
        assert len(drawer_text) > 50, "Drawer body should have meaningful content"

        # Close drawer
        page.click("#drawer-close")
        # Wait for the hidden class to be applied (drawer is display:none via .hidden)
        page.wait_for_function(
            "() => document.getElementById('detail-drawer').classList.contains('hidden')",
            timeout=3000,
        )

    finally:
        os.unlink(csv_path)


# ===========================================================================
# TEST 7: Results panel — stat cards show correct values, predictions table populated
# ===========================================================================

def test_results_panel_metrics_and_predictions(page: Page):
    """Results tab: MAPE/coverage cards show correct values; predictions table populated."""
    # Get expected values from API directly
    api_metrics = requests.get(f"{BASE_URL}/dashboard/metrics").json()

    page.click(".tab-btn[data-panel='results']")
    page.wait_for_selector("#panel-results:not(.hidden)", timeout=3000)

    # Wait for metrics to load (skeleton class removed)
    page.wait_for_function(
        "() => !document.getElementById('card-blended').classList.contains('skeleton')",
        timeout=8000,
    )

    # --- Blended MAPE ---
    blended_val_text = page.locator("#sc-blended-val").inner_text()
    assert blended_val_text.endswith("%"), (
        f"Blended MAPE value should end with %, got: {blended_val_text!r}"
    )
    blended_val = float(blended_val_text.replace("%", ""))
    expected_blended = api_metrics["blended"]  # already a percentage: 10.49
    assert abs(blended_val - expected_blended) < 0.2, (
        f"Blended MAPE displayed as {blended_val}% but API says {expected_blended}% "
        f"(bug: multiplied by 100?)"
    )

    # Verify it is NOT multiplied by 100 (the known bug)
    assert blended_val < 100, (
        f"Blended MAPE {blended_val}% looks like it was multiplied by 100 "
        f"(expected ~{expected_blended})"
    )

    # --- Real-only MAPE ---
    real_val_text = page.locator("#sc-real-val").inner_text()
    real_val = float(real_val_text.replace("%", ""))
    expected_real = api_metrics["real_only"]  # 26.22
    assert abs(real_val - expected_real) < 0.2, (
        f"Real-only MAPE displayed as {real_val}% but API says {expected_real}%"
    )
    assert real_val < 100, "Real-only MAPE should not be multiplied by 100"

    # --- Coverage ---
    cov_val_text = page.locator("#sc-cov-val").inner_text()
    cov_val = float(cov_val_text.replace("%", ""))
    expected_cov = api_metrics["coverage"]  # 82.7
    assert abs(cov_val - expected_cov) < 0.2, (
        f"Coverage displayed as {cov_val}% but API says {expected_cov}%"
    )
    assert cov_val < 100, "Coverage should not be multiplied by 100"

    # Coverage pass check — 82.7 >= 80 so should pass
    cov_check_text = page.locator("#sc-cov-check").inner_text()
    assert "Pass" in cov_check_text, (
        f"Coverage {cov_val}% >= 80% should show Pass, got: {cov_check_text!r}"
    )

    # Blended MAPE pass check — 10.49 < 11.56 baseline → Pass
    blended_check_text = page.locator("#sc-blended-check").inner_text()
    assert "Pass" in blended_check_text, (
        f"Blended MAPE {blended_val}% < baseline {api_metrics['baseline_blended']}% should Pass, "
        f"got: {blended_check_text!r}"
    )

    # --- Predictions table populated ---
    page.wait_for_selector("#predictions-section:not(.hidden)", timeout=5000)
    rows = page.locator("#predictions-tbody tr")
    assert rows.count() > 0, "Predictions table should have at least one row"

    # Spot-check first row has USD values
    first_row_text = rows.first.inner_text()
    assert "$" in first_row_text, "Predictions table row should contain USD values"


# ===========================================================================
# TEST 8: AE4 — Contract fidelity: UI prediction matches direct API call
# ===========================================================================

def test_ae4_contract_fidelity_ui_matches_api(page: Page):
    """A prediction shown in the UI matches a direct POST to /dashboard/predict."""
    # Build a deterministic test booking
    booking = {
        "job_id": "e2e-fidelity-001",
        "service_category": "Plumbing",
        "zip_code": "78704",
        "job_description": "Replace kitchen faucet, standard single-handle",
        "original_estimate": 400,
    }

    page.fill("#booking-input", json.dumps(booking, indent=2))

    with page.expect_response(lambda r: "/dashboard/predict" in r.url) as resp_info:
        page.click("#predict-btn")

    resp = resp_info.value
    ui_data = resp.json()

    page.wait_for_selector("#result-card:not(.hidden)", timeout=8000)

    # Direct API call with same payload
    api_resp = requests.post(
        f"{BASE_URL}/dashboard/predict",
        json=booking,
        headers={"Content-Type": "application/json"},
    )
    assert api_resp.status_code == 200, f"Direct API call failed: {api_resp.status_code}"
    api_data = api_resp.json()

    # The model is deterministic for the same payload — values must match
    assert abs(ui_data["estimate_lo"] - api_data["estimate_lo"]) < 1, (
        f"estimate_lo mismatch: UI={ui_data['estimate_lo']} API={api_data['estimate_lo']}"
    )
    assert abs(ui_data["estimate_midpoint"] - api_data["estimate_midpoint"]) < 1, (
        f"estimate_midpoint mismatch: UI={ui_data['estimate_midpoint']} API={api_data['estimate_midpoint']}"
    )
    assert abs(ui_data["estimate_hi"] - api_data["estimate_hi"]) < 1, (
        f"estimate_hi mismatch: UI={ui_data['estimate_hi']} API={api_data['estimate_hi']}"
    )
    assert abs(ui_data["confidence"] - api_data["confidence"]) < 0.01, (
        f"confidence mismatch: UI={ui_data['confidence']} API={api_data['confidence']}"
    )

    # Verify UI renders the midpoint correctly
    mid_text = page.locator("#label-mid").inner_text()
    rendered_mid = float(mid_text.replace("$", "").replace(",", ""))
    assert abs(rendered_mid - api_data["estimate_midpoint"]) < 1, (
        f"Rendered midpoint {rendered_mid} != API {api_data['estimate_midpoint']}"
    )

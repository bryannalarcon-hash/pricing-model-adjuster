"""Confidence/OOD spec tests + inference contract + integration signing."""
import hashlib
import hmac
import os

import pytest

from houseprice.confidence import ConfidenceCalibrator, OOD_MIDPOINT


@pytest.fixture
def cal():
    # observed ranges ~ small ($200), model intervals moderate
    import numpy as np
    rng = np.random.RandomState(0)
    mid = rng.uniform(200, 500, 300)
    lo = mid * 0.85
    hi = mid * 1.15
    observed = rng.uniform(150, 300, 1432)
    return ConfidenceCalibrator.fit(lo, hi, mid, observed)


def test_confidence_in_unit_interval(cal):
    c, _ = cal.score(180, 220, 200, in_production=True)
    assert 0.0 <= c <= 1.0


def test_ood_midpoint_forces_low(cal):
    c, flags = cal.score(4000, 9000, 6000, in_production=True)  # > $5k midpoint
    assert flags["ood_midpoint"] is True
    assert c < 0.5


def test_ood_category_forces_low(cal):
    c, flags = cal.score(180, 220, 200, in_production=False)  # outside production verticals
    assert flags["ood_category"] is True
    assert c < 0.5


def test_ood_wide_interval_forces_low(cal):
    # interval >> 3x median observed range -> low confidence
    c, flags = cal.score(100, 5000, 2500, in_production=True)
    assert flags["ood_interval"] is True
    assert c < 0.5


def test_in_distribution_is_confident(cal):
    c, flags = cal.score(180, 220, 200, in_production=True)
    assert not any(flags.values())
    assert c >= 0.5


def test_density_aware_confidence():
    """Sparse in-production categories get lower confidence than well-supported ones at equal
    interval width (data-density awareness)."""
    import numpy as np
    rng = np.random.RandomState(0)
    cal = ConfidenceCalibrator.fit(
        rng.uniform(170, 230, 100), rng.uniform(170, 230, 100), np.full(100, 200),
        rng.uniform(150, 300, 1000), cat_counts={"Cleaning": 66, "Plumbing": 3})
    dense, _ = cal.score(180, 220, 200, in_production=True, category="Cleaning")
    sparse, _ = cal.score(180, 220, 200, in_production=True, category="Plumbing")
    assert sparse < dense


# ---- inference contract (needs a trained bundle) ----
BUNDLE = os.path.join(os.path.dirname(__file__), "..", "model", "bundle.pkl")


@pytest.mark.skipif(not os.path.exists(BUNDLE), reason="model not trained yet")
def test_predict_one_schema():
    from houseprice.predict import load_bundle, predict_one
    b = load_bundle()
    out = predict_one(b, {
        "job_id": "x", "service_category": "Plumbing", "zip_code": "78704",
        "job_description": "water heater replacement", "original_estimate": 1850,
        "original_estimate_lo": 1400, "original_estimate_hi": 2300,
    })
    for k in ("estimate_lo", "estimate_hi", "estimate_midpoint", "confidence", "model_version"):
        assert k in out
    assert out["estimate_lo"] <= out["estimate_midpoint"] <= out["estimate_hi"]
    assert 0.0 <= out["confidence"] <= 1.0


@pytest.mark.skipif(not os.path.exists(BUNDLE), reason="model not trained yet")
def test_predict_minimal_request_no_estimate():
    """Only the 4 required fields — must still price via category anchor (not crash)."""
    from houseprice.predict import load_bundle, predict_one
    out = predict_one(load_bundle(), {
        "job_id": "m", "service_category": "Cleaning", "zip_code": "75062",
        "job_description": "window wash 20 windows",
    })
    assert out["estimate_midpoint"] > 0
    assert out["estimate_lo"] <= out["estimate_hi"]


def test_hmac_signing_recipe():
    """Lock the verified signing recipe: HMAC-SHA256(ts + '.' + body), key as UTF-8 string."""
    from integration.sign_and_post import sign
    h = sign("{}", "gauntlet", "secretkey")
    expected = hmac.new(b"secretkey", (h["App-Timestamp"] + ".{}").encode(), hashlib.sha256).hexdigest()
    # rebuild with the same ts the function used
    base = f'{h["App-Timestamp"]}.' + "{}"
    expected = hmac.new(b"secretkey", base.encode(), hashlib.sha256).hexdigest()
    assert h["App-Signature"] == expected
    assert h["App-Name"] == "gauntlet"

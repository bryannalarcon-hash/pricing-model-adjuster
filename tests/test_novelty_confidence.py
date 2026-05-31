"""Option 2 regression tests: feature-space novelty must lower confidence.

Guards the gap surfaced earlier — a bizarre/novel description in a KNOWN category at a NORMAL
price (no OOD price/interval/category flag) used to get ~0.85 confidence. After the novelty
integration it must drop (and extreme novelty forces < 0.5 via a 4th OOD gate).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import pytest
from houseprice.predict import load_bundle, predict_one


@pytest.fixture(scope="module")
def bundle():
    return load_bundle()


def _predict(bundle, desc, est=300.0, cat="Cleaning"):
    return predict_one(bundle, {
        "job_id": "t", "service_category": cat, "zip_code": "78704",
        "job_description": desc, "original_estimate": est,
        "estimate_lo": est * 0.85, "estimate_hi": est * 1.15,
        "deadline": "I'm flexible", "booking_month": "2024-06",
    })


def test_calibrator_carries_novelty_reference(bundle):
    cal = bundle["calibrator"]
    assert getattr(cal, "novelty_ref", None), "calibrator must carry a training-novelty reference"


def test_score_novelty_lowers_confidence(bundle):
    """Same interval/category/price — only novelty differs — must lower confidence; extreme novelty < 0.5."""
    cal = bundle["calibrator"]
    typical, _ = cal.score(270, 330, 300, True, category="Cleaning", novelty=cal.novelty_ref)
    novel, flags = cal.score(270, 330, 300, True, category="Cleaning", novelty=cal.novelty_p95 * 1.5)
    assert novel < typical, f"novel booking should be less confident: {novel} vs {typical}"
    assert novel < 0.5, f"extreme novelty should force confidence < 0.5, got {novel}"
    assert flags.get("ood_novelty") is True, "extreme novelty should raise the ood_novelty flag"


def test_normal_booking_stays_confident(bundle):
    r = _predict(bundle, "Standard 2 bedroom apartment deep clean")
    assert r["confidence"] > 0.55, f"a normal in-distribution booking should stay confident, got {r['confidence']}"


def test_gibberish_description_less_confident_end_to_end(bundle):
    normal = _predict(bundle, "Standard 2 bedroom apartment deep clean")["confidence"]
    weird = _predict(bundle, "xqzj wkpfl 88273 zzz vvvv 9912 nonsense gibberish foobar " * 4)["confidence"]
    assert weird < normal, f"novel/gibberish booking should be less confident than a normal one: {weird} vs {normal}"

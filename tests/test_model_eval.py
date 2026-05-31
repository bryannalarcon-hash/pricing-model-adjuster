"""Core model + eval tests, including the headline regression: beat both MAPE baselines."""
import numpy as np
import pytest

from houseprice.data_load import load_dataset, labeled, normalize_category, is_production_category
from houseprice.eval import ape, mape, baseline_blended
from houseprice.features import build_features
from houseprice.model_v2 import oof_predict  # deployed v2 architecture
from houseprice.train import metrics_payload


@pytest.fixture(scope="module")
def df():
    return load_dataset()


def test_dataset_shape(df):
    assert len(df) == 1432
    assert int(df["is_labeled"].sum()) == 411
    assert df["category"].nunique() == 18


def test_category_normalization():
    assert normalize_category("plumbing") == "Plumbing"
    assert normalize_category("HVAC") == "HVAC"
    assert normalize_category("pest-control") == "Pest Control"


def test_production_mapping():
    assert is_production_category("Plumbing") is True
    assert is_production_category("HVAC") is True
    assert is_production_category("Moving") is False   # outside the 10 production verticals
    assert is_production_category("Roofing") is False
    # Unknown/unmapped categories must be treated as out-of-production (OOD -> low confidence).
    assert is_production_category("Underwater Basket Weaving") is False
    assert is_production_category("") is False


def test_mape_helpers():
    assert mape([100, 100], [100, 100]) == 0.0
    assert ape([110], [100])[0] == pytest.approx(0.1)


def test_baseline_reproduces_official(df):
    # The official blended baseline is 11.6% — our harness must reproduce it.
    assert baseline_blended(labeled(df)) == pytest.approx(11.56, abs=0.1)


def test_model_beats_both_baselines(df):
    """REGRESSION GATE: leakage-free OOF must beat blended (11.56%) AND real-only (~37%)."""
    lab = labeled(df).reset_index(drop=True)
    lo, mid, hi = oof_predict(lab, build_features)
    base = ape(lab["original_estimate"], lab["final_price"])
    real_mask = base > 0.20

    blended = mape(mid, lab["final_price"])
    real = mape(mid[real_mask], lab["final_price"].values[real_mask])
    base_blended = baseline_blended(lab)
    base_real = 100 * base[real_mask].mean()

    assert blended < base_blended, f"blended {blended:.2f} !< {base_blended:.2f}"
    assert real < base_real, f"real-only {real:.2f} !< {base_real:.2f}"
    # interval coverage near the 80% target (CQR)
    cov = ((lab["final_price"].values >= lo) & (lab["final_price"].values <= hi)).mean()
    assert 0.72 <= cov <= 0.92, f"coverage {cov:.2f} off target"


def test_metrics_payload_keys_and_types():
    """metrics_payload is a pure helper: verify schema and numeric contract."""
    payload = metrics_payload(
        blended=10.47, real=26.58, cov=0.832,
        base_blended=11.56, base_real=37.20, n_real=183,
    )
    expected_keys = {
        "model_version", "blended", "real_only", "coverage",
        "baseline_blended", "baseline_real", "n_real", "generated_for",
    }
    assert expected_keys == set(payload.keys()), "unexpected or missing keys"

    # numeric fields are Python scalars (JSON-serialisable), not numpy types
    for key in ("blended", "real_only", "coverage", "baseline_blended", "baseline_real"):
        assert isinstance(payload[key], float), f"{key} must be float, got {type(payload[key])}"
    assert isinstance(payload["n_real"], int), "n_real must be int"

    # rounding contract
    assert payload["blended"] == round(10.47, 2)
    assert payload["real_only"] == round(26.58, 2)
    assert payload["coverage"] == round(0.832 * 100, 1)
    assert payload["n_real"] == 183
    assert payload["generated_for"] == "labeled-oof"

    # model must beat baseline (the regression gate in numeric form)
    assert payload["blended"] < payload["baseline_blended"], (
        f"blended {payload['blended']} must be < baseline {payload['baseline_blended']}"
    )
    assert payload["real_only"] < payload["baseline_real"], (
        f"real_only {payload['real_only']} must be < baseline_real {payload['baseline_real']}"
    )


def test_no_leakage_in_oof(df):
    """OOF predictions must come from models that never saw the row: monkey-check that
    shuffling final_price destroys the result (a leaky pipeline would still 'predict' it)."""
    lab = labeled(df).reset_index(drop=True).copy()
    rng = np.random.RandomState(0)
    lab["final_price"] = rng.permutation(lab["final_price"].values)
    _, mid, _ = oof_predict(lab, build_features)
    shuffled_mape = mape(mid, lab["final_price"])
    # With labels shuffled, predictions (driven by original_estimate/features) should be FAR
    # from the shuffled targets — proving we aren't memorizing the label.
    assert shuffled_mape > 25.0

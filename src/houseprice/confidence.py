"""Confidence + OOD layer (PRD §Confidence calibration).

Confidence in [0,1]: high when the conformal interval is tight relative to the typical interval,
lower as it widens. THREE hard OOD conditions force confidence < 0.5 (do not reject/cap the
estimate itself — pass it through with low confidence):
  1. estimate_midpoint > $5,000
  2. prediction interval (hi-lo) > 3× the median observed range
  3. service_category outside the 10 production verticals

PRD threshold semantics for reference: >=0.8 obvious, 0.5-0.8 ambiguous, <0.5 guess.
"""
from __future__ import annotations

from dataclasses import dataclass

OOD_MIDPOINT = 5000.0
OOD_INTERVAL_MULT = 3.0
OOD_CONF_CEIL = 0.45  # forced ceiling when any OOD condition holds (< 0.5)


SUPPORT_FULL_N = 25       # category labels at/above which support penalty = none
SUPPORT_FLOOR = 0.70      # min support multiplier for very sparse in-production categories


@dataclass
class ConfidenceCalibrator:
    median_range: float                     # median observed estimate range (OOD reference)
    width_ref: float                        # median model relative interval width (base curve)
    cat_support: dict = None                # category -> training label count (data-density)

    @classmethod
    def fit(cls, lo, hi, mid, observed_ranges, cat_counts=None):
        """median_range = median OBSERVED estimate range (PRD OOD reference). width_ref = median
        model relative interval width. cat_counts = per-category training label counts, used to
        damp confidence for sparsely-supported (in-production) categories."""
        import numpy as np
        lo, hi, mid = map(lambda a: np.asarray(a, float), (lo, hi, mid))
        rel = (hi - lo) / np.clip(mid, 1, None)
        med_obs = float(np.median(np.asarray(observed_ranges, float)))
        return cls(median_range=med_obs, width_ref=float(np.median(rel)) or 0.3,
                   cat_support=dict(cat_counts) if cat_counts else {})

    def _support_factor(self, category) -> float:
        """≤1 multiplier: sparse categories (few training labels) -> lower confidence. A Plumbing
        prediction (3 labels) is genuinely less certain than a Cleaning one (66), even at equal
        interval width — the global conformal pad can't see per-category data density."""
        if not self.cat_support or category is None:
            return 1.0
        n = self.cat_support.get(category, 0)
        frac = min(n / SUPPORT_FULL_N, 1.0)
        return SUPPORT_FLOOR + (1.0 - SUPPORT_FLOOR) * frac

    def score(self, lo: float, hi: float, mid: float, in_production: bool, category=None):
        """Return (confidence in [0,1], ood_flags dict)."""
        interval = max(hi - lo, 0.0)
        rel = interval / max(mid, 1.0)
        ratio = rel / max(self.width_ref, 1e-6)          # 1.0 == typical width
        base = 1.05 - 0.25 * ratio                       # typical -> ~0.80
        conf = max(0.05, min(0.95, base)) * self._support_factor(category)

        flags = {
            "ood_midpoint": bool(mid > OOD_MIDPOINT),
            "ood_interval": bool(interval > OOD_INTERVAL_MULT * self.median_range),
            "ood_category": bool(not in_production),
        }
        if any(flags.values()):
            conf = min(conf, OOD_CONF_CEIL)
        return round(float(max(0.0, min(1.0, conf))), 3), flags


def uncertainties_text(flags: dict, rel_width: float) -> str:
    """Human-readable 'why the price might vary' for the booking `uncertainties` field."""
    msgs = []
    if flags.get("ood_midpoint"):
        msgs.append("large job (>$5k) outside the typical training range")
    if flags.get("ood_interval"):
        msgs.append("wide price range — scope is ambiguous from the description")
    if flags.get("ood_category"):
        msgs.append("service category outside the current production set")
    if not msgs:
        if rel_width > 0.4:
            msgs.append("moderate scope uncertainty from the description")
        else:
            msgs.append("scope well-constrained; price expected to hold")
    return "; ".join(msgs)

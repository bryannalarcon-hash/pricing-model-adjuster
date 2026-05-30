"""FastAPI inference sidecar (the model layer behind Rails).

Loads the trained bundle once at startup; Rails proxies validated bookings to POST /infer.
Run: uvicorn houseprice.infer_service:app --host 127.0.0.1 --port 8011
"""
from __future__ import annotations

import os
from fastapi import FastAPI
from pydantic import BaseModel

from .predict import load_bundle, predict_one
from . import MODEL_VERSION

app = FastAPI(title="HouseAccount pricing sidecar", version=MODEL_VERSION)
_BUNDLE = None


def bundle():
    global _BUNDLE
    if _BUNDLE is None:
        _BUNDLE = load_bundle()
    return _BUNDLE


class Booking(BaseModel):
    job_id: str | None = None
    service_category: str | None = None
    service_subtype: str | None = None
    zip_code: str | None = None
    job_description: str | None = None
    deadline: str | None = None
    booking_month: str | None = None
    job_status: str | None = None
    original_estimate: float | None = None
    original_estimate_lo: float | None = None
    original_estimate_hi: float | None = None

    model_config = {"extra": "allow"}


@app.get("/health")
def health():
    b = bundle()
    return {"ok": True, "model_version": b.get("model_version", MODEL_VERSION),
            "scope_backend": os.environ.get("SCOPE_BACKEND", b.get("scope_backend", "deterministic")),
            "trained_rows": b.get("trained_rows")}


@app.post("/infer")
def infer(booking: Booking):
    out = predict_one(bundle(), booking.model_dump())
    return {
        "estimate_lo": out["estimate_lo"], "estimate_hi": out["estimate_hi"],
        "estimate_midpoint": out["estimate_midpoint"], "confidence": out["confidence"],
        "coverage": out["coverage"], "uncertainties": out["uncertainties"],
        "model_version": out["model_version"], "ood": out["ood"],
    }

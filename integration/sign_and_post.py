"""HouseAccount staging booking integration (surface B: me -> them).

Auth = HMAC request signing (verified live): App-Signature = HMAC_SHA256(ts + "." + body) with
the signing key as raw UTF-8 string bytes; headers App-Name, App-Timestamp.

Write-safety policy (no GET/DELETE/dry-run exist on staging):
  --probe  : correctly-signed INVALID body -> expect 422 (auth ok) / 401 (auth bad). Writes nothing.
  --post   : create EXACTLY ONE tagged, disposable booking; log id to staging_bookings.log.
Default is --probe. Real ZIP required ("ZIP must exist"); PII is synthetic and clearly tagged.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("HOUSEACCOUNT_BASE", "https://pro.houseparty.dev")
BOOKINGS_URL = BASE + "/api/bookings"
LOG = os.path.join(ROOT, "staging_bookings.log")


def _env(key, default=""):
    v = os.environ.get(key)
    if v:
        return v
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
    return default


def sign(body: str, app_name: str, key: str):
    ts = str(int(time.time()))
    sig = hmac.new(key.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "App-Name": app_name,
            "App-Timestamp": ts, "App-Signature": sig}


def _send(body: str, headers: dict):
    req = urllib.request.Request(BOOKINGS_URL, data=body.encode(), method="POST", headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=25)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def probe() -> bool:
    """Zero-write connectivity + auth check. Returns True if auth path is healthy."""
    app_name, key = _env("HOUSEACCOUNT_APP_NAME"), _env("HOUSEACCOUNT_SIGNING_KEY")
    body = "{}"  # all required fields missing -> validation rejects, nothing created
    code, txt = _send(body, sign(body, app_name, key))
    ok = code in (400, 422)  # reached validation => signature accepted
    print(f"[probe] HTTP {code} (auth {'OK' if ok else 'FAILED'}): {txt[:160]}")
    # also confirm a bad signature is rejected
    bad = sign(body, app_name, key); bad["App-Signature"] = "deadbeef"
    c2, t2 = _send(body, bad)
    print(f"[probe] bad-sig HTTP {c2} (expect 401): {t2[:80]}")
    return ok and c2 == 401


def build_booking(pred: dict, row: dict) -> dict:
    """Construct ONE tagged, disposable booking from a priced dataset row."""
    desc = (row.get("job_description") or "home service job")[:400]
    return {
        "name": "Gauntlet Test",
        "phone": "5555550100",
        "zip": str(row.get("zip_code") or "78704"),
        "summary": f"[GAUNTLET TEST] {desc}",
        "comment": "Synthetic test booking from the Gauntlet pricing-model integration. Safe to delete.",
        "deadline": row.get("deadline") or "I'm flexible",
        "estimate": {"min": pred["estimate_lo"], "max": pred["estimate_hi"]},
        "coverage": pred.get("coverage", ""),
        "uncertainties": pred.get("uncertainties", ""),
        "confirmation": f"Estimated ${pred['estimate_midpoint']:.0f} "
                        f"(confidence {pred['confidence']:.2f}) by {pred['model_version']}.",
        "campaign": {"utm_source": "gauntlet-test", "utm_campaign": "pricing-model"},
    }


def post_one(booking: dict) -> dict:
    app_name, key = _env("HOUSEACCOUNT_APP_NAME"), _env("HOUSEACCOUNT_SIGNING_KEY")
    body = json.dumps(booking)
    code, txt = _send(body, sign(body, app_name, key))
    rec = {"ts": int(time.time()), "http": code, "summary": booking["summary"], "response": txt[:500]}
    with open(LOG, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(f"[post] HTTP {code}: {txt[:300]}")
    print(f"[post] logged to {LOG}")
    return rec


def _priced_row():
    """Pick a real dataset row, price it through the model."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from houseprice.data_load import load_dataset
    from houseprice.predict import load_bundle, predict_one
    df = load_dataset()
    row = df[df["category"] == "Plumbing"].iloc[0].to_dict()
    pred = predict_one(load_bundle(), row)
    return pred, row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="zero-write auth/connectivity check (default)")
    ap.add_argument("--post", action="store_true", help="create ONE tagged staging booking")
    args = ap.parse_args()
    if args.post:
        pred, row = _priced_row()
        booking = build_booking(pred, row)
        print("[post] booking:", json.dumps(booking)[:200], "...")
        post_one(booking)
    else:
        ok = probe()
        print("[probe]", "healthy" if ok else "UNHEALTHY")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

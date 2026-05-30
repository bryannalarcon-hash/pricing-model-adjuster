"""CLI: price a single booking from stdin JSON (demo / smoke test).

  echo '{"service_category":"Plumbing","job_description":"...","original_estimate":1850,
         "original_estimate_lo":1400,"original_estimate_hi":2300}' | python -m houseprice.predict_cli
"""
import json
import sys

from .predict import load_bundle, predict_one


def main():
    booking = json.load(sys.stdin)
    out = predict_one(load_bundle(), booking)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

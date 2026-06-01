#!/usr/bin/env bash
# scripts/up.sh — one-command local bring-up of the HouseAccount pricing stack.
# Starts the Python inference sidecar (:8011) and the Rails API + dashboard (:3007),
# installs any missing deps, waits for the sidecar to be healthy, then runs Rails in
# the foreground. Ctrl-C tears BOTH down. BOOKING_LIVE is force-unset so bookings stay
# SIMULATED and nothing is posted to real staging.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cat <<'BANNER'
────────────────────────────────────────────────────────────────────────
  Bringing up the HouseAccount pricing stack — LOCAL (this machine only).

  This will:
    • install Python deps + Rails gems if they are missing
    • create .env from .env.example if you don't have one
    • start the Python model sidecar  →  http://127.0.0.1:8011
    • start the Rails API + dashboard  →  http://127.0.0.1:3007
    • open the dashboard at            →  http://127.0.0.1:3007/

  SAFETY: BOOKING_LIVE is force-unset → bookings are SIMULATED; nothing is
  posted to the real staging endpoint. Press Ctrl-C to stop BOTH services.
────────────────────────────────────────────────────────────────────────
BANNER
sleep 2

# --- Python sidecar deps (install only if missing) ---
if ! python3 -c "import lightgbm, fastapi, pandas" >/dev/null 2>&1; then
  echo "→ installing Python deps (requirements.txt)…"
  pip install -q -r requirements.txt
fi

# --- Ruby/bundler: fall back to the ~/.gem convention if bundle isn't already on PATH ---
command -v bundle >/dev/null 2>&1 || { export GEM_HOME="${GEM_HOME:-$HOME/.gem}"; export PATH="$GEM_HOME/bin:$PATH"; }
if ! command -v bundle >/dev/null 2>&1; then
  echo "✗ 'bundle' not found — install Ruby 3.0.2 + bundler (see README Quickstart)." >&2
  exit 1
fi
( cd api && { bundle check >/dev/null 2>&1 || bundle install --quiet; } )

# --- env, demo secret, and the live-booking safety latch ---
[ -f .env ] || { cp .env.example .env; echo "→ created .env from .env.example (edit it to set real secrets)"; }
export GAUNTLET_PRICING_SECRET="${GAUNTLET_PRICING_SECRET:-demo-secret}"
unset BOOKING_LIVE   # never post to real staging from a local bring-up

# --- start the sidecar in the background and wait for /health ---
echo "→ starting model sidecar on :8011 …"
PYTHONPATH=src SCOPE_BACKEND=deterministic python3 -m uvicorn houseprice.infer_service:app \
  --host 127.0.0.1 --port 8011 >/tmp/houseprice-sidecar.log 2>&1 &
SIDECAR_PID=$!
trap 'echo; echo "→ stopping stack…"; kill "$SIDECAR_PID" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 40); do
  curl -sf http://127.0.0.1:8011/health >/dev/null 2>&1 && break
  kill -0 "$SIDECAR_PID" 2>/dev/null || { echo "✗ sidecar failed — see /tmp/houseprice-sidecar.log" >&2; exit 1; }
  sleep 0.5
done
echo "✓ sidecar healthy on :8011"

# --- start Rails in the foreground (Ctrl-C fires the trap above and stops the sidecar) ---
echo "→ starting Rails API + dashboard on :3007  →  open http://127.0.0.1:3007/"
cd api
RAILS_SERVE_STATIC_FILES=1 bundle exec rails server -p 3007 -b 127.0.0.1

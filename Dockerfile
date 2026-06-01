# Python FastAPI inference sidecar (Railway "sidecar" service). Built from the repo ROOT.
# Loads model/bundle.pkl and serves POST /infer + GET /health for the Rails app to proxy.
# python:3.10-slim + pinned requirements match the env that created the bundle (pickle-safe).
FROM python:3.10-slim

WORKDIR /app

# libgomp1 is required by LightGBM (OpenMP runtime).
RUN apt-get update -qq \
 && apt-get install --no-install-recommends -y libgomp1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only the inference code + the trained model are needed at runtime (no dataset).
COPY src/ ./src/
COPY model/ ./model/

ENV PYTHONPATH=/app/src \
    SCOPE_BACKEND=deterministic \
    PYTHONUNBUFFERED=1

# Railway private networking is IPv6 — bind :: so the Rails service can reach us at
# sidecar.railway.internal. $PORT is injected by Railway (we pin it to 8011 via a service var).
CMD ["sh", "-c", "uvicorn houseprice.infer_service:app --host :: --port ${PORT:-8011}"]

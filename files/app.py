"""
Minimal API around tile_fetcher.py so the SolarScan website's
"Run a scan" button has something to call.

Endpoints
---------
GET /api/geocode?q=<text>
    Address/place search via Nominatim (OpenStreetMap) -- completely
    separate from the Sentinel Hub / CDSE credentials, which are only
    used for imagery. Free, keyless, but rate-limited (see notes below).
    -> {"status": "ok", "query": "...", "results": [{"label", "lat", "lon", "type"}, ...]}

POST /api/scan
    body: {"lat": 28.5921, "lon": 77.3736}
    -> {
         "status": "ok",
         "tile_url": "/api/tiles/<file>.png",
         "effective_mpp": 0.29,
         "lat": 28.5921,
         "lon": 77.3736
       }

GET /api/tiles/<filename>
    Serves the generated PNG so the frontend <img> can point at it.

GET /api/health
    Basic liveness check, useful once this is actually deployed.

Notes / what this does NOT do
------------------------------
- It does not run roof segmentation, shading, or financial modelling —
  those don't exist yet. This endpoint only fetches and returns the
  aerial tile via get_hires_tile(). The "usable area / kWh / payback"
  numbers on the site are still the illustrative mockup values until
  that modelling step is built.
- It calls get_hires_tile() (Esri World Imagery), not
  get_satellite_tile() (Sentinel-2) — the former is what's actually
  useful for roof-level detail, per the docstring in tile_fetcher.py.
- CDSE credentials are irrelevant to this path (only get_satellite_tile
  needs them), but get_hires_tile still makes outbound requests to
  Esri's tile servers, so this process needs real network access to
  services.arcgisonline.com when deployed.
- /api/geocode proxies Nominatim, which requires a real, identifying
  User-Agent (set below -- put your own contact info in it) and caps
  usage at roughly 1 request/second. Fine for a hackathon demo; do not
  point production traffic at the public Nominatim instance.
"""

from __future__ import annotations

import os
import uuid
import logging
import threading

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from tile_fetcher import get_hires_tile

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("solarscan-api")

app = Flask(__name__)

# Wide-open CORS for hackathon/demo purposes. Lock this down to your
# actual site origin (CORS(app, origins=["https://yoursite.com"])) before
# sharing the API URL publicly.
CORS(app)

TILE_DIR = os.path.join(os.path.dirname(__file__), "tiles")
os.makedirs(TILE_DIR, exist_ok=True)

# Only one scan runs at a time -- get_hires_tile() does synchronous,
# blocking network calls to Esri tile servers. This lock just stops two
# overlapping requests from writing to the same output file; it does
# NOT make the API fast. A real deployment would use a job queue.
_scan_lock = threading.Lock()

# --------------------------------------------------------------- geocoding
#
# Nominatim (OpenStreetMap) is used for address -> coordinates search.
# This has NOTHING to do with the Sentinel Hub / CDSE credentials used
# for imagery -- it's a separate, free, keyless service with its own
# usage policy (https://operations.osmfoundation.org/policies/nominatim/):
#   * max ~1 request/second
#   * a real, identifying User-Agent is REQUIRED or requests get blocked
#   * no heavy/bulk use -- this is fine for a hackathon demo, not for
#     production-scale traffic. For that, self-host Nominatim or use a
#     paid provider (Mapbox, Google, LocationIQ, etc).
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "SolarScan-SIH2026-Demo/1.0 (contact: replace-with-your-email@example.com)"


@app.get("/api/geocode")
def geocode():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({
            "status": "error",
            "message": "Query parameter 'q' is required, e.g. /api/geocode?q=JSS+Noida"
        }), 400

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 5,
            },
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.exception("Geocoding failed for query=%r", query)
        return jsonify({
            "status": "error",
            "message": f"Geocoding request failed: {exc}"
        }), 502

    matches = [
        {
            "label": r.get("display_name"),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "type": r.get("type"),
        }
        for r in results
        if "lat" in r and "lon" in r
    ]

    return jsonify({"status": "ok", "query": query, "results": matches})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/scan")
def scan():
    body = request.get_json(silent=True) or {}

    lat = body.get("lat")
    lon = body.get("lon")
    size_m = body.get("size_m", 300)   # smaller default than the script's
                                        # 640 -- keeps demo requests fast
    zoom = body.get("zoom", 19)

    if lat is None or lon is None:
        return jsonify({
            "status": "error",
            "message": "Both 'lat' and 'lon' are required. If you only "
                       "have an address, geocode it client-side (or add a "
                       "geocoding step server-side) before calling /api/scan."
        }), 400

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return jsonify({
            "status": "error",
            "message": "'lat' and 'lon' must be numbers."
        }), 400

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({
            "status": "error",
            "message": "'lat' must be in [-90, 90] and 'lon' in [-180, 180]."
        }), 400

    filename = f"{uuid.uuid4().hex}.png"
    out_path = os.path.join(TILE_DIR, filename)

    try:
        with _scan_lock:
            _, effective_mpp = get_hires_tile(
                lat, lon, size_m=size_m, zoom=zoom, out=out_path
            )
    except Exception as exc:  # noqa: BLE001
        log.exception("Tile fetch failed for lat=%s lon=%s", lat, lon)
        return jsonify({
            "status": "error",
            "message": f"Tile fetch failed: {exc}"
        }), 502

    return jsonify({
        "status": "ok",
        "tile_url": f"/api/tiles/{filename}",
        "effective_mpp": round(effective_mpp, 3),
        "lat": lat,
        "lon": lon,
    })


@app.get("/api/tiles/<path:filename>")
def serve_tile(filename):
    return send_from_directory(TILE_DIR, filename)


if __name__ == "__main__":
    # Dev server only. For a real deployment use gunicorn/uwsgi behind a
    # proper WSGI setup, e.g.:
    #   gunicorn -w 2 -b 0.0.0.0:8000 app:app
    app.run(host="0.0.0.0", port=8000, debug=True)

"""
SolarScan — Flask backend.

Endpoints:
  GET  /            → serves the showcase page
  POST /api/scan    → fetches aerial tile + runs solar feasibility calc
"""

from __future__ import annotations

import io
import math
import os
import sys
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_from_directory

# ── make code1.py importable from the parent directory ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from code1 import get_hires_tile  # noqa: E402

app = Flask(__name__)

SCAN_DIR = os.path.join(app.static_folder, "scans")
os.makedirs(SCAN_DIR, exist_ok=True)


# ═══════════════════════════════════════════════ pages

@app.route("/")
def index():
    return render_template("index.html", year=datetime.now().year)


# ═══════════════════════════════════════════════ API

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Fetch a high-res aerial tile and return solar feasibility numbers.

    Expects JSON body:
      { "lat": float, "lon": float, "zoom": int (optional), "size_m": int (optional) }

    Returns JSON:
      { image_url, lat, lon, zoom, mpp, width, height,
        roof_area_m2, panel_count, system_kw, annual_kwh,
        gross_cost, subsidy, net_cost, payback_years, annual_revenue }
    """
    data = request.get_json(force=True)
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return jsonify({"error": "lat and lon are required"}), 400

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon must be numbers"}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return jsonify({"error": "lat must be -90..90, lon must be -180..180"}), 400

    zoom = int(data.get("zoom", 19))
    size_m = int(data.get("size_m", 640))

    # ── fetch the tile ──
    tile_id = uuid.uuid4().hex[:12]
    out_path = os.path.join(SCAN_DIR, f"{tile_id}.png")

    try:
        _, mpp = get_hires_tile(lat, lon, size_m=size_m, zoom=zoom, out=out_path)
    except Exception as exc:
        return jsonify({"error": f"Tile fetch failed: {exc}"}), 502

    # ── image dimensions ──
    from PIL import Image
    img = Image.open(out_path)
    w, h = img.size

    # ── lightweight solar feasibility estimate ──
    calc = _solar_calc(lat, size_m, mpp)

    return jsonify({
        "image_url": f"/static/scans/{tile_id}.png",
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "mpp": round(mpp, 3),
        "width": w,
        "height": h,
        **calc,
    })


# ═══════════════════════════════════════════════ solar calc

# India-specific constants (PM Surya Ghar scheme, 2024-26 rates)
PANEL_WATT = 540           # typical panel rating
PANEL_AREA_M2 = 2.58       # ~2.28 m × 1.13 m including spacing
SYSTEM_COST_PER_KW = 50000 # ₹/kW gross (before subsidy), average 2025
ELECTRICITY_RATE = 7.5     # ₹/kWh average domestic tariff
DEGRADATION_RATE = 0.005   # 0.5% annual degradation

# PM Surya Ghar subsidy slabs (Central Financial Assistance)
# Up to 2 kW  → ₹30,000/kW
# 2–3 kW      → ₹18,000/kW (for the incremental kW)
# 3–10 kW     → ₹9,000/kW  (for the incremental kW)
# > 10 kW     → ₹0


def _pm_surya_ghar_subsidy(system_kw: float) -> float:
    """Calculate PM Surya Ghar central subsidy for a given system size."""
    if system_kw <= 0:
        return 0
    subsidy = 0.0
    # Slab 1: up to 2 kW
    s1 = min(system_kw, 2)
    subsidy += s1 * 30_000
    # Slab 2: 2–3 kW
    s2 = max(0, min(system_kw, 3) - 2)
    subsidy += s2 * 18_000
    # Slab 3: 3–10 kW
    s3 = max(0, min(system_kw, 10) - 3)
    subsidy += s3 * 9_000
    return subsidy


def _solar_calc(lat: float, size_m: float, mpp: float) -> dict:
    """Estimate solar feasibility from tile metadata.

    We assume ~65% of the tile area is usable roof (conservative for a
    single-building scan in a dense Indian neighbourhood). This is a
    heuristic — the real segmentation model replaces this.
    """
    tile_area = size_m * size_m
    roof_fraction = 0.35          # usable roof as fraction of tile area
    roof_area = tile_area * roof_fraction

    # average peak sun hours/day varies by latitude (India range: 4.5–6.5)
    peak_sun = 5.5 - abs(lat - 23) * 0.04   # rough India approximation
    peak_sun = max(4.0, min(6.5, peak_sun))

    panel_count = int(roof_area / PANEL_AREA_M2)
    system_kw = round(panel_count * PANEL_WATT / 1000, 2)

    # cap at a reasonable residential size
    if system_kw > 10:
        system_kw = 10.0
        panel_count = int(system_kw * 1000 / PANEL_WATT)
        roof_area = panel_count * PANEL_AREA_M2

    annual_kwh = round(system_kw * peak_sun * 365 * 0.80)  # 80% performance ratio
    shading_loss = 0.12  # assume 12% average shading
    annual_kwh = round(annual_kwh * (1 - shading_loss))

    gross_cost = round(system_kw * SYSTEM_COST_PER_KW)
    subsidy = round(_pm_surya_ghar_subsidy(system_kw))
    net_cost = gross_cost - subsidy

    annual_revenue = round(annual_kwh * ELECTRICITY_RATE)
    payback = round(net_cost / annual_revenue, 1) if annual_revenue > 0 else 99

    return {
        "roof_area_m2": round(roof_area, 1),
        "panel_count": panel_count,
        "system_kw": system_kw,
        "peak_sun_hours": round(peak_sun, 1),
        "shading_loss_pct": round(shading_loss * 100),
        "annual_kwh": annual_kwh,
        "gross_cost": gross_cost,
        "subsidy": subsidy,
        "net_cost": net_cost,
        "payback_years": payback,
        "annual_revenue": annual_revenue,
    }


# ═══════════════════════════════════════════════ run

if __name__ == "__main__":
    print("\n  ☼  SolarScan running at http://localhost:5000\n")
    app.run(debug=True, host="0.0.0.0", port=5000)

"""
SolarScan — Flask backend.

Endpoints:
  GET  /            → serves the showcase page
  GET  /api/geocode → geocode an address to lat/lon (proxies Nominatim)
  POST /api/scan    → fetches aerial tile + runs solar feasibility calc
"""

from __future__ import annotations

import io
import math
import os
import sys
import uuid
from datetime import datetime

import base64

# Add the current directory to sys.path so imports work on Vercel
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify
from tile_fetcher import get_hires_tile

# Explicitly set paths so Vercel finds templates/static when running from root
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates"),
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))


# ═══════════════════════════════════════════════ pages

@app.route("/")
def index():
    return render_template("index.html", year=datetime.now().year)

@app.route("/robots.txt")
def robots():
    return "User-agent: *\nAllow: /\nSitemap: /sitemap.xml", 200, {'Content-Type': 'text/plain'}

@app.route("/sitemap.xml")
def sitemap():
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://solarscan.com/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>'''
    return xml, 200, {'Content-Type': 'application/xml'}

# ═══════════════════════════════════════════════ API

@app.route("/api/geocode")
def api_geocode():
    """Geocode an address using OpenStreetMap Nominatim.

    Query params:
      q  — search string (e.g. "Taj Mahal, India" or "1600 Pennsylvania Ave")

    Returns JSON array of results:
      [{ display_name, lat, lon, boundingbox, type }]
    """
    import requests as req

    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return jsonify([])

    try:
        resp = req.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q,
                "format": "json",
                "addressdetails": 1,
                "limit": 6,
            },
            headers={"User-Agent": "SolarScan/1.0 (hackathon project)"},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as exc:
        return jsonify({"error": f"Geocoding failed: {exc}"}), 502

    out = []
    for r in results:
        out.append({
            "display_name": r.get("display_name", ""),
            "lat": float(r.get("lat", 0)),
            "lon": float(r.get("lon", 0)),
            "boundingbox": r.get("boundingbox", []),
            "type": r.get("type", ""),
        })

    return jsonify(out)

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
    out_path = f"/tmp/{tile_id}.png"

    try:
        _, mpp = get_hires_tile(lat, lon, size_m=size_m, zoom=zoom, out=out_path)
    except Exception as exc:
        return jsonify({"error": f"Tile fetch failed: {exc}"}), 502

    # ── image dimensions and base64 encoding ──
    from PIL import Image
    img = Image.open(out_path)
    w, h = img.size
    
    with open(out_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    try:
        os.remove(out_path)
    except Exception:
        pass

    # ── lightweight solar feasibility estimate ──
    calc = _solar_calc(lat, size_m, mpp)

    return jsonify({
        "image_url": f"data:image/png;base64,{img_b64}",
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "mpp": round(mpp, 3),
        "width": w,
        "height": h,
        **calc,
    })


@app.route("/api/detect-roof", methods=["POST"])
def api_detect_roof():
    """Auto-detect building/roof outline from a satellite tile image.

    Expects JSON body:
      { "image_b64": str (base64 PNG data-url or raw),
        "mpp": float (meters per pixel) }

    Returns JSON:
      { "polygon": [[x,y], ...],
        "area_m2": float,
        "contour_count": int }
    """
    import cv2
    import numpy as np

    data = request.get_json(force=True)
    img_b64 = data.get("image_b64", "")
    mpp = float(data.get("mpp", 0.3))

    # Strip data-url prefix if present
    if "," in img_b64:
        img_b64 = img_b64.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(img_b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as exc:
        return jsonify({"error": f"Failed to decode image: {exc}"}), 400

    if img is None:
        return jsonify({"error": "Could not decode image"}), 400

    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2

    # ── preprocessing ──
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # CLAHE for contrast enhancement (helps with varied lighting)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Bilateral filter to reduce noise while keeping edges
    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    # ── edge detection ──
    # Adaptive threshold to handle varying brightness across the tile
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 21, 4
    )

    # Morphological close to connect nearby edges into solid regions
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

    # Fill small holes
    kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_DILATE, kernel_small, iterations=1)

    # Also try Canny for cleaner edges
    edges = cv2.Canny(gray, 30, 120)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Combine both approaches
    combined = cv2.bitwise_or(thresh, edges)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=2)

    mask_polygon = data.get("mask_polygon")
    if mask_polygon and len(mask_polygon) >= 3:
        try:
            mask = np.zeros(gray.shape, dtype=np.uint8)
            pts = np.array(mask_polygon, dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)
            combined = cv2.bitwise_and(combined, mask)
        except Exception:
            pass

    # ── contour detection ──
    contours, _ = cv2.findContours(
        combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return jsonify({
            "polygon": [],
            "area_m2": 0,
            "contour_count": 0,
            "message": "No building contours detected"
        })

    # ── select best contour ──
    # Score each contour by: size (bigger = better) + proximity to center
    min_area = (w * h) * 0.005   # at least 0.5% of image
    max_area = (w * h) * 0.85    # no more than 85% of image
    candidates = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        # Centroid distance from image center
        M = cv2.moments(cnt)
        if M["m00"] == 0:
            continue
        cnt_cx = int(M["m10"] / M["m00"])
        cnt_cy = int(M["m01"] / M["m00"])
        dist = math.sqrt((cnt_cx - cx) ** 2 + (cnt_cy - cy) ** 2)

        # Prefer large contours close to center
        # Normalize: distance penalty relative to image diagonal
        diag = math.sqrt(w ** 2 + h ** 2)
        score = area / (1 + (dist / diag) * 3)

        candidates.append((score, cnt))

    if not candidates:
        return jsonify({
            "polygon": [],
            "area_m2": 0,
            "contour_count": len(contours),
            "message": "No suitable building contour found near image center"
        })

    # Pick the best candidate
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_contour = candidates[0][1]

    # ── simplify polygon ──
    perimeter = cv2.arcLength(best_contour, True)
    # Epsilon controls simplification: smaller = more detail
    epsilon = 0.012 * perimeter
    approx = cv2.approxPolyDP(best_contour, epsilon, True)

    # Convert to list of [x, y] points
    polygon = approx.reshape(-1, 2).tolist()

    # Calculate area in m²
    pixel_area = cv2.contourArea(approx)
    area_m2 = pixel_area * (mpp ** 2)

    return jsonify({
        "polygon": polygon,
        "area_m2": round(area_m2, 1),
        "area_px": round(pixel_area, 1),
        "contour_count": len(candidates),
        "vertex_count": len(polygon),
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

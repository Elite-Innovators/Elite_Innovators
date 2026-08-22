"""
Tile fetcher — extracted from code1.py for standalone deployment.

Fetches high-resolution aerial imagery from multiple tile providers.
Automatically falls back to lower zoom levels when high-res tiles are
not available for a given area (common in rural/remote regions).

Providers (tried in order):
  1. Esri World Imagery  — best quality, ~0.3 m/px at zoom 19
  2. Google Maps Satellite — broad global coverage, good fallback
"""

from __future__ import annotations

import io
import math
import numpy as np
from PIL import Image
import requests


# ──────────────────────── tile providers ────────────────────────

TILE_PROVIDERS = [
    {
        "name": "Esri World Imagery",
        "url": (
            "https://services.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
    },
    {
        "name": "Google Satellite",
        "url": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    },
]


# ──────────────────────── placeholder detection ────────────────────────

def _is_placeholder_tile(tile_bytes: bytes) -> bool:
    """Detect 'no data available' placeholder tiles.

    Esri (and others) return a uniform grey/beige tile with text like
    'Map data not yet available' when imagery is missing at this zoom.
    These tiles have very low colour variance — real aerial imagery
    (roofs, roads, vegetation) always has high variance.
    """
    try:
        img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
        arr = np.array(img, dtype=np.float32)

        # Check colour variance across the whole tile
        # Placeholder tiles have stddev < 15 across all channels
        # Real imagery almost always has stddev > 25
        channel_std = arr.std(axis=(0, 1))  # std per channel
        avg_std = channel_std.mean()

        if avg_std < 18:
            return True

        # Also check if the tile is almost entirely one colour
        # (some placeholders are solid grey/white)
        unique_colors = len(set(img.getdata()))
        if unique_colors < 50:
            return True

        return False
    except Exception:
        return True  # if we can't read it, treat as placeholder


def _is_canvas_valid(canvas: Image.Image) -> bool:
    """Check if the stitched canvas has real imagery (not all placeholders)."""
    arr = np.array(canvas, dtype=np.float32)
    channel_std = arr.std(axis=(0, 1))
    avg_std = channel_std.mean()
    return avg_std > 18


# ──────────────────────── core fetcher ────────────────────────

def _fetch_tiles_at_zoom(
    lat: float,
    lon: float,
    size_m: int,
    zoom: int,
    provider: dict,
    sess: requests.Session,
) -> tuple[Image.Image, float] | None:
    """Fetch and stitch tiles at a specific zoom level from a given provider.

    Returns (cropped_image, meters_per_pixel) or None if the tiles are
    placeholders / no-data.
    """
    def deg2num(la, lo, z):
        n = 2.0 ** z
        return (
            (lo + 180.0) / 360.0 * n,
            (1.0 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2.0 * n,
        )

    mpp = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
    px_needed = size_m / mpp
    xf, yf = deg2num(lat, lon, zoom)
    half = px_needed / 2 / 256
    x0, x1 = math.floor(xf - half), math.floor(xf + half)
    y0, y1 = math.floor(yf - half), math.floor(yf + half)

    canvas = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    placeholder_count = 0
    total_tiles = 0

    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            total_tiles += 1
            try:
                r = sess.get(
                    provider["url"].format(z=zoom, x=x, y=y),
                    timeout=15,
                )
                r.raise_for_status()

                if _is_placeholder_tile(r.content):
                    placeholder_count += 1

                canvas.paste(
                    Image.open(io.BytesIO(r.content)).convert("RGB"),
                    ((x - x0) * 256, (y - y0) * 256),
                )
            except Exception:
                placeholder_count += 1

    # If more than 40% of tiles are placeholders, this zoom level is no good
    if total_tiles > 0 and (placeholder_count / total_tiles) > 0.4:
        return None

    # Double-check the stitched canvas for real imagery content
    if not _is_canvas_valid(canvas):
        return None

    cx, cy, h = (xf - x0) * 256, (yf - y0) * 256, px_needed / 2
    crop = canvas.crop(
        (round(cx - h), round(cy - h), round(cx + h), round(cy + h))
    )

    return crop, mpp


# ──────────────────────── public API ────────────────────────

def get_hires_tile(
    lat: float,
    lon: float,
    size_m: int = 640,
    zoom: int = 19,
    out: str = "roof_tile_hires.png",
):
    """Fetch high-res aerial imagery with automatic fallback.

    Tries the requested zoom level first. If the tiles are placeholders
    ('map data not yet available'), automatically steps down zoom levels
    until real imagery is found (minimum zoom 13 ≈ ~19 m/px).

    Falls back to alternative tile providers (Google Satellite) if
    the primary provider (Esri) has no coverage at any zoom.

    Returns (output_path, meters_per_pixel).
    """
    min_zoom = 13  # ~19 m/px, below this is too coarse for roof analysis
    sess = requests.Session()
    sess.headers["User-Agent"] = "SolarScan/1.0 (hackathon roof-tile-fetcher)"

    for provider in TILE_PROVIDERS:
        # Try from the requested zoom down to min_zoom
        for z in range(zoom, min_zoom - 1, -1):
            result = _fetch_tiles_at_zoom(lat, lon, size_m, z, provider, sess)
            if result is not None:
                crop, mpp = result
                crop.save(out, optimize=True)
                if z < zoom:
                    print(
                        f"[i] {provider['name']}: zoom {zoom} unavailable, "
                        f"fell back to zoom {z}"
                    )
                print(
                    f"[i] {crop.width}x{crop.height} px | "
                    f"{mpp:.2f} m/px (zoom {z}) | {provider['name']}"
                )
                return out, mpp

        print(f"[!] {provider['name']}: no imagery at any zoom for {lat},{lon}")

    # If absolutely nothing worked, raise
    raise RuntimeError(
        f"No aerial imagery available for ({lat}, {lon}) from any provider "
        f"at zoom levels {zoom}–{min_zoom}. This location may be in an "
        f"unmapped area (ocean, polar region, etc.)."
    )


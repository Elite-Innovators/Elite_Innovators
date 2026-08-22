"""
Tile fetcher — extracted from code1.py for standalone deployment.

Fetches ~0.3 m/px aerial imagery from Esri World Imagery (public XYZ tiles).
No API keys or authentication needed.
"""

from __future__ import annotations

import io
import math
from PIL import Image
import requests


def get_hires_tile(
    lat: float,
    lon: float,
    size_m: int = 640,
    zoom: int = 19,
    out: str = "roof_tile_hires.png",
):
    """~0.3 m/px aerial imagery from Esri World Imagery (XYZ tiles).

    This is what you want for roof outlines, obstructions and panel layout.
    Zoom 19 ~= 0.30 m/px at the equator, 20 ~= 0.15 m/px where available.
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
    sess = requests.Session()
    sess.headers["User-Agent"] = "roof-tile-fetcher/1.0"
    base = (
        "https://services.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    )

    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            r = sess.get(base.format(z=zoom, x=x, y=y), timeout=30)
            r.raise_for_status()
            canvas.paste(
                Image.open(io.BytesIO(r.content)).convert("RGB"),
                ((x - x0) * 256, (y - y0) * 256),
            )

    cx, cy, h = (xf - x0) * 256, (yf - y0) * 256, px_needed / 2
    crop = canvas.crop(
        (round(cx - h), round(cy - h), round(cx + h), round(cy + h))
    )
    crop.save(out, optimize=True)
    print(f"[i] {crop.width}x{crop.height} px | {mpp:.2f} m/px (zoom {zoom})")
    return out, mpp

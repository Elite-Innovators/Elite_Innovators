"""
High-quality satellite tile fetcher.

Two paths:
  1) get_satellite_tile()   -> Sentinel-2 L2A via CDSE Sentinel Hub, maximum
                               achievable quality (float32 reflectance, UTM grid,
                               server-side bicubic oversampling, percentile
                               tone-mapping, optional Lanczos upscale).
  2) get_hires_tile()       -> ~0.3 m/px aerial imagery (Esri World Imagery XYZ)
                               for anything that needs actual roof detail.

Reality check: Sentinel-2 RGB is 10 m/pixel at the sensor. You can render more
pixels, but you cannot create detail that was never sampled. A 6 m house is
sub-pixel. Use path (2) for roof segmentation / panel layout, and path (1) for
regional context, change detection, spectral indices, or cloud-free mosaics.

CHANGE LOG (fix for "Tile is entirely no-data."):
  * maxcc is a whole-PRODUCT cloud percentage from scene metadata, not
    "clouds over your tiny AOI". A scene can be rejected as 30% cloudy even
    though your 640 m bbox is perfectly clear, which silently starves the
    leastCC mosaic and returns an all-zero dataMask instead of raising.
  * get_satellite_tile() now retries with progressively looser filters
    (wider time window, higher maxcc) before giving up.
  * If every retry still comes back empty, it queries the Sentinel Hub
    Catalog API for that bbox/time range so you get a real diagnostic
    (e.g. "0 scenes found at all" -> auth/quota problem, vs "12 scenes
    found, all rejected by maxcc" -> loosen max_cloud).
"""

from __future__ import annotations

import io
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

from sentinelhub import (
    SHConfig, BBox, CRS, bbox_to_dimensions,
    SentinelHubRequest, SentinelHubCatalog, DataCollection, MimeType,
)

Image.MAX_IMAGE_PIXELS = None  # allow big renders

# ---------------------------------------------------------------- config

config = SHConfig()
config.sh_client_id = os.getenv("CDSE_CLIENT_ID", "")
config.sh_client_secret = os.getenv("CDSE_CLIENT_SECRET", "")
config.sh_base_url = "https://sh.dataspace.copernicus.eu"
config.sh_auth_base_url = "https://identity.dataspace.copernicus.eu"
config.sh_token_url = (
    "https://identity.dataspace.copernicus.eu"
    "/auth/realms/CDSE/protocol/openid-connect/token"
)

S2L2A = DataCollection.SENTINEL2_L2A.define_from(
    "s2l2a_cdse", service_url=config.sh_base_url
)

# ------------------------------------------------------------- evalscript
# Raw FLOAT32 reflectance + dataMask. No baked-in 2.5x gain: that hard-clips
# every bright roof / sand pixel in Dubai. Tone mapping happens in numpy where
# a proper percentile stretch is possible.

TRUE_COLOR_SCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02","B03","B04","dataMask"], units: "REFLECTANCE" }],
    output: { bands: 4, sampleType: "FLOAT32" },
    mosaicking: "ORBIT"
  };
}
function evaluatePixel(samples) {
  // With mosaicking:"ORBIT" we get every matching observation for this
  // pixel across the time window, pre-sorted by mosaicking_order (leastCC
  // puts the least-cloudy scene first). The default SIMPLE mosaicking
  // (no mosaicking field) instead clips a single chosen product to the
  // bbox -- if that one granule has a nodata seam/orbit-edge over your
  // AOI you get an all-empty tile with no fallback, which is what was
  // happening here. Looping and taking the first valid pixel per
  // location gives a genuine gap-filled least-cloud composite.
  for (var i = 0; i < samples.length; i++) {
    if (samples[i].dataMask === 1) {
      var s = samples[i];
      return [s.B04, s.B03, s.B02, 1];
    }
  }
  return [0, 0, 0, 0];
}
"""

MAX_DIM = 2500  # Sentinel Hub Process API hard limit per side


# ------------------------------------------------------------- tone mapping

def _tonemap(rgb: np.ndarray, mask: np.ndarray,
             low_pct: float = 1.0, high_pct: float = 99.0,
             gamma: float = 1 / 1.8) -> np.ndarray:
    """Per-scene percentile stretch + gamma -> uint8. Much better contrast and
    no highlight clipping compared with a fixed 2.5 * reflectance gain."""
    valid = mask > 0
    if not valid.any():
        raise RuntimeError("Tile is entirely no-data.")

    out = np.empty(rgb.shape, dtype=np.float32)
    for c in range(3):
        band = rgb[:, :, c]
        lo, hi = np.percentile(band[valid], [low_pct, high_pct])
        if hi <= lo:
            hi = lo + 1e-6
        out[:, :, c] = np.clip((band - lo) / (hi - lo), 0, 1)

    out = np.power(out, gamma)                 # perceptual lift on shadows
    out = (out * 255.0).round().astype(np.uint8)
    out[~valid] = 0
    return out


def _unsharp(img: Image.Image, radius: float = 1.2,
             percent: int = 120, threshold: int = 2) -> Image.Image:
    from PIL import ImageFilter
    return img.filter(
        ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold)
    )


# ------------------------------------------------------- catalog diagnostics

def _diagnose_empty_result(bbox_wgs: BBox, time_interval: tuple[str, str],
                            max_cloud: float) -> str:
    """Query the Catalog API to explain why the mosaic came back empty.
    Never raises on its own -- this is best-effort diagnostics only."""
    try:
        catalog = SentinelHubCatalog(config=config)
        search = list(catalog.search(
            S2L2A,
            bbox=bbox_wgs,
            time=time_interval,
            fields={"include": ["properties.eo:cloud_cover", "properties.datetime"],
                    "exclude": []},
        ))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never crash the caller
        return (f"Catalog lookup itself failed ({exc!r}). This usually means "
                f"CDSE_CLIENT_ID / CDSE_CLIENT_SECRET are missing or invalid, "
                f"or there's no network access to sh.dataspace.copernicus.eu.")

    if not search:
        return (f"0 Sentinel-2 scenes exist in the catalog for this bbox "
                f"between {time_interval[0]} and {time_interval[1]}. That's "
                f"unusual for a populated area -- double check the lat/lon "
                f"and that the CDSE collection is actually indexed there.")

    ccs = [s["properties"].get("eo:cloud_cover") for s in search]
    passing = [c for c in ccs if c is not None and c <= max_cloud * 100]
    return (f"{len(search)} scene(s) found, cloud cover range "
            f"{min(ccs):.0f}-{max(ccs):.0f}%. Only {len(passing)} pass your "
            f"max_cloud={max_cloud:.2f} filter (product-level, not AOI-level). "
            f"Raise max_cloud and/or days_back.")


# ------------------------------------------------------------- main fetch

def get_satellite_tile(
    lat: float,
    lon: float,
    size_m: int = 640,
    resolution: float = 2.5,       # render grid; 10 m native, 2.5 m = 4x oversample
    days_back: int = 90,
    max_cloud: float = 0.2,
    upscale: int = 1,              # extra Lanczos upscale on top (1 = off)
    sharpen: bool = True,
    out: str = "roof_tile.png",
    save_tiff: bool = True,
    auto_widen: bool = True,       # NEW: retry with looser filters on empty result
):
    """Fetch the least-cloudy true-color Sentinel-2 tile centred on lat/lon.

    Quality upgrades over the original:
      * UTM projection instead of WGS84 -> square, undistorted metric pixels.
      * FLOAT32 reflectance instead of pre-clipped 8-bit.
      * Server-side BICUBIC upsampling, so a 2.5 m grid is interpolated by
        Sentinel Hub from the native 10 m data (smooth, not blocky).
      * Percentile stretch + gamma instead of a fixed 2.5x multiplier.
      * Optional Lanczos upscale + unsharp mask.
      * Auto-clamps resolution so neither side exceeds the 2500 px API limit.
      * NEW: if the first attempt returns an all-empty mosaic (0% valid
        pixels -- typically caused by maxcc rejecting every scene at
        product level even though the AOI itself is clear), automatically
        retries with a wider time window and looser cloud threshold before
        giving up, and reports Catalog diagnostics if it still fails.
    """
    # --- geometry: build in WGS84, then reproject to the local UTM zone
    half_lat = (size_m / 2) / 111_320
    half_lon = (size_m / 2) / (111_320 * math.cos(math.radians(lat)))
    bbox_wgs = BBox(
        [lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat],
        crs=CRS.WGS84,
    )
    bbox = bbox_wgs.transform(CRS.get_utm_from_wgs84(lon, lat))
    print(f"[i] bbox WGS84: {bbox_wgs} | bbox UTM: {bbox} (CRS {bbox.crs})")

    # --- clamp resolution to the API pixel budget
    if math.ceil(size_m / resolution) > MAX_DIM:
        resolution = size_m / MAX_DIM
        print(f"[i] resolution clamped to {resolution:.3f} m/px ({MAX_DIM} px limit)")
    size = bbox_to_dimensions(bbox, resolution=resolution)

    # --- attempts: (days_back, max_cloud) escalation ladder
    attempts = [(days_back, max_cloud)]
    if auto_widen:
        attempts += [
            (max(days_back, 180), max(max_cloud, 0.5)),
            (max(days_back, 365), 1.0),   # 1.0 = no cloud filtering at all
        ]

    now = datetime.now(timezone.utc)
    arr = None
    last_time_interval = None
    last_max_cloud = max_cloud

    for i, (db, mc) in enumerate(attempts):
        time_interval = (
            (now - timedelta(days=db)).strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
        )
        last_time_interval, last_max_cloud = time_interval, mc

        input_data = SentinelHubRequest.input_data(
            data_collection=S2L2A,
            time_interval=time_interval,
            mosaicking_order="leastCC",
            maxcc=mc,
            other_args={"processing": {
                "upsampling": "BICUBIC",
                "downsampling": "BICUBIC",
            }},
        )

        request = SentinelHubRequest(
            evalscript=TRUE_COLOR_SCRIPT,
            input_data=[input_data],
            responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
            bbox=bbox,
            size=size,
            config=config,
        )

        data = request.get_data()
        if not data or data[0] is None:
            continue  # nothing at all this attempt, try looser filters

        candidate = np.asarray(data[0], dtype=np.float32)
        if candidate.ndim != 3 or candidate.shape[2] < 4:
            raise RuntimeError(f"Unexpected array shape {candidate.shape}")

        coverage = float((candidate[:, :, 3] > 0).mean())
        if coverage > 0:
            if i > 0:
                print(f"[i] attempt {i + 1} succeeded after widening "
                      f"(days_back={db}, max_cloud={mc}) -> {coverage:.0%} valid")
            arr = candidate
            break
        elif i < len(attempts) - 1:
            print(f"[!] attempt {i + 1} returned 0% valid pixels "
                  f"(days_back={db}, max_cloud={mc}) -- widening and retrying")

    if arr is None:
        diagnosis = _diagnose_empty_result(bbox_wgs, last_time_interval, last_max_cloud)
        raise RuntimeError(
            f"No valid imagery for {lat},{lon} even after widening filters "
            f"to days_back={attempts[-1][0]}, max_cloud={attempts[-1][1]}.\n"
            f"Diagnosis: {diagnosis}"
        )

    rgb, mask = arr[:, :, :3], arr[:, :, 3]
    coverage = float((mask > 0).mean())
    if coverage < 0.5:
        print(f"[!] only {coverage:.0%} valid pixels — consider widening further")

    img = Image.fromarray(_tonemap(rgb, mask), mode="RGB")

    if upscale > 1:
        img = img.resize((img.width * upscale, img.height * upscale), Image.LANCZOS)
    if sharpen:
        img = _unsharp(img)

    img.save(out, optimize=True)

    if save_tiff:
        tif = os.path.splitext(out)[0] + "_reflectance.tif"
        try:
            import tifffile
            tifffile.imwrite(tif, arr)          # full float32, all 4 bands
            print(f"[i] float32 reflectance saved -> {tif}")
        except ImportError:
            print("[i] pip install tifffile to also keep the float32 stack")

    effective_mpp = size_m / img.width
    print(f"[i] {img.width}x{img.height} px | render grid {resolution:.2f} m/px "
          f"| effective {effective_mpp:.2f} m/px | native sensor 10 m/px")
    return out, effective_mpp


# ------------------------------------------------- genuinely high-res option

def get_hires_tile(lat: float, lon: float, size_m: int = 640,
                   zoom: int = 19, out: str = "roof_tile_hires.png"):
    """~0.3 m/px aerial imagery from Esri World Imagery (XYZ tiles).

    This is what you want for roof outlines, obstructions and panel layout.
    Zoom 19 ~= 0.30 m/px at the equator, 20 ~= 0.15 m/px where available.
    Check the Esri World Imagery terms of use before shipping anything.
    """
    import requests

    def deg2num(la, lo, z):
        n = 2.0 ** z
        return ((lo + 180.0) / 360.0 * n,
                (1.0 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2.0 * n)

    mpp = 156543.03392 * math.cos(math.radians(lat)) / (2 ** zoom)
    px_needed = size_m / mpp
    xf, yf = deg2num(lat, lon, zoom)
    half = px_needed / 2 / 256
    x0, x1 = math.floor(xf - half), math.floor(xf + half)
    y0, y1 = math.floor(yf - half), math.floor(yf + half)

    canvas = Image.new("RGB", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    sess = requests.Session()
    sess.headers["User-Agent"] = "roof-tile-fetcher/1.0"
    base = ("https://services.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")

    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            r = sess.get(base.format(z=zoom, x=x, y=y), timeout=30)
            r.raise_for_status()
            canvas.paste(Image.open(io.BytesIO(r.content)).convert("RGB"),
                         ((x - x0) * 256, (y - y0) * 256))

    cx, cy, h = (xf - x0) * 256, (yf - y0) * 256, px_needed / 2
    crop = canvas.crop((round(cx - h), round(cy - h), round(cx + h), round(cy + h)))
    crop.save(out, optimize=True)
    print(f"[i] {crop.width}x{crop.height} px | {mpp:.2f} m/px (zoom {zoom})")
    return out, mpp


if __name__ == "__main__":
    # Sentinel-2: 10 m/px native — good for spectral analysis, not sharp visuals
    # get_satellite_tile(25.11607, 55.13506, size_m=640, resolution=2.5,
    #                    out="roof_tile.png", save_tiff=False)

    # Esri World Imagery: ~0.3 m/px at zoom 19, ~0.15 m/px at zoom 20
    # This is genuinely sharp — real aerial/satellite detail, not interpolation
    get_hires_tile(39.07357, 127.03822, size_m=640, zoom=19,
                   out="roof_tile.png")
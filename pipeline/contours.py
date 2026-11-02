#!/usr/bin/env python3
"""Contour lines every 10 m for one z9 cell, from the cell's dem.pmtiles (Mapterhorn terrarium).

Mosaics the z12 tiles of the cell, traces the contours with contourpy and writes a GeoJSON
(none for a cell with no lines) FeatureCollection of LineStrings with an integer "ele" property, for profiles/TrekProfile.java.

Usage: python3 pipeline/contours.py <cell_dir>   (e.g. work/cells/9-275-189)
"""
import io
import json
import math
import subprocess
import sys
from pathlib import Path

import contourpy
import numpy as np
from PIL import Image

DEM_ZOOM = 12
TILE_PX = 512
INTERVAL_M = 10
# Shorter lines are DEM noise (tiny closed loops on flat ground), not useful on a map.
MIN_VERTICES = 10


def tile_elevation(dem, x, y):
    """Elevation grid of one z12 tile, or None when the file has no such tile (open sea)."""
    webp = subprocess.run(["pmtiles", "tile", str(dem), str(DEM_ZOOM), str(x), str(y)],
                          check=True, capture_output=True).stdout
    if not webp:
        return None
    rgb = np.asarray(Image.open(io.BytesIO(webp)).convert("RGB"), dtype=np.float32)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def cell_grid(dem, x9, y9):
    """Mosaic of the z12 tiles of z9 cell (x9, y9); NaN where a tile is missing."""
    per_side = 2 ** (DEM_ZOOM - 9)

    def tile(x, y):
        grid = tile_elevation(dem, x, y)
        return np.full((TILE_PX, TILE_PX), np.nan, dtype=np.float32) if grid is None else grid

    return np.vstack([np.hstack([tile(x9 * per_side + i, y9 * per_side + j) for i in range(per_side)])
                      for j in range(per_side)])


def main(cell_dir):
    cell_dir = Path(cell_dir)
    _, x9, y9 = (int(v) for v in cell_dir.name.split("-"))
    per_side = 2 ** (DEM_ZOOM - 9)
    x0, y0 = x9 * per_side, y9 * per_side
    grid = cell_grid(cell_dir / "dem.pmtiles", x9, y9)

    world_px = 2 ** DEM_ZOOM * TILE_PX

    def to_lonlat(col, row):
        # Pixel centres, in global Web Mercator pixels.
        gx = x0 * TILE_PX + col + 0.5
        gy = y0 * TILE_PX + row + 0.5
        lon = gx / world_px * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy / world_px))))
        return [round(lon, 6), round(lat, 6)]

    # Missing tiles are masked: no lines there.
    generator = contourpy.contour_generator(z=np.ma.masked_invalid(grid))
    features = []
    low, high = (float(np.nanmin(grid)), float(np.nanmax(grid))) if np.isfinite(grid).any() else (0.0, -1.0)
    first = math.ceil(low / INTERVAL_M) * INTERVAL_M
    for ele in range(int(first), int(high) + 1, INTERVAL_M):
        for line in generator.lines(ele):
            if len(line) < MIN_VERTICES:
                continue
            features.append({
                "type": "Feature",
                "properties": {"ele": ele},
                "geometry": {"type": "LineString", "coordinates": [to_lonlat(c, r) for c, r in line]},
            })
    out = cell_dir / "contours.geojson"
    if not features:
        # Cell all at sea: no file, build_tiles.sh then builds trek without contours (Planetiler
        # 0.10.2 fails on a GeoJSON with no features).
        out.unlink(missing_ok=True)
        print(f"{cell_dir.name}: no contour lines")
        return
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    print(f"{cell_dir.name}: {len(features)} lines, {low:.0f}-{high:.0f} m, "
          f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

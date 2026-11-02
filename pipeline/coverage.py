#!/usr/bin/env python3
"""Cells of the Italian coverage and their release groups (M1-01).

A cell is a z9 tile that touches one of the 20 Italian regions. For each cell:
  italy_share  share of the cell inside Italy (0-1);
  region       Italian region holding the largest part of the cell;
  group        release group, the Geofabrik macro-area of that region;
  extracts     Geofabrik extracts the cell needs: italy plus every neighbouring extract whose
               polygon covers at least MIN_EXTRACT_SHARE of the cell outside italy.poly.
               Geofabrik polygons include sea, so a listed extract may hold no land in the
               cell (checked in M1-01: alps, slovenia, croatia and corse are the ones with
               foreign land in some cell).

Writes cells.csv and cells.geojson (cell squares with their properties, to check the groups on
a map, e.g. geojson.io).

Usage: python3 -I pipeline/coverage.py work/osm/regions work/osm/italy.poly \
           work/osm/neighbours coverage
Region polygons: openstreetmap.fr; italy.poly and neighbours/*.poly: Geofabrik.
"""
import csv
import json
import math
import sys
from pathlib import Path

from shapely.geometry import box, mapping
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent))  # -I leaves the script folder out
from cai_coverage import read_poly  # noqa: E402

ZOOM = 9
MIN_EXTRACT_SHARE = 0.01
GROUPS = {
    "nord-ovest": ["liguria", "lombardia", "piemonte", "valle_aosta"],
    "nord-est": ["emilia_romagna", "friuli_venezia_giulia", "trentino_alto_adige", "veneto"],
    "centro": ["lazio", "marche", "toscana", "umbria"],
    "sud": ["abruzzo", "basilicata", "calabria", "campania", "molise", "puglia"],
    "isole": ["sardegna", "sicilia"],
}
GROUP_OF = {region: group for group, regions in GROUPS.items() for region in regions}


def tile_x(lon: float) -> int:
    return int((lon + 180.0) / 360.0 * 2**ZOOM)


def tile_y(lat: float) -> int:
    r = math.radians(lat)
    return int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * 2**ZOOM)


def tile_bounds(x: int, y: int):
    """West, south, east, north in degrees."""
    n = 2**ZOOM

    def lat(yy):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))

    return x / n * 360.0 - 180.0, lat(y + 1), (x + 1) / n * 360.0 - 180.0, lat(y)


def main(regions_dir: str, italy_poly: str, neighbours_dir: str, out_dir: str) -> None:
    names = sorted(p.stem for p in Path(regions_dir).glob("*.poly"))
    regions = {n: read_poly(Path(regions_dir) / f"{n}.poly") for n in names}
    missing = set(names) ^ set(GROUP_OF)
    if missing:
        sys.exit(f"regions without a group or group regions without a polygon: {sorted(missing)}")
    italy = unary_union(list(regions.values()))
    italy_extract = read_poly(Path(italy_poly))
    neighbours = {
        p.stem: read_poly(p).difference(italy_extract) for p in sorted(Path(neighbours_dir).glob("*.poly"))
    }

    west, south, east, north = italy.bounds
    rows, features = [], []
    for x in range(tile_x(west), tile_x(east) + 1):
        for y in range(tile_y(north), tile_y(south) + 1):
            cell = box(*tile_bounds(x, y))
            inside = cell.intersection(italy)
            if inside.is_empty:
                continue
            # Shares in degree areas: good enough inside one cell (~0.7° x 0.5°).
            share = {n: cell.intersection(p).area for n, p in regions.items()}
            region = max(share, key=share.get)
            extracts = ["italy"] + [
                n for n, p in neighbours.items() if cell.intersection(p).area >= MIN_EXTRACT_SHARE * cell.area
            ]
            row = {
                "cell": f"{ZOOM}-{x}-{y}",
                "x": x,
                "y": y,
                "italy_share": round(inside.area / cell.area, 3),
                "region": region,
                "group": GROUP_OF[region],
                "extracts": " ".join(extracts),
            }
            rows.append(row)
            features.append({"type": "Feature", "properties": row, "geometry": mapping(cell)})

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "cells.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with open(out / "cells.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    print(f"{len(rows)} cells", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:5])

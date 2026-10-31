#!/usr/bin/env python3
"""Pick reference routes for routing quality tests from CAI-signed OSM hiking relations.

For each area, query route=hiking relations with cai_scale T/E/EE, keep the ones whose
members form one continuous line of 4-18 km, pick two with different difficulty and
write them as GPX plus a routes.csv index.
Usage: python3 -I pipeline/reference_routes.py reference/
Data © OpenStreetMap contributors, ODbL.
"""
import csv
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "trekbuddy-data/0.1 (reference routes; github.com/salvmontagna/trekbuddy-data)"

# (name, group, bbox south, west, north, east)
AREAS = [
    ("Dolomiti Gardena-Badia", "Alpi", 46.45, 11.60, 46.70, 12.00),
    ("Dolomiti di Brenta", "Alpi", 46.05, 10.75, 46.30, 11.00),
    ("Gran Paradiso - Cogne", "Alpi", 45.50, 7.20, 45.75, 7.50),
    ("Grigne - Lecco", "Alpi", 45.80, 9.30, 46.00, 9.50),
    ("Alpi Carniche e Giulie", "Alpi", 46.35, 12.80, 46.55, 13.40),
    ("Appennino tosco-emiliano", "Appennino", 44.05, 10.50, 44.25, 10.85),
    ("Monti Sibillini", "Appennino", 42.75, 13.15, 43.00, 13.35),
    ("Gran Sasso", "Appennino", 42.38, 13.45, 42.52, 13.70),
    ("Majella", "Appennino", 42.00, 14.00, 42.20, 14.20),
    ("Pollino", "Appennino", 39.85, 16.10, 40.00, 16.30),
]
MIN_KM, MAX_KM = 4.0, 18.0
# Larger gaps between consecutive ways mean a broken or branching relation.
MAX_GAP_M = 30.0
# E/EE first: they exercise trail routing more than T (mostly tracks and roads).
PREFERENCE = ["E", "EE", "T"]


def overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.load(resp)
        except Exception as exc:  # the public instance often answers 429/504 under load
            print(f"  overpass error ({exc}), retrying...", file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("Overpass unreachable")


def haversine(a, b) -> float:
    r = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def stitch(members) -> list | None:
    """Join the relation ways into one line; None if there are gaps or branches."""
    ways = [
        [(p["lat"], p["lon"]) for p in m["geometry"]]
        for m in members
        if m["type"] == "way" and m.get("role", "") in ("", "main", "forward", "backward") and m.get("geometry")
    ]
    if not ways:
        return None
    line = list(ways[0])
    if len(ways) > 1:
        # The first way has no predecessor: orient it so its end touches the second way.
        nxt = ways[1]
        if min(haversine(line[0], nxt[0]), haversine(line[0], nxt[-1])) < min(
            haversine(line[-1], nxt[0]), haversine(line[-1], nxt[-1])
        ):
            line.reverse()
    for way in ways[1:]:
        d_start, d_end = haversine(line[-1], way[0]), haversine(line[-1], way[-1])
        if min(d_start, d_end) > MAX_GAP_M:
            return None
        line.extend(way if d_start <= d_end else list(reversed(way)))
    return line


def length_km(line) -> float:
    return sum(haversine(a, b) for a, b in zip(line, line[1:])) / 1000.0


def write_gpx(path: Path, rel: dict, line) -> None:
    tags = rel["tags"]
    name = tags.get("name", f"Sentiero {tags.get('ref', rel['id'])}")
    pts = "\n".join(f'      <trkpt lat="{la:.7f}" lon="{lo:.7f}"/>' for la, lo in line)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="trekbuddy-data reference_routes.py" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>{esc(name)}</name>
    <copyright author="OpenStreetMap contributors"><license>https://opendatacommons.org/licenses/odbl/1-0/</license></copyright>
    <link href="https://www.openstreetmap.org/relation/{rel['id']}"><text>OSM relation {rel['id']} v{rel.get('version', '?')}</text></link>
  </metadata>
  <trk>
    <name>{esc(name)}</name>
    <type>{esc(tags.get('cai_scale', ''))}</type>
    <trkseg>
{pts}
    </trkseg>
  </trk>
</gpx>
""",
        encoding="utf-8",
    )


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for area, group, s, w, n, e in AREAS:
        print(f"{area}...", file=sys.stderr)
        res = overpass(
            f'[out:json][timeout:170];rel["route"="hiking"]["cai_scale"~"^(T|E|EE)$"]({s},{w},{n},{e});out meta geom;'
        )
        # Sorted by id so reruns pick the same relations while OSM data is unchanged.
        candidates = {}
        for rel in sorted(res["elements"], key=lambda r: r["id"]):
            scale = rel["tags"]["cai_scale"]
            if scale in candidates:
                continue
            line = stitch(rel.get("members", []))
            if line is None:
                continue
            km = length_km(line)
            if MIN_KM <= km <= MAX_KM:
                candidates[scale] = (rel, line, km)
        chosen = [candidates[c] for c in PREFERENCE if c in candidates][:2]
        if len(chosen) < 2:
            print(f"  warning: only {len(chosen)} valid routes in {area}", file=sys.stderr)
        for rel, line, km in chosen:
            tags = rel["tags"]
            fname = f"{rel['id']}.gpx"
            write_gpx(out / fname, rel, line)
            rows.append({
                "osm_relation": rel["id"],
                "version": rel.get("version", ""),
                "group": group,
                "area": area,
                "ref": tags.get("ref", ""),
                "name": tags.get("name", ""),
                "cai_scale": tags["cai_scale"],
                "length_km": f"{km:.2f}",
                "points": len(line),
                "file": fname,
            })
        time.sleep(5)  # Overpass usage policy: keep the load on the public instance low
    with open(out / "routes.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} routes saved to {out}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reference")

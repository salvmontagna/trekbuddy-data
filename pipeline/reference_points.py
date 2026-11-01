"""Reference itineraries and the points a router is asked to pass through (shared by the
*_routes.py scripts)."""
import csv
import math
import re
from pathlib import Path

REFERENCE = Path("reference")


def itineraries():
    """Rows of reference/routes.csv, each with its GPX points as 'points' [(lat, lon)]."""
    with open(REFERENCE / "routes.csv", newline="") as f:
        for row in csv.DictReader(f):
            gpx = (REFERENCE / row["file"]).read_text()
            row["points"] = [(float(a), float(b)) for a, b in
                             re.findall(r'<trkpt lat="([-\d.]+)" lon="([-\d.]+)"', gpx)]
            yield row


def distance_m(a, b):
    """Haversine distance in metres."""
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * 6371008.8 * math.asin(math.sqrt(h))


def waypoints(points, via_km=None):
    """Start and end of the reference, plus one point every via_km along it when given.

    With intermediate points the router is asked the same question a user asks in the planner
    (start, a few points along the trail, end) instead of the shortest way between the ends."""
    if not via_km:
        return [points[0], points[-1]]
    out, walked, next_at = [points[0]], 0.0, via_km * 1000
    for a, b in zip(points, points[1:]):
        walked += distance_m(a, b)
        if walked >= next_at:
            out.append(b)
            next_at += via_km * 1000
    # Drop an intermediate point too close to the end, it adds nothing but a possible detour.
    if len(out) > 1 and distance_m(out[-1], points[-1]) < via_km * 500:
        out.pop()
    return out + [points[-1]]


def write_gpx(path, creator, name, points):
    trkpts = "\n".join(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>' for lat, lon in points)
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="trekbuddy-data {creator}" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <copyright author="OpenStreetMap contributors"><license>https://opendatacommons.org/licenses/odbl/1-0/</license></copyright>
  </metadata>
  <trk>
    <name>{name}</name>
    <trkseg>
{trkpts}
    </trkseg>
  </trk>
</gpx>
""")

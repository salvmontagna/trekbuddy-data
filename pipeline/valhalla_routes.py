#!/usr/bin/env python3
"""Route every reference itinerary with Valhalla.

Writes one GPX per route, named <osm_relation>.gpx, for the comparison harness in
Trekbuddy's geo_core (compare_routes). Uses the whole build (work/valhalla/tiles), not the cells.
max_hiking_difficulty follows the route's CAI grade; other pedestrian costing options come from
--costing (JSON object) or keep Valhalla's defaults.

Usage: python3 pipeline/valhalla_routes.py <out_dir> [--via-km 2] [--costing options.json]
"""
import argparse
import json
from pathlib import Path

from valhalla import Actor

from reference_points import itineraries, waypoints, write_gpx

# Lowest max_hiking_difficulty (sac_scale 0-6) that allows the route's CAI grade, same
# mapping as pipeline/preprocess_osm.py.
CAI_LEVEL = {"T": 1, "E": 2, "EE": 3, "EEA": 5}


def decode_polyline6(encoded):
    """Valhalla shape (Google polyline, precision 6) -> [(lat, lon)]."""
    coords, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        for axis in (0, 1):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / 1e6, lon / 1e6))
    return coords


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir")
    parser.add_argument("--via-km", type=float, help="intermediate point every N km of the reference")
    parser.add_argument("--costing", help="JSON file with pedestrian costing options")
    args = parser.parse_args()

    costing = json.loads(Path(args.costing).read_text()) if args.costing else {}
    actor = Actor(json.loads(Path("work/valhalla/valhalla.json").read_text()))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for row in itineraries():
        stops = waypoints(row["points"], args.via_km)
        # "through" keeps the route going past an intermediate point instead of turning back on it.
        locations = [{"lat": lat, "lon": lon, "type": "through"} for lat, lon in stops]
        locations[0]["type"] = locations[-1]["type"] = "break"
        request = {
            "locations": locations,
            "costing": "pedestrian",
            "costing_options": {"pedestrian": {"max_hiking_difficulty": CAI_LEVEL[row["cai_scale"]], **costing}},
        }
        target = out / f"{row['osm_relation']}.gpx"
        try:
            trip = actor.route(request)["trip"]
        except RuntimeError as e:
            target.unlink(missing_ok=True)
            print(row["osm_relation"], "no route:", str(e)[:120])
            continue
        shape = []
        for leg in trip["legs"]:
            pts = decode_polyline6(leg["shape"])
            shape += pts if not shape else pts[1:]
        write_gpx(target, "valhalla_routes.py", f"Valhalla {row['osm_relation']}", shape)
        print(row["osm_relation"], "ok", round(trip["summary"]["length"], 2), "km")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Route every reference itinerary with BRouter (desktop), same points as valhalla_routes.py.

Starts a local BRouter RouteServer on 127.0.0.1, writes one GPX per route named
<osm_relation>.gpx for Trekbuddy's compare_routes, then stops the server.
Expects the unzipped BRouter release in work/brouter/brouter-<version>/ (all-in-one jar and
profiles2/) and the .rd5 segments in work/brouter/segments/.

Usage: python3 pipeline/brouter_routes.py <out_dir> [--via-km 2] [--profile hiking-mountain]
"""
import argparse
import glob
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from reference_points import itineraries, waypoints, write_gpx

BROUTER = Path("work/brouter")
PORT = 17777


def start_server():
    release = Path(glob.glob(str(BROUTER / "brouter-*/"))[0])
    jar = glob.glob(str(release / "brouter-*-all.jar"))[0]
    server = subprocess.Popen(
        ["java", "-Xmx2g", "-cp", jar, "btools.server.RouteServer",
         str(BROUTER / "segments"), str(release / "profiles2"), str(BROUTER / "customprofiles"),
         str(PORT), "1", "127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            return server
        except OSError:
            time.sleep(0.5)
    server.kill()
    raise RuntimeError("BRouter server did not start")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir")
    parser.add_argument("--via-km", type=float, help="intermediate point every N km of the reference")
    parser.add_argument("--profile", default="hiking-mountain")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (BROUTER / "customprofiles").mkdir(exist_ok=True)
    server = start_server()
    try:
        for row in itineraries():
            stops = waypoints(row["points"], args.via_km)
            lonlats = "|".join(f"{lon},{lat}" for lat, lon in stops)
            url = (f"http://127.0.0.1:{PORT}/brouter?lonlats={lonlats}"
                   f"&profile={args.profile}&alternativeidx=0&format=gpx")
            target = out / f"{row['osm_relation']}.gpx"
            try:
                gpx = urllib.request.urlopen(url, timeout=120).read().decode()
            except urllib.error.HTTPError as e:
                target.unlink(missing_ok=True)
                print(row["osm_relation"], "no route:", e.read().decode()[:120].strip())
                continue
            # BRouter writes lon before lat in its trkpt elements.
            shape = [(float(lat), float(lon)) for lon, lat in
                     re.findall(r'<trkpt lon="([-\d.]+)" lat="([-\d.]+)"', gpx)]
            write_gpx(target, "brouter_routes.py", f"BRouter {row['osm_relation']}", shape)
            length = re.search(r"track-length = (\d+)", gpx)
            print(row["osm_relation"], "ok", int(length[1]) / 1000 if length else "?", "km")
    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# Build the map files of the z9 cells, plus overview.pmtiles (base zooms 0-8, whole coverage):
# - base.pmtiles: OpenMapTiles schema, zooms 9-14. Built once for the whole coverage from
#   work/osm/build.osm.pbf (pipeline/build_osm.sh), then cut into cells: rebuilding it per cell
#   rereads the whole extract every time;
# - dem.pmtiles: Mapterhorn terrarium elevation, zooms 9-12, extracted from the public planet file;
# - contours.geojson: contour lines every 10 m from the DEM (pipeline/contours.py);
# - trek.pmtiles: profiles/TrekProfile.java (hiking overlay + contour lines), zooms 9-14.
# Usage: pipeline/build_tiles.sh [272/180 271/181 ...]  (run from the repo root; no cells = all
#        the cells in coverage/cells.csv)
# Settings: JAVA (Java 25, default java), JOBS (cells built at the same time, default 3: trek
# takes ~5.5 GB of memory). Needs work/planetiler/planetiler.jar (0.10.2), the pmtiles CLI on the
# PATH or in work/bin, and the venv in work/.venv.
set -euo pipefail

export JAVA="${JAVA:-java}"
export PYTHON="$PWD/$( [ -x work/.venv/bin/python ] && echo work/.venv/bin/python || echo work/.venv/Scripts/python )"
export PATH="$PWD/work/bin:$PATH"
JOBS="${JOBS:-3}"
if [ $# -eq 0 ]; then
  set -- $(tail -n +2 coverage/cells.csv | cut -d, -f2,3 | tr , /)
fi

# Planetiler keeps the OpenMapTiles sources in ./data/sources. Paths stay relative: Planetiler turns
# the output path into a URI and rejects absolute paths with spaces.
mkdir -p work/planetiler work/cells
cd work/planetiler
if [ ! base-all.pmtiles -nt ../osm/build.osm.pbf ]; then
  # --download fetches Natural Earth, water polygons and lake centerlines the first time.
  "$JAVA" -Xmx16g -jar planetiler.jar --osm_path=../osm/build.osm.pbf --minzoom=9 --maxzoom=14 \
    --force --download --output=base-all.pmtiles > base-all.log 2>&1
fi
# Overview: base zooms 0-8 over the bounding box of all the cells, one file for the whole coverage
# (below z9 a tile spans several cells).
if [ ! overview.pmtiles -nt ../osm/build.osm.pbf ]; then
  overview_bounds="$("$PYTHON" -c "
import csv, math
n = 2 ** 9
lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
rows = list(csv.DictReader(open('../../coverage/cells.csv')))
xs = [int(r['x']) for r in rows]; ys = [int(r['y']) for r in rows]
print(f'{min(xs) / n * 360 - 180},{lat(max(ys) + 1)},{(max(xs) + 1) / n * 360 - 180},{lat(min(ys))}')")"
  "$JAVA" -Xmx16g -jar planetiler.jar --osm_path=../osm/build.osm.pbf --minzoom=0 --maxzoom=8 \
    --bounds="$overview_bounds" --force --output=overview.pmtiles > overview.log 2>&1
fi

build_cell() {
  local x="${1%/*}" y="${1#*/}"
  local out="../cells/9-$x-$y"
  # Cell bbox inset by a hair, so tiles that only touch the cell border are left out.
  local bounds
  bounds="$("$PYTHON" -c "
import math
n = 2 ** 9
lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
e = 1e-6
print(f'{$x / n * 360 - 180 + e},{lat($y + 1) + e},{($x + 1) / n * 360 - 180 - e},{lat($y) - e}')")"
  mkdir -p "$out"
  pmtiles extract base-all.pmtiles "$out/base.pmtiles" --bbox="$bounds" --minzoom=9 --maxzoom=14 > /dev/null 2>&1
  # Range requests on the planet file: only the cell's tiles are downloaded. Network errors
  # happen (3 of 169 cells in M1-03): up to 3 attempts.
  local try
  for try in 1 2 3; do
    pmtiles extract https://download.mapterhorn.com/planet.pmtiles "$out/dem.pmtiles" --bbox="$bounds" \
      --minzoom=9 --maxzoom=12 > /dev/null 2>&1 && break
    [ "$try" = 3 ] && { echo "9-$x-$y: DEM extract failed" >&2; return 1; }
    sleep 10
  done
  "$PYTHON" ../../pipeline/contours.py "$out"
  local contours=()
  [ -f "$out/contours.geojson" ] && contours=(--contours_path="$out/contours.geojson")
  # Own temp folder: several cells run at the same time.
  "$JAVA" -Xmx6g -cp planetiler.jar ../../profiles/TrekProfile.java --osm_path=../osm/build.osm.pbf \
    --bounds="$bounds" --minzoom=9 --maxzoom=14 --force --tmpdir="$out/tmp" \
    "${contours[@]}" --output="$out/trek.pmtiles" > "$out/trek.log" 2>&1
  rm -rf "$out/tmp"
  du -h "$out"/*.pmtiles
}
export -f build_cell
printf '%s\n' "$@" | xargs -P "$JOBS" -I{} bash -c 'set -euo pipefail; build_cell {}'

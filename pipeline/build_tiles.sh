#!/usr/bin/env bash
# Build the map files of each z9 cell:
# - dem.pmtiles: Mapterhorn terrarium elevation, zooms 9-12, extracted from the public planet file;
# - contours.geojson: contour lines every 10 m from the DEM (pipeline/contours.py);
# - base.pmtiles: OpenMapTiles schema, zooms 9-14, from the merged OSM extract made by build_routing.sh;
# - trek.pmtiles: profiles/TrekProfile.java (hiking overlay + contour lines), zooms 9-14.
# Needs Java 25 (brew install openjdk@25), work/planetiler/planetiler.jar (0.10.2), the pmtiles CLI
# and the venv in work/.venv.
# Usage: pipeline/build_tiles.sh 272/180 271/181 275/189  (run from the repo root)
set -euo pipefail

JAVA="$(brew --prefix openjdk@25)/bin/java"
DEM_PLANET=https://download.mapterhorn.com/planet.pmtiles
mkdir -p work/planetiler
# Planetiler keeps the OpenMapTiles sources in ./data/sources. Paths stay relative: Planetiler turns
# the output path into a URI and rejects absolute paths with spaces.
cd work/planetiler
OSM=../osm/build.osm.pbf

for cell in "$@"; do
  x="${cell%/*}"; y="${cell#*/}"
  # Cell bbox inset by a hair, so tiles that only touch the cell border are left out.
  bounds="$(python3 -c "
import math
n = 2 ** 9
lat = lambda t: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * t / n))))
e = 1e-6
print(f'{$x / n * 360 - 180 + e},{lat($y + 1) + e},{($x + 1) / n * 360 - 180 - e},{lat($y) - e}')")"
  out="../cells/9-$x-$y"
  mkdir -p "$out"
  common=(--osm_path="$OSM" --bounds="$bounds" --minzoom=9 --maxzoom=14 --force)

  # Range requests on the planet file: only the cell's tiles are downloaded.
  pmtiles extract "$DEM_PLANET" "$out/dem.pmtiles" --bbox="$bounds" --minzoom=9 --maxzoom=12
  ../.venv/bin/python ../../pipeline/contours.py "$out"

  # --download fetches Natural Earth, water polygons and lake centerlines the first time.
  /usr/bin/time -l "$JAVA" -Xmx3g -jar planetiler.jar "${common[@]}" --download \
    --output="$out/base.pmtiles" > "$out/base.log" 2>&1
  /usr/bin/time -l "$JAVA" -Xmx2g -cp planetiler.jar ../../profiles/TrekProfile.java "${common[@]}" \
    --contours_path="$out/contours.geojson" --output="$out/trek.pmtiles" > "$out/trek.log" 2>&1
  du -h "$out"/*.pmtiles
done

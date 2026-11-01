#!/usr/bin/env bash
# Build one Valhalla routing graph for a set of OSM extracts.
# All cells must be packed from the same build: tiles from different builds do not connect
# at their borders.
# Usage: pipeline/build_routing.sh  (run from the repo root, after creating work/.venv)
set -euo pipefail

WORK=work
VENV="$WORK/.venv"
# download.geofabrik.de is unreachable from the dev machine; openstreetmap.fr has the same data
# split by Italian region.
MIRROR=https://download.openstreetmap.fr/extracts/europe/italy
# "regions|bbox": each group is clipped to its bbox before merging, so the build only covers
# the test cells and the reference routes plus a margin of about 15 km (west,south,east,north).
EXTRACTS=(
  "trentino_alto_adige veneto lombardia|10.2,45.8,12.2,47.1"  # test cells, Gardena, Brenta
  "abruzzo|13.1,41.8,14.3,42.8"                              # test cell, Gran Sasso, Majella
  "lombardia|9.18,45.78,9.54,46.10"                          # Grigne
  "valle_aosta|7.21,45.44,7.64,45.80"                        # Gran Paradiso - Cogne
  "friuli_venezia_giulia|12.70,46.27,13.30,46.73"            # Alpi Carniche e Giulie
  "toscana emilia_romagna|10.65,43.93,11.04,44.36"           # Appennino tosco-emiliano
  "marche umbria|12.94,42.64,13.44,43.06"                    # Monti Sibillini
  "calabria basilicata|16.03,39.72,16.43,40.10"              # Pollino
)

mkdir -p "$WORK/osm" "$WORK/valhalla"
clipped=()
for i in "${!EXTRACTS[@]}"; do
  regions="${EXTRACTS[$i]%%|*}"
  bbox="${EXTRACTS[$i]##*|}"
  inputs=()
  for r in $regions; do
    pbf="$WORK/osm/$r.osm.pbf"
    if [ ! -f "$pbf" ]; then
      curl -fsSL --retry 3 -o "$pbf.part" "$MIRROR/$r.osm.pbf"
      # The mirror's .md5 files can lag a day behind the extracts, so check integrity by
      # decoding the whole file instead.
      osmium fileinfo -e -F pbf "$pbf.part" > /dev/null
      mv "$pbf.part" "$pbf"
    fi
    inputs+=("$pbf")
  done
  osmium merge --overwrite -o "$WORK/osm/group$i.osm.pbf" "${inputs[@]}"
  osmium extract --overwrite -s smart -b "$bbox" -o "$WORK/osm/group$i-clip.osm.pbf" "$WORK/osm/group$i.osm.pbf"
  rm "$WORK/osm/group$i.osm.pbf"
  clipped+=("$WORK/osm/group$i-clip.osm.pbf")
done
osmium merge --overwrite -o "$WORK/osm/build.osm.pbf" "${clipped[@]}"
# Move CAI difficulty and marked-trail information from relations onto ways (docs/preprocessing.md).
"$VENV/bin/python" pipeline/preprocess_osm.py "$WORK/osm/build.osm.pbf" \
  "$WORK/osm/build-pre.osm.pbf" "$WORK/osm/preprocess-report.json"

"$VENV/bin/valhalla_build_config" \
  --mjolnir-tile-dir "$WORK/valhalla/tiles" \
  --mjolnir-tile-extract "$WORK/valhalla/tiles.tar" \
  --mjolnir-concurrency 4 \
  > "$WORK/valhalla/valhalla.json"

rm -rf "$WORK/valhalla/tiles"
# The pyvalhalla console wrappers look executables up on PATH, so call the binary directly.
BIN="$("$VENV/bin/python" -m valhalla print_bin_path)"
# time -l reports wall time and peak memory (maximum resident set size) at the end of the log.
/usr/bin/time -l "$BIN/valhalla_build_tiles" -c "$WORK/valhalla/valhalla.json" "$WORK/osm/build-pre.osm.pbf" \
  2>&1 | tee "$WORK/valhalla/build.log"
du -sh "$WORK/valhalla/tiles"

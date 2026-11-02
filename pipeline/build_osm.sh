#!/usr/bin/env bash
# OSM input of the whole coverage: Geofabrik extracts of one date, merged, clipped to the cells
# (coverage/area.geojson) and preprocessed.
# Output: work/osm/build.osm.pbf (map tiles) and work/osm/build-pre.osm.pbf (routing).
# Usage: pipeline/build_osm.sh 261101  (Geofabrik date YYMMDD; run from the repo root)
# Tools: OSMIUM (osmium-tool), PYTHON (venv with pipeline/requirements.txt); see README.
set -euo pipefail

DATE="$1"
PYTHON="${PYTHON:-$( [ -x work/.venv/bin/python ] && echo work/.venv/bin/python || echo work/.venv/Scripts/python )}"
OSMIUM="${OSMIUM:-osmium}"
D=work/osm/$DATE
mkdir -p "$D"

# Extracts of one date share the same OSM snapshot. Geofabrik has no dated files for France's
# regions, so corse is the latest one and may be a day off.
for p in europe/italy europe/alps europe/slovenia europe/croatia europe/france/corse; do
  f="$D/$(basename "$p").osm.pbf"
  [ -f "$f" ] && continue
  url="https://download.geofabrik.de/$p-$DATE.osm.pbf"
  [ "$p" = europe/france/corse ] && url="https://download.geofabrik.de/$p-latest.osm.pbf"
  curl -fsSL --retry 3 -o "$f.part" "$url"
  mv "$f.part" "$f"
done

"$OSMIUM" merge --overwrite -o "$D/merged.osm.pbf" "$D"/italy.osm.pbf "$D"/alps.osm.pbf \
  "$D"/slovenia.osm.pbf "$D"/croatia.osm.pbf "$D"/corse.osm.pbf
# Objects in two extracts of different snapshots come out in two versions: keep the newest.
"$OSMIUM" time-filter --overwrite -o "$D/single.osm.pbf" "$D/merged.osm.pbf"
rm "$D/merged.osm.pbf"
"$OSMIUM" extract --overwrite -s smart -p coverage/area.geojson -o work/osm/build.osm.pbf "$D/single.osm.pbf"
rm "$D/single.osm.pbf"
# Move CAI difficulty and marked-trail information from relations onto ways (docs/preprocessing.md).
"$PYTHON" -I pipeline/preprocess_osm.py work/osm/build.osm.pbf work/osm/build-pre.osm.pbf \
  work/osm/preprocess-report.json
echo "$DATE" > work/osm/build.date

#!/usr/bin/env bash
# Build one Valhalla routing graph for the whole coverage, from work/osm/build-pre.osm.pbf
# (pipeline/build_osm.sh).
# All cells must be packed from the same build: tiles from different builds do not connect
# at their borders.
# Usage: pipeline/build_routing.sh  (run from the repo root)
# Settings: VALHALLA_THREADS (default 4), VALHALLA_ENHANCE_THREADS (default 1 on Windows, else
# VALHALLA_THREADS); the Valhalla executables are the ones bundled with pyvalhalla in the venv.
set -euo pipefail

WORK=work
VENV_BIN="$( [ -d work/.venv/bin ] && echo work/.venv/bin || echo work/.venv/Scripts )"
BIN="$("$VENV_BIN/python" -m valhalla print_bin_path | tr -d '\r')"
EXE=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    EXE=.exe
    BIN="$(cygpath -u "$BIN")"
    # The executables need the DLLs bundled with pyvalhalla; its own launcher fails on Windows.
    export PATH="$BIN/../../pyvalhalla.libs:$PATH"
    ;;
esac
THREADS="${VALHALLA_THREADS:-4}"
# On Windows (pyvalhalla 3.9.1) the enhance stage stops with 0xC0000409 when it runs on more
# than one thread.
ENHANCE_THREADS="${VALHALLA_ENHANCE_THREADS:-$([ -n "$EXE" ] && echo 1 || echo "$THREADS")}"

mkdir -p "$WORK/valhalla"
"$VENV_BIN/valhalla_build_config$EXE" \
  --mjolnir-tile-dir "$WORK/valhalla/tiles" \
  --mjolnir-tile-extract "$WORK/valhalla/tiles.tar" \
  --mjolnir-concurrency "$THREADS" \
  > "$WORK/valhalla/valhalla.json"

rm -rf "$WORK/valhalla/tiles"
"$BIN/valhalla_build_tiles$EXE" -c "$WORK/valhalla/valhalla.json" -e build \
  "$WORK/osm/build-pre.osm.pbf" > "$WORK/valhalla/build.log" 2>&1
sed -i "s/\"concurrency\": [0-9]*/\"concurrency\": $ENHANCE_THREADS/" "$WORK/valhalla/valhalla.json"
"$BIN/valhalla_build_tiles$EXE" -c "$WORK/valhalla/valhalla.json" -s enhance \
  "$WORK/osm/build-pre.osm.pbf" >> "$WORK/valhalla/build.log" 2>&1
du -sh "$WORK/valhalla/tiles"

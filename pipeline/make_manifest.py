#!/usr/bin/env python3
"""Release folders for the cells, one per release group, plus the release index.

A release has no folders, so each file becomes `<cell>_<file>` (e.g. 9-271-181_base.pmtiles).
Each group folder holds its cells' files and a manifest.json listing every cell with its files,
sizes and SHA-256 hashes; the app checks them before using a downloaded cell. routing.tar.gz
also carries unpacked_size, the size of routing.tar once unpacked on the phone. label names the
cell in the app before download: the most important place in its index.sqlite (city, then town,
then village), the one nearest the cell centre.
releases.json, in the output folder, lists the groups with their release name (tag), cells
and total size, and the overview (base zooms 0-8 of the whole coverage, downloaded by the app at
first launch) with its tag, asset, size and SHA-256.

Usage: python3 -I pipeline/make_manifest.py work/cells coverage/cells.csv <version> work/release \
           [work/planetiler/overview.pmtiles]
       (version: date of the OSM build, e.g. 2026-11-01)
"""
import csv
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # -I leaves the script folder out
from coverage import tile_bounds  # noqa: E402

CELL_FILES = ["base.pmtiles", "trek.pmtiles", "dem.pmtiles", "routing.tar.gz", "index.sqlite"]
PLACE_RANK = ["city", "town", "village"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gzip_size(path: Path) -> int:
    """Uncompressed size; the gzip trailer only holds it modulo 4 GiB, so read it all."""
    size = 0
    with gzip.open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            size += len(chunk)
    return size


def label(cell: Path) -> str | None:
    index = cell / "index.sqlite"
    if not index.exists():
        return None
    _, x, y = (int(v) for v in cell.name.split("-"))
    w, s, e, n = tile_bounds(x, y)
    db = sqlite3.connect(index)
    rows = db.execute(f"SELECT name, kind, lat, lon FROM place WHERE kind IN ({','.join('?' * len(PLACE_RANK))})",
                      PLACE_RANK).fetchall()
    db.close()
    if not rows:
        return None
    cy, cx = (s + n) / 2, (w + e) / 2
    return min(rows, key=lambda r: (PLACE_RANK.index(r[1]), (r[2] - cy) ** 2 + (r[3] - cx) ** 2))[0]


def link_or_copy(src: Path, dst: Path) -> None:
    dst.unlink(missing_ok=True)
    # Hard link when possible: the release folder costs no extra space.
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main(cells_dir: str, cells_csv: str, version: str, out_dir: str, overview: str | None = None) -> None:
    with open(cells_csv, encoding="utf-8") as f:
        group_of = {row["cell"]: row["group"] for row in csv.DictReader(f)}
    out = Path(out_dir)
    by_group = defaultdict(list)
    for cell in sorted(p for p in Path(cells_dir).iterdir() if p.is_dir()):
        group = group_of[cell.name]
        dst_dir = out / group
        dst_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for name in CELL_FILES:
            src = cell / name
            if not src.exists():
                continue
            asset = f"{cell.name}_{name}"
            link_or_copy(src, dst_dir / asset)
            entry ={"name": name, "asset": asset, "size": src.stat().st_size, "sha256": sha256(src)}
            if name.endswith(".gz"):
                entry["unpacked_size"] = gzip_size(src)
            files.append(entry)
        entry = {"id": cell.name, "files": files}
        if name := label(cell):
            entry["label"] = name
        by_group[group].append(entry)
        print(f"{group} {cell.name}: {len(files)} files, {sum(f['size'] for f in files)} bytes")

    index = []
    for group, cells in sorted(by_group.items()):
        manifest = {"schema": 1, "version": version, "cells": cells}
        (out / group / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        index.append({
            "group": group,
            "tag": f"cells-{version}-{group}",
            "cells": [c["id"] for c in cells],
            "size": sum(f["size"] for c in cells for f in c["files"]),
        })
    releases = {"schema": 1, "version": version, "releases": index}
    if overview:
        src = Path(overview)
        (out / "overview").mkdir(parents=True, exist_ok=True)
        link_or_copy(src, out / "overview" / "overview.pmtiles")
        releases["overview"] = {"tag": f"overview-{version}", "asset": "overview.pmtiles",
                                "size": src.stat().st_size, "sha256": sha256(src)}
        print(f"overview: {src.stat().st_size} bytes")
    (out / "releases.json").write_text(json.dumps(releases, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:6])

#!/usr/bin/env python3
"""Release folder for a set of cells: the cell files with flat asset names plus manifest.json.

A release has no folders, so each file becomes `<cell>_<file>` (e.g. 9-271-181_base.pmtiles).
manifest.json lists every cell with its files, sizes and SHA-256 hashes; the app checks them
before using a downloaded cell.

Usage: python3 -I pipeline/make_manifest.py work/cells <version> work/release
       (version: date of the OSM build, e.g. 2026-10-31)
"""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

CELL_FILES = ["base.pmtiles", "trek.pmtiles", "dem.pmtiles", "routing.tar", "index.sqlite"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(cells_dir: str, version: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cells = []
    for cell in sorted(p for p in Path(cells_dir).iterdir() if p.is_dir()):
        files = []
        for name in CELL_FILES:
            src = cell / name
            if not src.exists():
                continue
            asset = f"{cell.name}_{name}"
            dst = out / asset
            dst.unlink(missing_ok=True)
            # Hard link when possible: the release folder costs no extra space.
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
            files.append({"name": name, "asset": asset, "size": src.stat().st_size, "sha256": sha256(src)})
        cells.append({"id": cell.name, "files": files})
        print(f"{cell.name}: {len(files)} files, {sum(f['size'] for f in files)} bytes")
    manifest = {"schema": 1, "version": version, "cells": cells}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])

#!/usr/bin/env python3
"""Merge the per-cell PMTiles of one layer into one file for the whole coverage.

The app reads it over the network, by range requests, where a cell is not downloaded (trek
overlay online). Zooms 9-14 of a z9 cell are nested in the cell, so the cells hold no tile in
common and the merge only reorders the tiles by id.
Usage: python3 -I pipeline/merge_pmtiles.py work/cells trek.pmtiles work/trek-online.pmtiles
"""
import sys
from pathlib import Path

from pmtiles.reader import MmapSource, Reader, all_tiles, zxy_to_tileid
from pmtiles.writer import Writer


def main(cells_dir: str, name: str, out: str) -> None:
    files = sorted(p / name for p in Path(cells_dir).iterdir() if (p / name).exists())
    index = []  # (tile id, file number, z, x, y)
    for n, path in enumerate(files):
        with open(path, "rb") as f:
            for (z, x, y), _ in all_tiles(MmapSource(f)):
                index.append((zxy_to_tileid(z, x, y), n, z, x, y))
    index.sort()
    handles = [open(p, "rb") for p in files]
    readers = [Reader(MmapSource(h)) for h in handles]
    header = readers[0].header()
    metadata = readers[0].metadata()
    bounds = [readers[0].header()[k] for k in ("min_lon_e7", "min_lat_e7", "max_lon_e7", "max_lat_e7")]
    for r in readers[1:]:
        h = r.header()
        bounds = [min(bounds[0], h["min_lon_e7"]), min(bounds[1], h["min_lat_e7"]),
                  max(bounds[2], h["max_lon_e7"]), max(bounds[3], h["max_lat_e7"])]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        writer = Writer(f)
        for tile_id, n, z, x, y in index:
            writer.write_tile(tile_id, readers[n].get(z, x, y))
        header.update(min_lon_e7=bounds[0], min_lat_e7=bounds[1], max_lon_e7=bounds[2], max_lat_e7=bounds[3],
                      center_lon_e7=(bounds[0] + bounds[2]) // 2, center_lat_e7=(bounds[1] + bounds[3]) // 2)
        writer.finalize(header, metadata)
    for h in handles:
        h.close()
    print(f"{len(files)} cells, {len(index)} tiles, {Path(out).stat().st_size} bytes")


if __name__ == "__main__":
    main(*sys.argv[1:4])

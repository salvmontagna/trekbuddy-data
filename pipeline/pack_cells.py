#!/usr/bin/env python3
"""Pack Valhalla graph tiles into one routing.tar per z9 cell.

A cell gets every tile, on every hierarchy level, whose bounding box intersects the cell:
level 2 (0.25 deg) for local paths, levels 1 (1 deg) and 0 (4 deg) for the long-distance
network that Valhalla needs to connect them.
Usage: python3 -I pipeline/pack_cells.py work/valhalla/tiles work/cells 272/180 271/181 275/189
"""
import math
import sys
import tarfile
from pathlib import Path

ZOOM = 9
LEVEL_TILE_DEG = {0: 4.0, 1: 1.0, 2: 0.25}


def cell_bbox(x: int, y: int) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a web-mercator tile."""
    n = 2**ZOOM
    lat = lambda yy: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / n))))
    return x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)


def tile_bbox(rel_path: Path) -> tuple[int, tuple[float, float, float, float]]:
    """Level and bbox of a Valhalla tile from its path, e.g. 2/000/818/660.gph."""
    level = int(rel_path.parts[0])
    tile_id = int("".join(rel_path.parts[1:]).removesuffix(".gph"))
    size = LEVEL_TILE_DEG[level]
    ncols = round(360 / size)
    row, col = divmod(tile_id, ncols)
    west, south = -180 + col * size, -90 + row * size
    return level, (west, south, west + size, south + size)


def intersects(a, b) -> bool:
    # Touching edges do not count: a tile that only shares a border has no data inside the cell.
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def main(tiles_dir: str, out_dir: str, cells: list[str]) -> None:
    root = Path(tiles_dir)
    tiles = [p.relative_to(root) for p in sorted(root.rglob("*.gph"))]
    print("cell,level,tiles,bytes")
    for cell in cells:
        x, y = map(int, cell.split("/"))
        bbox = cell_bbox(x, y)
        out = Path(out_dir) / f"{ZOOM}-{x}-{y}"
        out.mkdir(parents=True, exist_ok=True)
        per_level = {lvl: [0, 0] for lvl in LEVEL_TILE_DEG}
        # Plain tar, no compression: Valhalla memory-maps the archive and reads tiles in place.
        with tarfile.open(out / "routing.tar", "w", format=tarfile.USTAR_FORMAT) as tar:
            for rel in tiles:
                level, tb = tile_bbox(rel)
                if intersects(bbox, tb):
                    tar.add(root / rel, arcname=str(rel))
                    per_level[level][0] += 1
                    per_level[level][1] += (root / rel).stat().st_size
        for level, (count, size) in per_level.items():
            print(f"{ZOOM}-{x}-{y},{level},{count},{size}")
        print(f"{ZOOM}-{x}-{y},tar,,{(out / 'routing.tar').stat().st_size}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])

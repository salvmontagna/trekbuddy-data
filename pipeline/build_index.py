#!/usr/bin/env python3
"""index.sqlite of each z9 cell: offline search and the hiking route catalogue (M1-05, F20).

Tables (schema 1):
  meta    schema, OSM data date, attribution;
  place   named places, peaks and saddles, huts and bivouacs, water points (named or not) and
          named car parks: OSM id, kind, name, lat/lon, elevation (ele tag, else the DEM);
  route   one row per route=hiking relation touching the cell, keyed by relation_id like the
          hiking_route layer of trek.pmtiles: ref, name, network, operator, from/to, osmc
          symbol, difficulty and its source, length, ascent/descent, min/max elevation,
          roundtrip, T21 class, bounding box and simplified geometry (JSON list of encoded
          polylines, precision 5);
  search  FTS5 over place and route names, refs and an Italian kind word ("rifugio",
          "sentiero"...), so "sentiero 200" or "rifugio franchetti" find their row.
A relation crossing several cells is written to each of them, complete: the app keeps one.

Difficulty: cai_scale of the relation; without it, the highest sac_scale of its ways mapped to
the CAI scale (T1 T, T2 E, T3 EE, T4 EE, T5-T6 EEA; EEA means equipment, so T4 stays EE).
Length on the main ways. Ascent and descent from the cells' DEM (dem.pmtiles, z12) every
SAMPLE_M along the joined line, counting only changes of at least CLIMB_M; left empty when the
ways do not join into one line (branched or broken relations, T21) or the DEM is missing.

Usage: python3 -I pipeline/build_index.py work/osm/build.osm.pbf coverage/cells.csv work/cells \
           [9-275-189 ...]   (no cells = every built cell in work/cells)
Data © OpenStreetMap contributors, ODbL.
"""
import csv
import json
import math
import re
import sqlite3
import sys
import time
from collections import OrderedDict
from pathlib import Path

import osmium
from shapely.geometry import LineString, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent))  # -I leaves the script folder out
from cai_coverage import MAIN_ROLES, MAX_GAP_M, classify_graph, haversine, length_m  # noqa: E402
from contours import DEM_ZOOM, TILE_PX, cell_grid  # noqa: E402
from coverage import tile_bounds  # noqa: E402

SCHEMA = 1
SAMPLE_M = 20.0
CLIMB_M = 5.0
SIMPLIFY_DEG = 0.00005  # ~5 m
SAC_TO_CAI = {
    "hiking": "T",
    "mountain_hiking": "E",
    "demanding_mountain_hiking": "EE",
    "alpine_hiking": "EE",
    "demanding_alpine_hiking": "EEA",
    "difficult_alpine_hiking": "EEA",
}
CAI_ORDER = ["T", "E", "EE", "EEA"]
# OSM tags -> (kind, Italian word for the search).
PLACES = {
    ("place", "city"): ("city", "località"),
    ("place", "town"): ("town", "località"),
    ("place", "village"): ("village", "località"),
    ("place", "hamlet"): ("hamlet", "località"),
    ("place", "locality"): ("locality", "località"),
    ("natural", "peak"): ("peak", "vetta"),
    ("natural", "volcano"): ("peak", "vetta"),
    ("natural", "saddle"): ("saddle", "sella passo"),
    ("mountain_pass", "yes"): ("saddle", "sella passo"),
    ("tourism", "alpine_hut"): ("alpine_hut", "rifugio"),
    ("tourism", "wilderness_hut"): ("wilderness_hut", "bivacco"),
    ("amenity", "drinking_water"): ("drinking_water", "acqua fontana"),
    ("natural", "spring"): ("spring", "acqua sorgente"),
    ("amenity", "parking"): ("parking", "parcheggio"),
}
UNNAMED_OK = {"drinking_water", "spring", "peak", "saddle"}


def place_kind(tags):
    for (k, v), kind in PLACES.items():
        if tags.get(k) == v:
            return kind
    return None


def cai_grade(value: str) -> str:
    """CAI grade of a cai_scale value ("EEA:PD" -> "EEA"), or ""."""
    head = value.strip().upper().split(":")[0]
    return head if head in CAI_ORDER else ""


def join_line(ways):
    """The ways joined into one line that walks each way once, or None when they cannot (branches
    or gaps over MAX_GAP_M, as in T21). Endpoints within MAX_GAP_M are one vertex; the line is an
    Euler path over the ways (Hierholzer), so a route crossing itself still joins."""
    if classify_graph(ways) != "valid_reordered":
        return None
    ends = [p for w in ways for p in (w[0], w[-1])]
    vertex = list(range(len(ends)))
    for i in range(len(ends)):
        for j in range(i):
            if haversine(ends[i], ends[j]) <= MAX_GAP_M:
                vertex[i] = vertex[j]
                break
    adj = {}
    for k in range(len(ways)):
        a, b = vertex[2 * k], vertex[2 * k + 1]
        adj.setdefault(a, []).append((k, b, False))
        adj.setdefault(b, []).append((k, a, True))
    odd = [v for v, edges in adj.items() if len(edges) % 2]
    used = [False] * len(ways)
    stack, path = [(odd[0] if odd else vertex[0], None)], []
    while stack:
        v, step = stack[-1]
        while adj[v] and used[adj[v][-1][0]]:
            adj[v].pop()
        if adj[v]:
            k, nxt, rev = adj[v].pop()
            used[k] = True
            stack.append((nxt, (k, rev)))
        else:
            stack.pop()
            if step:
                path.append(step)
    line = []
    for k, rev in reversed(path):
        line.extend(reversed(ways[k]) if rev else ways[k])
    return line


class Dem:
    """Elevation from the z12 terrarium tiles of the built cells. A decoded cell takes 64 MB, so
    only the last MAX_GRIDS stay in memory; routes are processed in geographic order."""

    MAX_GRIDS = 9

    def __init__(self, cells_dir: Path):
        self.cells_dir = cells_dir
        self.grids = OrderedDict()

    def _grid(self, x9, y9):
        key = (x9, y9)
        if key in self.grids:
            self.grids.move_to_end(key)
        else:
            dem = self.cells_dir / f"9-{x9}-{y9}" / "dem.pmtiles"
            grid = cell_grid(dem, x9, y9) if dem.exists() else None
            self.grids[key] = grid
            if len(self.grids) > self.MAX_GRIDS:
                self.grids.popitem(last=False)
        return self.grids[key]

    def at(self, lat, lon):
        world = 2 ** DEM_ZOOM * TILE_PX
        gx = (lon + 180) / 360 * world
        gy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * world
        side = 2 ** (DEM_ZOOM - 9) * TILE_PX
        x9, y9 = int(gx // side), int(gy // side)
        grid = self._grid(x9, y9)
        if grid is None:
            return None
        ele = float(grid[min(int(gy - y9 * side), side - 1), min(int(gx - x9 * side), side - 1)])
        return None if math.isnan(ele) else ele  # missing DEM tile (open sea)


def profile(line, dem: Dem):
    """Ascent, descent, min and max elevation along the line, or None without DEM."""
    samples = []
    carry = 0.0
    for a, b in zip(line, line[1:]):
        d = haversine(a, b)
        t = carry
        while t < d:
            f = t / d
            ele = dem.at(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            if ele is None:
                return None
            samples.append(ele)
            t += SAMPLE_M
        carry = t - d
    end = dem.at(*line[-1])
    if end is None:
        return None
    samples.append(end)
    up = down = 0.0
    ref = samples[0]
    for e in samples[1:]:
        if e - ref >= CLIMB_M:
            up += e - ref
            ref = e
        elif ref - e >= CLIMB_M:
            down += ref - e
            ref = e
    return round(up), round(down), round(min(samples)), round(max(samples))


def encode_polyline(points) -> str:
    """Google encoded polyline, precision 5, from (lat, lon) points."""
    out, plat, plon = [], 0, 0
    for lat, lon in points:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def simplified(line):
    ls = LineString([(p[1], p[0]) for p in line]).simplify(SIMPLIFY_DEG)
    return [(lat, lon) for lon, lat in ls.coords]


def read_osm(pbf: str):
    t0 = time.time()
    relations = {}
    for r in osmium.FileProcessor(pbf, osmium.osm.RELATION).with_filter(osmium.filter.TagFilter(("route", "hiking"))):
        relations[r.id] = {
            "tags": {k: r.tags.get(k, "") for k in ("ref", "name", "network", "operator", "from", "to",
                                                     "osmc:symbol", "cai_scale", "roundtrip")},
            "main": [m.ref for m in r.members if m.type == "w" and m.role in MAIN_ROLES],
            "has_sub": any(m.type == "r" for m in r.members),
        }
    print(f"{len(relations)} hiking relations ({time.time() - t0:.0f} s)", file=sys.stderr)

    wanted = {w for rel in relations.values() for w in rel["main"]}
    ways, sac, places = {}, {}, []
    proc = osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations("sparse_mem_array")
    for o in proc:
        if o.is_node():
            kind = place_kind(o.tags) if len(o.tags) else None
            if kind and o.location.valid():
                places.append(_place(o, kind, o.location.lat, o.location.lon))
            continue
        pts = None
        if o.id in wanted:
            pts = [(n.lat, n.lon) for n in o.nodes if n.location.valid()]
            if len(pts) >= 2:
                ways[o.id] = pts
                if o.tags.get("sac_scale"):
                    sac[o.id] = o.tags["sac_scale"]
        kind = place_kind(o.tags) if len(o.tags) else None
        if kind and kind[0] not in ("city", "town", "village", "hamlet", "locality"):
            pts = pts or [(n.lat, n.lon) for n in o.nodes if n.location.valid()]
            if pts:  # area mapped as a way: its mean point
                places.append(_place(o, kind, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
    print(f"{len(ways)} of {len(wanted)} ways, {len(places)} places ({time.time() - t0:.0f} s)", file=sys.stderr)
    return relations, ways, sac, places


def _place(o, kind, lat, lon):
    ele = re.match(r"^\s*(-?\d+(?:[.,]\d+)?)", o.tags.get("ele", ""))
    return {
        "id": f"{'n' if o.is_node() else 'w'}{o.id}",
        "kind": kind[0],
        "word": kind[1],
        "name": o.tags.get("name:it") or o.tags.get("name", ""),
        "lat": lat,
        "lon": lon,
        "ele": round(float(ele.group(1).replace(",", "."))) if ele else None,
    }


def route_rows(relations, ways, sac, dem: Dem, area):
    """Rows of the relations with at least one main way inside area (the requested cells)."""
    t0 = time.time()
    rows = []
    todo = []
    for rid, rel in relations.items():
        parts = [ways[w] for w in rel["main"] if w in ways]
        if parts and any(area.intersects(LineString([(p[1], p[0]) for p in part])) for part in parts):
            todo.append((rid, rel, parts))
    # Geographic order, so the DEM cells in memory are reused.
    todo.sort(key=lambda t: (round(t[2][0][0][0] * 2), t[2][0][0][1]))
    for rid, rel, parts in todo:
        missing = len(rel["main"]) - len(parts)
        tags = rel["tags"]
        grade, source = cai_grade(tags["cai_scale"]), "cai_scale"
        if not grade:
            grades = [SAC_TO_CAI[sac[w]] for w in rel["main"] if sac.get(w) in SAC_TO_CAI]
            grade = max(grades, key=CAI_ORDER.index) if grades else ""
            source = "sac_scale" if grade else ""
        line = None if missing else join_line(parts)
        cls = "incomplete" if missing else ("valid" if line else classify_graph(parts))
        prof = profile(line, dem) if line else None
        geom = [simplified(line)] if line else [simplified(p) for p in parts]
        lats = [p[0] for g in parts for p in g]
        lons = [p[1] for g in parts for p in g]
        roundtrip = tags["roundtrip"] == "yes" or bool(line and haversine(line[0], line[-1]) <= 100)
        rows.append({
            "relation_id": rid,
            "ref": tags["ref"],
            "name": tags["name"],
            "network": tags["network"],
            "operator": tags["operator"],
            "from_name": tags["from"],
            "to_name": tags["to"],
            "osmc_symbol": tags["osmc:symbol"],
            "difficulty": grade or None,
            "difficulty_source": source or None,
            "length_m": round(sum(length_m(p) for p in parts)),
            "ascent_m": prof[0] if prof else None,
            "descent_m": prof[1] if prof else None,
            "ele_min": prof[2] if prof else None,
            "ele_max": prof[3] if prof else None,
            "roundtrip": int(roundtrip),
            "class": cls,
            "min_lat": min(lats), "min_lon": min(lons), "max_lat": max(lats), "max_lon": max(lons),
            "geometry": json.dumps([encode_polyline(g) for g in geom]),
            "_parts": parts,
        })
    print(f"{len(rows)} routes with ways ({time.time() - t0:.0f} s)", file=sys.stderr)
    return rows


ROUTE_COLUMNS = ["relation_id", "ref", "name", "network", "operator", "from_name", "to_name", "osmc_symbol",
                 "difficulty", "difficulty_source", "length_m", "ascent_m", "descent_m", "ele_min", "ele_max",
                 "roundtrip", "class", "min_lat", "min_lon", "max_lat", "max_lon", "geometry"]


def write_cell(path: Path, date: str, places, routes):
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE place (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                            lat REAL NOT NULL, lon REAL NOT NULL, ele INTEGER);
        CREATE TABLE route (relation_id INTEGER PRIMARY KEY, ref TEXT, name TEXT, network TEXT,
                            operator TEXT, from_name TEXT, to_name TEXT, osmc_symbol TEXT,
                            difficulty TEXT, difficulty_source TEXT, length_m INTEGER NOT NULL,
                            ascent_m INTEGER, descent_m INTEGER, ele_min INTEGER, ele_max INTEGER,
                            roundtrip INTEGER NOT NULL, class TEXT NOT NULL,
                            min_lat REAL NOT NULL, min_lon REAL NOT NULL,
                            max_lat REAL NOT NULL, max_lon REAL NOT NULL, geometry TEXT NOT NULL);
        CREATE VIRTUAL TABLE search USING fts5(name, ref, kind, source UNINDEXED, source_id UNINDEXED,
                                               tokenize = 'unicode61 remove_diacritics 2');
    """)
    db.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("schema", str(SCHEMA)), ("osm_date", date), ("attribution", "© OpenStreetMap contributors (ODbL)")])
    db.executemany("INSERT INTO place VALUES (:id, :kind, :name, :lat, :lon, :ele)", places)
    db.executemany(f"INSERT INTO route VALUES ({', '.join(':' + c for c in ROUTE_COLUMNS)})", routes)
    db.executemany("INSERT INTO search VALUES (?, ?, ?, 'place', ?)",
                   [(p["name"], "", p["word"], p["id"]) for p in places if p["name"]])
    db.executemany("INSERT INTO search VALUES (?, ?, 'sentiero', 'route', ?)",
                   [(r["name"] or "", r["ref"] or "", r["relation_id"]) for r in routes if r["name"] or r["ref"]])
    db.execute("INSERT INTO search(search) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()


def main(pbf: str, cells_csv: str, cells_dir: str, *cells: str) -> None:
    cells_dir = Path(cells_dir)
    if not cells:
        cells = sorted(p.name for p in cells_dir.iterdir() if (p / "trek.pmtiles").exists())
    with open(cells_csv, encoding="utf-8") as f:
        xy = {row["cell"]: (int(row["x"]), int(row["y"])) for row in csv.DictReader(f)}
    date_file = Path(pbf).parent / "build.date"
    date = date_file.read_text().strip() if date_file.exists() else ""

    relations, ways, sac, places = read_osm(pbf)
    dem = Dem(cells_dir)
    area = unary_union([box(*tile_bounds(*xy[c])) for c in cells])
    routes = route_rows(relations, ways, sac, dem, area)

    for cell in cells:
        w, s, e, n = tile_bounds(*xy[cell])
        cell_box = box(w, s, e, n)
        cell_places = [dict(p) for p in places if s <= p["lat"] < n and w <= p["lon"] < e
                       and (p["name"] or p["kind"] in UNNAMED_OK)
                       and (p["kind"] != "parking" or p["name"])]
        for p in cell_places:
            if p["ele"] is None and p["kind"] not in ("city", "town", "village", "hamlet", "locality"):
                ele = dem.at(p["lat"], p["lon"])
                p["ele"] = round(ele) if ele is not None else None
        cell_routes = [r for r in routes
                       if r["max_lat"] >= s and r["min_lat"] < n and r["max_lon"] >= w and r["min_lon"] < e
                       and any(cell_box.intersects(LineString([(p[1], p[0]) for p in part])) for part in r["_parts"])]
        out = cells_dir / cell / "index.sqlite"
        write_cell(out, date, cell_places, cell_routes)
        print(f"{cell}: {len(cell_places)} places, {len(cell_routes)} routes, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])

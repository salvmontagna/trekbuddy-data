#!/usr/bin/env python3
"""How many Italian hiking relations can become one usable track, region by region (T21, F20).

Reads the route=hiking relations and their ways from an OSM extract of Italy and classifies
each relation:
  valid_in_order   the main ways, in member order, form one continuous line (gaps <= 30 m,
                   the rule of reference_routes.py);
  valid_reordered  one continuous line exists, but the members are out of order;
  branched         connected, but with variants or side branches (more than two loose ends);
  broken           real gaps between pieces;
  incomplete       some member ways are missing from the extract (near_border counts the
                   ones within 1 km of the national border, cut by the extract);
  container        no ways, only sub-relations (e.g. long-distance superroutes).
Ways with roles such as alternative/excursion/approach are variants by design and are left out
of the line. A relation belongs to the region that holds most of its length.

Usage: python3 -I pipeline/cai_coverage.py work/osm/italy-latest.osm.pbf work/osm/regions \
           work/osm/italy.poly reports/cai-coverage.csv work/cai-coverage-relations.csv
Data © OpenStreetMap contributors, ODbL.
"""
import csv
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import osmium
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

MAX_GAP_M = 30.0
BORDER_M = 1000.0
MAIN_ROLES = {"", "main", "forward", "backward"}
CAI_OPERATOR = re.compile(r"\bCAI\b|club alpino italiano", re.IGNORECASE)
CLASSES = ["valid_in_order", "valid_reordered", "branched", "broken", "incomplete", "container"]


def haversine(a, b) -> float:
    r = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def length_m(line) -> float:
    return sum(haversine(a, b) for a, b in zip(line, line[1:]))


def read_poly(path: Path):
    """Area of an osmosis .poly file: every ring, islands included; rings named with a leading
    '!' are holes."""
    lines = [line.strip() for line in path.read_text().splitlines()[1:]]
    outer, holes = [], []
    i = 0
    while i < len(lines) and lines[i] != "END":
        name, coords = lines[i], []
        i += 1
        while lines[i] != "END":
            lon, lat = map(float, lines[i].split())
            coords.append((lon, lat))
            i += 1
        i += 1
        (holes if name.startswith("!") else outer).append(Polygon(coords).buffer(0))
    return unary_union(outer).difference(unary_union(holes)) if holes else unary_union(outer)


def stitch_in_order(ways) -> bool:
    """True if the ways, in member order, join into one line (same rule as reference_routes.py)."""
    line = list(ways[0])
    if len(ways) > 1:
        nxt = ways[1]
        if min(haversine(line[0], nxt[0]), haversine(line[0], nxt[-1])) < min(
            haversine(line[-1], nxt[0]), haversine(line[-1], nxt[-1])
        ):
            line.reverse()
    for way in ways[1:]:
        d_start, d_end = haversine(line[-1], way[0]), haversine(line[-1], way[-1])
        if min(d_start, d_end) > MAX_GAP_M:
            return False
        line.extend(way if d_start <= d_end else list(reversed(way)))
    return True


def classify_graph(ways) -> str:
    """Ways as edges between endpoints merged within MAX_GAP_M: one component with at most two
    odd vertices can be walked as a single line; more odd vertices mean branches."""
    ends = []
    for w in ways:
        ends += [w[0], w[-1]]
    parent = list(range(len(ends)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            if haversine(ends[i], ends[j]) <= MAX_GAP_M:
                parent[find(i)] = find(j)
    degree = Counter()
    edges = []
    for k in range(len(ways)):
        a, b = find(2 * k), find(2 * k + 1)
        degree[a] += 1
        degree[b] += 1
        edges.append((a, b))
    # Components over the merged endpoints.
    comp = {v: v for v in degree}

    def cfind(v):
        while comp[v] != v:
            comp[v] = comp[comp[v]]
            v = comp[v]
        return v

    for a, b in edges:
        comp[cfind(a)] = cfind(b)
    if len({cfind(v) for v in degree}) > 1:
        return "broken"
    odd = sum(1 for d in degree.values() if d % 2)
    return "valid_reordered" if odd <= 2 else "branched"


def main(pbf: str, regions_dir: str, italy_poly: str, report_csv: str, relations_csv: str) -> None:
    t0 = time.time()
    # 1. Hiking relations.
    relations = {}
    for r in osmium.FileProcessor(pbf, osmium.osm.RELATION).with_filter(osmium.filter.TagFilter(("route", "hiking"))):
        relations[r.id] = {
            "name": r.tags.get("name", ""),
            "ref": r.tags.get("ref", ""),
            "cai_scale": r.tags.get("cai_scale", ""),
            "cai_operator": bool(CAI_OPERATOR.search(r.tags.get("operator", ""))),
            "main": [m.ref for m in r.members if m.type == "w" and m.role in MAIN_ROLES],
            "has_sub": any(m.type == "r" for m in r.members),
        }
    print(f"{len(relations)} hiking relations ({time.time() - t0:.0f} s)", file=sys.stderr)

    # 2. Their main ways, with node locations.
    wanted = {w for rel in relations.values() for w in rel["main"]}
    geom = {}
    proc = (
        osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations("sparse_mem_array")
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.IdFilter(wanted).enable_for(osmium.osm.WAY))
    )
    for w in proc:
        pts = [(n.lat, n.lon) for n in w.nodes if n.location.valid()]
        if len(pts) >= 2:
            geom[w.id] = pts
    print(f"{len(geom)} of {len(wanted)} ways found ({time.time() - t0:.0f} s)", file=sys.stderr)

    # 3. Regions and border.
    names = sorted(p.stem for p in Path(regions_dir).glob("*.poly"))
    polys = [read_poly(Path(regions_dir) / f"{n}.poly") for n in names]
    tree = STRtree(polys)
    prepared = [prep(p) for p in polys]
    # ~1 km in degrees at Italian latitudes, good enough for a "near the border" flag.
    border = prep(read_poly(Path(italy_poly)).boundary.buffer(BORDER_M / 111000.0))

    def region_of(ways) -> str:
        weight = defaultdict(float)
        for w in ways:
            mid = w[len(w) // 2]
            pt = Point(mid[1], mid[0])
            for i in tree.query(pt):
                if prepared[i].contains(pt):
                    weight[names[i]] += length_m(w)
                    break
        return max(weight, key=weight.get) if weight else "outside"

    # 4. Classification.
    rows = []
    for rid, rel in relations.items():
        ways = [geom[w] for w in rel["main"] if w in geom]
        missing = len(rel["main"]) - len(ways)
        if not rel["main"]:
            cls = "container" if rel["has_sub"] else "incomplete"
        elif missing:
            cls = "incomplete"
        elif stitch_in_order(ways):
            cls = "valid_in_order"
        else:
            cls = classify_graph(ways)
        near_border = cls == "incomplete" and any(
            border.intersects(LineString([(p[1], p[0]) for p in w])) for w in ways
        )
        rows.append({
            "id": rid,
            "region": region_of(ways) if ways else "unknown",
            "class": cls,
            "near_border": near_border,
            "cai_scale": rel["cai_scale"],
            "cai_operator": rel["cai_operator"],
            "ref": rel["ref"],
            "name": rel["name"],
            "km": round(sum(length_m(w) for w in ways) / 1000.0, 2),
        })
    print(f"classified ({time.time() - t0:.0f} s)", file=sys.stderr)

    with open(relations_csv, "w", newline="", encoding="utf-8") as f:
        out = csv.DictWriter(f, fieldnames=list(rows[0]))
        out.writeheader()
        out.writerows(sorted(rows, key=lambda r: (r["region"], r["id"])))

    # 5. Report per region, plus Italy.
    def summary(name, group):
        total = len(group)
        routes = [r for r in group if r["class"] != "container"]
        valid = [r for r in routes if r["class"] in ("valid_in_order", "valid_reordered")]
        c = Counter(r["class"] for r in group)
        return {
            "region": name,
            "relations": total,
            "with_cai_scale": sum(1 for r in group if r["cai_scale"]),
            "cai_operator": sum(1 for r in group if r["cai_operator"]),
            **{k: c[k] for k in CLASSES},
            "incomplete_near_border": sum(1 for r in group if r["near_border"]),
            "valid_pct": round(100.0 * len(valid) / len(routes), 1) if routes else 0.0,
            "valid_km": round(sum(r["km"] for r in valid)),
        }

    by_region = defaultdict(list)
    for r in rows:
        by_region[r["region"]].append(r)
    report = [summary(n, by_region[n]) for n in sorted(by_region)]
    italy = [r for r in rows if r["region"] not in ("outside", "unknown")]
    report.append(summary("ITALY", italy))
    Path(report_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(report_csv, "w", newline="", encoding="utf-8") as f:
        out = csv.DictWriter(f, fieldnames=list(report[0]))
        out.writeheader()
        out.writerows(report)
    print(f"done ({time.time() - t0:.0f} s)", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:6])

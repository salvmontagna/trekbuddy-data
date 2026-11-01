#!/usr/bin/env python3
"""Copy hiking-route information from relations onto their ways before the Valhalla build.

Valhalla ignores route=hiking relations and reads difficulty only from the way's sac_scale,
so the CAI data has to be moved onto the ways. The rules are documented in docs/preprocessing.md.

Usage: preprocess_osm.py <input.osm.pbf> <output.osm.pbf> <report.json>
"""
import json
import sys
from collections import Counter

import osmium

# CAI difficulty -> sac_scale. EEA also covers the via ferrata grades (EEA:F, EEA:PD, ...).
CAI_TO_SAC = {
    "T": "hiking",                     # T1
    "E": "mountain_hiking",            # T2
    "EE": "demanding_mountain_hiking",  # T3
    "EEA": "demanding_alpine_hiking",  # T5
}
SAC_LEVEL = {
    "hiking": 1,
    "mountain_hiking": 2,
    "demanding_mountain_hiking": 3,
    "alpine_hiking": 4,
    "demanding_alpine_hiking": 5,
    "difficult_alpine_hiking": 6,
}
# Only footpaths get the relation's difficulty: a relation's cai_scale is the grade of its
# hardest section, so applying it to the roads and tracks it follows would block easy routes.
FOOTPATHS = {"path", "footway", "steps"}


def cai_to_sac(value, unknown):
    """Hardest sac_scale among the values of a cai_scale tag ("E;EE" -> EE), or None."""
    best = None
    for part in value.split(";"):
        grade = part.strip().upper().split(":")[0]
        sac = CAI_TO_SAC.get(grade)
        if sac is None:
            unknown[part.strip()] += 1
        elif best is None or SAC_LEVEL[sac] > SAC_LEVEL[best]:
            best = sac
    return best


def main(src, dst, report_path):
    unknown = Counter()
    in_hiking_route = set()  # way ids that belong to any route=hiking relation
    cai_sac = {}             # way id -> hardest sac_scale among its CAI relations

    for rel in osmium.FileProcessor(src, osmium.osm.RELATION):
        if rel.tags.get("route") != "hiking":
            continue
        sac = cai_to_sac(rel.tags["cai_scale"], unknown) if "cai_scale" in rel.tags else None
        for m in rel.members:
            if m.type != "w":
                continue
            in_hiking_route.add(m.ref)
            if sac and (m.ref not in cai_sac or SAC_LEVEL[sac] > SAC_LEVEL[cai_sac[m.ref]]):
                cai_sac[m.ref] = sac

    added = Counter()
    conflicts = Counter()
    to_footway = 0
    with osmium.SimpleWriter(dst, overwrite=True) as writer:
        for obj in osmium.FileProcessor(src):
            if not obj.is_way() or obj.id not in in_hiking_route:
                writer.add(obj)
                continue
            tags = dict(obj.tags)
            highway = tags.get("highway")
            sac = cai_sac.get(obj.id)
            if highway in FOOTPATHS and sac:
                if "sac_scale" not in tags:
                    tags["sac_scale"] = sac
                    added[sac] += 1
                elif tags["sac_scale"] != sac:
                    conflicts[f"{tags['sac_scale']} (way) vs {sac} (cai_scale)"] += 1
            # Valhalla's pedestrian costing can favour footways (walkway_factor) but has no
            # notion of marked trails, so marked paths become footways in the build input.
            if highway == "path":
                tags["highway"] = "footway"
                to_footway += 1
            writer.add(obj.replace(tags=tags))

    report = {
        "ways_in_hiking_relations": len(in_hiking_route),
        "ways_with_cai_scale": len(cai_sac),
        "sac_scale_added": dict(added.most_common()),
        "path_to_footway": to_footway,
        "sac_scale_conflicts": dict(conflicts.most_common()),
        "unknown_cai_scale_values": dict(unknown.most_common()),
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])

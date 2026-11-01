# OSM preprocessing for the routing graph

The routing graph (`routing.tar`) is built with Valhalla from OpenStreetMap data. Before the build, `pipeline/preprocess_osm.py` changes some way tags in the build input. The original extracts are not modified, and the changed data is distributed under the ODbL like the rest of the graph. This page lists every change.

## Why
Valhalla 3.9.1 ignores `route=hiking` relations: it only processes bicycle and mountain-bike route relations. Hiking difficulty is read only from the `sac_scale` tag of each way. The Italian CAI network records difficulty on the route relation (`cai_scale`), so without preprocessing that information never reaches the graph.

## Rules

### 1. `cai_scale` → `sac_scale`
Applies to ways with `highway=path`, `footway` or `steps` that belong to a `route=hiking` relation with a `cai_scale` tag, **only when the way has no `sac_scale`**. An existing `sac_scale` always wins, because it describes that way rather than the whole route.

| `cai_scale` | `sac_scale` | SAC grade |
|---|---|---|
| T | `hiking` | T1 |
| E | `mountain_hiking` | T2 |
| EE | `demanding_mountain_hiking` | T3 |
| EEA, EEA:F, EEA:PD, EEA:D, EEA:MD | `demanding_alpine_hiking` | T5 |

- When a way belongs to several relations, or the value lists several grades (`E;EE`), the hardest grade is used.
- Roads and tracks are not changed: a relation's `cai_scale` is the grade of its hardest section, so applying it to the roads and tracks the route follows would wrongly exclude easy sections.

### 2. Marked trails: `highway=path` → `highway=footway`
Applies to every way with `highway=path` that belongs to any `route=hiking` relation. Valhalla's pedestrian costing cannot tell marked trails apart, but it can weight footways (`walkway_factor`). Retagging lets the app prefer waymarked trails over unmarked paths. No other tag of the way changes.

## Report
Each build writes `work/osm/preprocess-report.json` with the number of ways changed by each rule, the `cai_scale` values that were not recognised, and the conflicts between a way's `sac_scale` and its relation's `cai_scale`. Conflicts are only reported: the way's own tag is kept.

Build of 31 October 2026 (central-eastern Alps and Gran Sasso):

| | Ways |
|---|---|
| In `route=hiking` relations | 102,890 |
| In relations with `cai_scale` | 41,654 |
| `sac_scale` added | 6,650 (T1 552 · T2 4,941 · T3 1,019 · T5 138) |
| `path` → `footway` | 32,361 |
| `sac_scale` different from `cai_scale` (kept) | 5,837, mostly a way easier than its route's hardest section |
| Unrecognised `cai_scale` values | 0 |

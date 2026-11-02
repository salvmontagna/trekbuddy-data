# trekbuddy-data

Pipeline and recipes that build the offline data for the **Trekbuddy** app (base map, hiking overlay, contour lines, elevation, routing). The data ships as per-cell packages in this repository's releases.

## Layout

| Folder | Contents |
|---|---|
| `pipeline/` | Build scripts: OSM extracts, preprocessing, Planetiler, Valhalla, DEM, cell cutting, manifest |
| `profiles/` | Planetiler `trek` profile, Valhalla costing configuration |
| `reference/` | Reference routes (GPX) used to measure routing quality |

## Cells
A cell is one zoom-level-9 tile (about 55 × 55 km at Italian latitudes). For each cell a release contains `base.pmtiles`, `trek.pmtiles`, `dem.pmtiles`, `routing.tar` and `index.sqlite`, plus a `manifest.json` with file sizes and SHA-256 hashes.

## Building
Run from the repository root with bash (Git Bash on Windows). Inputs and outputs go to `work/` (not versioned). A full build of the 169 cells takes about 2–3 hours on a 12-thread PC.

| Step | Command | Needs |
|---|---|---|
| Cells of the coverage, release groups, needed Geofabrik extracts (`coverage/cells.csv`, `cells.geojson`, `area.geojson`) | `python3 pipeline/coverage.py work/osm/regions work/osm/italy.poly work/osm/neighbours coverage` | openstreetmap.fr region `.poly` files, Geofabrik `italy.poly` + `alps`, `slovenia`, `croatia`, `france/corse` `.poly` in `work/osm/neighbours`, venv |
| Hiking relations usable as one track, per region (`reports/cai-coverage.csv`) | `python3 pipeline/cai_coverage.py work/osm/italy-latest.osm.pbf work/osm/regions work/osm/italy.poly reports/cai-coverage.csv work/cai-coverage-relations.csv` | Geofabrik `italy-latest.osm.pbf` + `.poly`, openstreetmap.fr region `.poly` files, venv |
| OSM input: Geofabrik extracts of one date, merged, clipped to the cells, preprocessed | `pipeline/build_osm.sh 261101` | `osmium-tool` (`OSMIUM`), venv |
| Valhalla graph of the whole coverage | `pipeline/build_routing.sh` | pyvalhalla in the venv |
| `base.pmtiles` (whole coverage, cut per cell), `dem.pmtiles`, contour lines, `trek.pmtiles`; `work/planetiler/overview.pmtiles` (base zooms 0-8, whole coverage) | `pipeline/build_tiles.sh` (all cells) or `pipeline/build_tiles.sh 272/180 …` | Java 25 (`JAVA`), `work/planetiler/planetiler.jar` (Planetiler 0.10.2), `pmtiles` CLI, venv |
| `index.sqlite` per cell: offline search (FTS5) and the hiking route catalogue, keyed by `relation_id` like `trek.pmtiles` | `python3 -I pipeline/build_index.py work/osm/build.osm.pbf coverage/cells.csv work/cells` (all built cells) or `… 9-272-182 …` | venv, `pmtiles` CLI (reads the cells' `dem.pmtiles`) |
| `routing.tar` + `routing.tar.gz` per cell | `python3 -I pipeline/pack_cells.py work/valhalla/tiles work/cells 272/180 …` | |
| `work/trek-online.pmtiles`: the `trek.pmtiles` of all the cells in one file, read by the app over the network where a cell is not downloaded | `python3 -I pipeline/merge_pmtiles.py work/cells trek.pmtiles work/trek-online.pmtiles` | venv |
| Release folders per group (`<cell>_<file>` + `manifest.json`), `overview/overview.pmtiles`, `trek-online/trek-online.pmtiles` and `releases.json` | `python3 -I pipeline/make_manifest.py work/cells coverage/cells.csv <version> work/release work/planetiler/overview.pmtiles work/trek-online.pmtiles` | |

Environment: `OSMIUM` and `JAVA` default to `osmium` and `java` on the `PATH`; `JOBS` (default 3) sets how many cells `build_tiles.sh` builds at once; `VALHALLA_THREADS` (default 4) and `VALHALLA_ENHANCE_THREADS` set the Valhalla threads. The venv is `work/.venv` with `pipeline/requirements.txt`.

On Windows:
- `osmium-tool` comes from conda-forge: `micromamba create -p work/osmium-env -c conda-forge osmium-tool`, then `OSMIUM=work/osmium-env/Library/bin/osmium.exe`;
- the `pmtiles` CLI (Windows build of go-pmtiles) can sit in `work/bin`;
- Valhalla runs from the pyvalhalla wheel; its enhance stage runs on one thread, because with more threads it stops (pyvalhalla 3.9.1).

`dem.pmtiles` is extracted from the [Mapterhorn](https://mapterhorn.com) planet file (terrarium, zooms 9–12). `base.pmtiles` uses Planetiler's built-in OpenMapTiles profile; `trek.pmtiles` uses [`profiles/TrekProfile.java`](profiles/TrekProfile.java) (layers `hiking_route`, `trail`, `mountain_poi`, `contour`), with contour lines traced from the DEM by `pipeline/contours.py`.

## Data licenses

| Source | License | Attribution |
|---|---|---|
| OpenStreetMap | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | © OpenStreetMap contributors — https://www.openstreetmap.org/copyright |
| OpenMapTiles schema | CC-BY 4.0 | © OpenMapTiles |
| Natural Earth (low zoom base map) | Public domain | Made with Natural Earth |
| Copernicus DEM GLO-30 | Copernicus DEM license | produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved |
| DEM sources via Mapterhorn | CC BY 4.0 / CC BY 2.5 / CC0 (per source) | Full list in each release (`attribution.json`) |

Tile packages and routing graphs are derived from OpenStreetMap and distributed under the **ODbL**. This repository publishes the complete recipe to rebuild them, including the tag changes made during preprocessing ([docs/preprocessing.md](docs/preprocessing.md)).

## Code license
The scripts in this repository are released under the [MIT license](LICENSE). The data they produce is covered by the data licenses above.

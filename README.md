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
Run from the repository root. Inputs and outputs go to `work/` (not versioned).

| Step | Command | Needs |
|---|---|---|
| OSM extracts, preprocessing, routing graph | `pipeline/build_routing.sh` | `osmium-tool`, venv with `pipeline/requirements.txt` in `work/.venv` |
| `routing.tar` per cell | `python3 pipeline/pack_cells.py work/valhalla/tiles work/cells 272/180 …` | |
| `dem.pmtiles`, contour lines, `base.pmtiles`, `trek.pmtiles` per cell | `pipeline/build_tiles.sh 272/180 …` | Java 25, `work/planetiler/planetiler.jar` (Planetiler 0.10.2), `pmtiles` CLI, venv |

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

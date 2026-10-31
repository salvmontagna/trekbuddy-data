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

## Data licenses

| Source | License | Attribution |
|---|---|---|
| OpenStreetMap | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | © OpenStreetMap contributors — https://www.openstreetmap.org/copyright |
| OpenMapTiles schema | CC-BY 4.0 | © OpenMapTiles |
| Copernicus DEM GLO-30 | Copernicus DEM license | produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved |
| DEM sources via Mapterhorn | CC BY 4.0 / CC BY 2.5 / CC0 (per source) | Full list in each release (`attribution.json`) |

Tile packages and routing graphs are derived from OpenStreetMap and distributed under the **ODbL**. This repository publishes the complete recipe to rebuild them, including the tag changes made during preprocessing.

## Code license
The scripts in this repository are released under the [MIT license](LICENSE). The data they produce is covered by the data licenses above.

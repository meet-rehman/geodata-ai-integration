# Data sources

Credit on every image and publication that uses this data:

**Datenquelle: LGL, www.lgl-bw.de**

## LoD2 3D building models (Landesamt für Geoinformation und Landentwicklung Baden-Württemberg)

| Tile | Area (EPSG:25832) | Buildings | In project | Used for |
|---|---|---|---|---|
| `LoD2_32_511_5406_2_bw` | E 511000–513000, N 5406000–5408000 | 4,768 | `data/lod2/` | Not used in this study |
| `LoD2_32_511_5404_2_bw` | E 511000–513000, N 5404000–5406000 | 5,487 | `data/lod2/` | Weissenhofsiedlung (west part) |
| `LoD2_32_513_5404_2_bw` | E 513000–515000, N 5404000–5406000 | 2,596 | `data/lod2/` | Weissenhofsiedlung (east part) |

- Format: CityGML 1.0, four 1 × 1 km files per 2 × 2 km tile
- Coordinate system: ETRS89 / UTM zone 32N (EPSG:25832), heights DHHN2016 normal heights
  (m above sea level), `urn:adv:crs:ETRS89_UTM32*DE_DHHN2016_NH`
- Currency (from the tile's INFO file): building footprints ALKIS 2025-04-01,
  ATKIS structures 2025-09-22; terrain and surface models 2000–2025; read out 2026-02
- Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0
  (`GOVDATA-Datenlizenz_Deutschland.pdf` in the tile folder)

Note: the download folder is called "Am Weißenhof", but `LoD2_32_511_5406_2_bw` does
**not** contain the Weissenhofsiedlung. The estate straddles the E 513000 line between
`511_5404` and `513_5404`.

### Used in

- `renders/lod2_weissenhof_overview.png`, `models/lod2_weissenhof.blend` (made by
  `scripts/import_lod2.py`): 73 buildings whose footprint lies within 150 m of
  E 513025.2, N 5405261.3, the midpoint of Am Weißenhof 14–20 and Rathenaustraße 1–3.
  The credit is burned into the image.
- Terrain in that scene: **LGL DGM1** (below), on a disc of radius 180 m, at the full 1 m
  resolution, shifted to the same local origin as the buildings (E 513025.2,
  N 5405261.3, H 298.78 m). If DGM1 is missing, `import_lod2.py` falls back to a terrain
  estimated from LoD2 ground heights and labels the render accordingly.
- Check of the two datasets against each other: each building's LoD2 ground height differs
  from the DGM1 at the same points by 0.39 m (median), 1.69 m (90th percentile), 7.16 m
  (max). The larger gaps are expected on the slope, where a building's ground height is a
  single reference value while the real ground falls away along its walls.

## DGM1 digital terrain model (LGL)

| Tile | Area (EPSG:25832) | In project | Used for |
|---|---|---|---|
| `dgm1_32_511_5404_2_bw` | E 511000–513000, N 5404000–5406000 | `data/dgm1/` | Weissenhofsiedlung terrain (west part) |
| `dgm1_32_513_5404_2_bw` | E 513000–515000, N 5404000–5406000 | `data/dgm1/` | Weissenhofsiedlung terrain (east part) |

- Format: XYZ text, 1 m grid (cell centres at .5 m), four 1 × 1 km files per 2 × 2 km tile
- Coordinate system: ETRS89 / UTM 32N, heights DHHN2016 normal heights (same as LoD2)
- From the per-file CSV for the two files used (`512_5405`, `513_5405`): stated height
  accuracy 0.15 m; captured 2016-04-05 and 2016-04-06, updated 2023-02-11. The metadata
  file name (`Meta-ATKIS_DGM1_ALS2`) indicates airborne laser scanning.
- Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0; same credit as LoD2

## DOP20 digital orthophoto (LGL)

| Tile | Area (EPSG:25832) | In project | 1 km files used |
|---|---|---|---|
| `dop20rgb_32_511_5404_2_bw` | E 511000–513000, N 5404000–5406000 | `data/dop20/` (zip + extracted file) | `512_5405` |
| `dop20rgb_32_513_5404_2_bw` | E 513000–515000, N 5404000–5406000 | `data/dop20/` (zip + extracted file) | `513_5405` |

- Format: GeoTIFF without embedded georeferencing + `.tfw` world file, RGB 8 bit, 20 cm pixels,
  5000 × 5000 px per 1 km file; only the two files covering the area were extracted
- Coordinate system: ETRS89 / UTM 32N (EPSG:25832); heights DHHN2016 (EPSG:7837)
- From the per-file CSV: `Aktualitaet` **2025-11-08**, flight no. 720, camera UltraCam Eagle M3,
  projection surface `bDOM` (image-based surface model, so roofs are shown in their true
  position), `Standardabweichung` 40, `Belaubungszustand` 3
- **Capture date caveat:** the image is clearly leaf-on summer imagery (full foliage, green lawns),
  so 2025-11-08 is probably the processing/release date rather than the flight date. Check the
  exact flight date in the LGL metadata record linked in `Meta-ATKIS_DOP20.txt`.
- Derived file: `data/dop20/dop20_weissenhof_crop.png` (1850 × 1850 px, upper-left corner
  E 512840.2, N 5405446.3, 0.2 m/px), made by `scripts/render_dop20.py`
- Used in `renders/dop20_*.png`, `models/lod2_weissenhof_dop20.blend`; findings in
  `notes/dop20_findings.md`
- Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0; credit
  **Datenquelle: LGL, www.lgl-bw.de** (burned into every render)

## ALKIS cadastre (LGL), Stuttgart

- File: `data/ALKIS.zip` → `ALKIS-oE_081460_Stuttgart_nas.xml` (1.72 GB, NAS 7.1, without owner
  data), created 2026-07-10, data current 3–10 July 2026; ETRS89 / UTM 32N (EPSG:25832)
- Extracted around the Weissenhofsiedlung by `scripts/extract_alkis.py` (streams the zip, no
  unpacking) into `data/alkis/`: 181 parcels (`AX_Flurstueck`), 224 buildings (`AX_Gebaeude`,
  the source of the Hausumringe product) and 5 other structures
  (`AX_SonstigesBauwerkOderSonstigeEinrichtung`)
- Used by `scripts/compare_alkis_lod2.py` → `notes/alkis_lod2_comparison.md`,
  `renders/alkis_lod2_aerial.png`, `renders/alkis_lod2_plan.png`
- Licence: Datenlizenz Deutschland – Namensnennung – Version 2.0; same credit as above

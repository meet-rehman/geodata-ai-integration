# LoD2 footprints vs. ALKIS building outlines – Weissenhofsiedlung

Area: buildings within 150 m of E 513025.2, N 5405261.3 (EPSG:25832). Made by `scripts/compare_alkis_lod2.py`.

## Result

- **Geometry:** the 73 matched outlines differ by at most **0.034 m** (median 0.000 m); every overlap is ≥ 99.9 %. 0 buildings deviate by more than 0.30 m.
- **Completeness:** all 69 official ALKIS buildings in the area have a LoD2 building (matched 1:1 by object ID); 0 are missing from LoD2.
- **Classification:** 4 LoD2 "buildings" are canopies that ALKIS records as structures, not buildings, so they are not part of the Hausumringe. Their outlines match.
- **Currency:** the newest ALKIS building version in the area is 2025-03-27, before the LoD2 footprint date (2025-04-01). The 15-month age difference between the datasets made no difference here.

**What this means:** LoD2 footprints are produced *from* ALKIS, so this comparison checks how faithfully they were transferred, not how accurate either is against the real buildings. Here the transfer is exact. Real-world deviations (roof overhangs, extensions not yet in the cadastre, roof heights and forms) need an independent source such as the LGL digital surface model (DOM) or orthophotos.

## Data

- **LoD2**: footprints (ground surfaces) of the LGL LoD2 buildings. Per the LoD2 INFO file they were taken from ALKIS dated **2025-04-01**.
- **ALKIS**: `AX_Gebaeude` outlines (the source of LGL's Hausumringe) and `AX_Flurstueck` parcels (89 in the area) from `data/ALKIS.zip`, current as of **July 2026**.
- Matching: LoD2 object IDs are the ALKIS object IDs with `L` replaced by `_`; where no ID matches, buildings are paired by overlap.

## Classification

| Status | Rule | Buildings |
|---|---|---|
| Aligned | largest gap between outlines ≤ 0.30 m and overlap ≥ 97 % | 69 |
| Minor deviation | gap ≤ 1.0 m and overlap ≥ 90% | 0 |
| Misaligned | gap > 1.0 m or overlap < 90% | 0 |
| ALKIS structure, not a building | LoD2 models it as a building; ALKIS has it as `AX_SonstigesBauwerkOderSonstigeEinrichtung`, so it is not in the Hausumringe | 4 |
| Only in ALKIS | official building with no LoD2 building | 0 |
| Only in LoD2 | LoD2 building with nothing in ALKIS | 0 |

Gap = Hausdorff distance between the two outlines (the largest distance from any point on one outline to the nearest point on the other). Overlap = intersection / union (IoU).
LoD2 buildings made of several parts are joined into one footprint first; hairline gaps (< 10 cm) between parts are closed so they do not count as deviations.

ALKIS function codes seen: building `gebaeudefunktion` and structure `bauwerksfunktion`; structure code 1610 is *Überdachung* (canopy) in the ALKIS code list.

0 of the 4 flagged buildings have an ALKIS object version newer than 2025-04-01, i.e. the cadastre changed after the LoD2 footprints were taken.

## Flagged buildings

Numbers match the flags in `renders/alkis_lod2_plan.png`.

| # | Status | Address | ALKIS object (function) | Max gap (m) | Overlap | LoD2 area (m²) | ALKIS area (m²) | ALKIS version | LoD2 ID |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ALKIS structure, not a building | – | AX_SonstigesBauwerk (1610) | 0.00 | 100% | 2.5 | 2.5 | 2011-12-04 | `DEBW_5221000BwiZ` |
| 2 | ALKIS structure, not a building | – | AX_SonstigesBauwerk (1610) | 0.00 | 100% | 8.4 | 8.4 | 2011-12-04 | `DEBW_5221000Bwby` |
| 3 | ALKIS structure, not a building | – | AX_SonstigesBauwerk (1610) | 0.00 | 100% | 2.9 | 2.9 | 2011-12-04 | `DEBW_5221000BwiO` |
| 4 | ALKIS structure, not a building | – | AX_SonstigesBauwerk (1610) | 0.00 | 100% | 9.1 | 9.1 | 2011-12-04 | `DEBW_5221000Bwhn` |

All buildings with their metrics: `data/alkis/comparison_weissenhof.csv`.

Datenquelle: LGL, www.lgl-bw.de

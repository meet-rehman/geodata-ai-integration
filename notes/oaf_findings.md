# LGL OGC API – Features (beta) vs. our ALKIS download

**Tested:** 2026-10-04, against `https://ogcapi.lgl-bw.de/beta/pygeoapi`
("LGL OGC API – Features POC", pygeoapi, ALKIS/ATKIS data from NOrA-BW). Read-only (GET requests only).
**Ground truth:** our extract from `data/ALKIS.zip` (NAS, data current 3–10 July 2026), in `data/alkis/`.
**Script:** `scripts/test_oaf.py`. API responses and the request log are saved in `data/oaf/`; no downloaded
data was replaced.

## 1. Service capabilities

- **16 collections:** `flurstueck`, `gebaeude`, `gemarkung`, `flur`, five kinds of survey points
  (`grenzpunkt`, `aufnahmepunkte`, …), and ATKIS administrative units (`bundesland` … `gemeinde`).
  There is no collection for other structures (`AX_SonstigesBauwerkOderSonstigeEinrichtung`).
- **Conformance:** OGC API Features Part 1 (core, GeoJSON, HTML, OpenAPI), Part 2 (CRS), Part 3
  (queryables, queryables as query parameters), CQL2 basic + text, and **Part 4
  (create/replace/delete)**. Write access is advertised; it was not tested.

| Query feature | Supported | Tested |
|---|---|---|
| `bbox` | yes | ✅ works |
| `bbox-crs` / `crs` (EPSG:25832, 4326, 3857, CRS84; storage CRS 25832) | yes | ✅ EPSG:25832 in and out, `Content-Crs` header set |
| CQL2 text `filter` | yes | ✅ `gebaeudefunktion_id=1010` and `gml_id IN (…)` work |
| Queryables as parameters | yes | ✅ `?gebaeudefunktion_id=1010` gives the same result as CQL2 |
| Paging | `limit` + `offset`, `next` links | ✅ default **10**, maximum **10,000** per page; **no `numberMatched`** (total unknown until the last page) |
| Output formats | GeoJSON, JSON-LD, HTML, CSV | GeoJSON used |

## 2. Schemas (= queryables)

- **`gebaeude`**: `gml_id`, `object_id` (UUID, also the feature `id`), `gebaeudefunktion_id` /
  `_kuerzel` / `_name`, `lage_id`, `adressen` (integer: number of addresses only, no street or
  house number), `hochhaus`, `lage_oberflaeche_id` / `_name`, `nutzung_id` / `_name`, `eigenname`,
  `qualitaet`, `beginn` (version start, no time zone). Geometry: MultiPolygon.
- **`flurstueck`**: `gml_id`, `flurstueckskennzeichen`, `gemarkung_id` / `_name`, `flurnummer`,
  `zaehler`, `nenner`, `folgenummer`, `flurstueckstext`, `amtliche_flaeche` (integer m²),
  `gemeinde_id` / `_name`, `ist_gebucht`, `anlass`, `fno_verfahren`, `vorgaenger`, `beginn`.
- Coordinates come with **2 decimals (cm)**; the NAS download has 3 (mm).

## 3. Buildings (`gebaeude`)

Query: `bbox` around the 150 m radius and around our 420 m extract square, `bbox-crs` and `crs`
EPSG:25832, GeoJSON. The 150 m bbox was also fetched with the default page size: 100 features in
11 pages of 10.

| Check | Result |
|---|---|
| Count, extract square | ours 224, API 224, no duplicates |
| IDs | **224 / 224 identical** (`gml_id`, e.g. `DEBWL52210005fd3`) |
| Within 150 m (the set used for the LoD2 comparison) | ours **69**, API **69**, same IDs |
| Footprint geometry | max gap **0.036 m**, median 0.000 m; overlap ≥ 99.3 %; max area difference 0.12 m² (cm rounding) |
| `gebaeudefunktion` | 0 mismatches |
| Version date (`beginn`) | within 150 m: **69 / 69 identical**; extract square: 223 / 224 identical. The one difference is `DEBWL52210004e9T` (Am Weißenhof 1/1, 163 m from the centre, outside the radius): download **2026-06-30**, API **2010-07-05** (see section 5) |
| **Canopies (code 1610)** | **Not present.** `gml_id IN (4 canopy IDs)` returns 0 features: the API has buildings only, no structures |

## 4. Parcels (`flurstueck`)

| Check | Result |
|---|---|
| Count | ours 181, API 181, no duplicates |
| IDs | **181 / 181 identical** |
| `amtliche_flaeche` (official area) | 0 mismatches |
| `beginn` | 0 mismatches |
| `flurstueckskennzeichen` | 22 differ **in format only**: an empty denominator is `____` in the NAS download and `0000` in the API (e.g. `08146000011677____00` vs. `08146000011677000000`) |
| Geometry | median gap 0.000 m; **3 parcels differ by up to 0.34 m** (17–26 m² area). They have curved boundaries, approximated with different numbers of points (e.g. ours 329, API 298). Neither version reproduces the official area exactly; official areas are not computed from UTM map coordinates |

## 5. Record currency (check of 2026-10-04, `scripts/check_currency.py`)

**Method.** Version start (`beginnt`) and version end (`endet`) were read straight from the NAS
file in `data/ALKIS.zip`, and `beginn` from the API (GET only). The NAS gives UTC timestamps with
`Z`, the API the same timestamps without a time zone. Treating the API's as UTC makes every
matching record agree to the second. Dates are reported in German local time, because ALKIS stores
local midnight as 23:00Z (winter) or 22:00Z (summer): `2010-07-04T22:00Z` is 5 July 2010.
Version end: the API has no such attribute, and none of the NAS objects in the area has an `endet`
(all are current versions). Per building: `data/oaf/currency_buildings.csv`.

| Set | Buildings | Identical version start | Different |
|---|---|---|---|
| Within 150 m (the LoD2 comparison set) | 69 | **69** | **0** |
| Extract square (420 m) | 224 | 223 | 1 (download newer by 5,839 days) |

Count by year of version start, within 150 m (download / API): 1997: 4/4, 2001: 47/47, 2002: 1/1,
2003: 1/1, 2004: 1/1, 2005: 1/1, 2008: 5/5, 2009: 2/2, 2011: 1/1, 2012: 1/1, 2021: 3/3, 2025: 2/2.
In the extract square the distributions are identical except 2010: 9/10 and 2026: 1/0 (the one
differing building).

**Which release our download is.** The NAS file was created on **10.07.2026** (header comment and
timestamp inside the zip). For the ID prefix of these objects (`DEBWL522`) the data is current as of
**03.07.2026**. It was downloaded on 03.10.2026 (file date). So it is the July 2026 snapshot, newer
than the portal update announced for 06.05.2026. The portal's metadata record doesn't identify
releases: its dates describe the dataset (metadata stamp 2025-03-04), and it states the update
frequency as weekly.

**How current the API is.** Its newest version dates are **2026-10-01**. The 10,000 most recently
changed buildings all date from 9 September to 1 October 2026, after our download. So the API is
updated, and overall it is *newer* than our July snapshot, not older. But it doesn't state its own
data date, and for the one building below it holds an older version than our download. **We can't
tell how old the API's data is for any particular object.**

**The one difference: Am Weißenhof 1/1 (`DEBWL52210004e9T`, 67 m², function 2081 "Gaststätte,
Restaurant"), the cleared site from the DOP20 comparison.** Yes, it is the same case:
- **Orthophoto (DOP20, 2025 flight):** bare earth, rubble and concrete pipes where the building
  stood.
- **LoD2 (footprints from ALKIS of 2025-04-01):** still contains it.
- **Download (NAS, 10.07.2026):** still contains it, as a current object whose version began on
  **30 June 2026**. Geometry and function are the same as in the API, so the June change isn't
  visible in the attributes we extracted.
- **API (queried 2026-10-04, data to 2026-10-01):** contains it with the version from
  **5 July 2010**.

None of the three sources removes the building the photo shows as gone. Why the API, though updated
since July, doesn't carry the June 2026 version can't be determined from the data.

### 5a. Attribute diff for Am Weißenhof 1/1 (`DEBWL52210004e9T`), 2026-10-04

Read-only. The raw NAS record is saved as `data/oaf/nas_DEBWL52210004e9T.xml`; the API record was
fetched by `gml_id` (CQL2) and by feature ID. The two API responses are identical (properties and
geometry), apart from `object_id` appearing as the feature ID in the single-item response.

| NAS element | NAS (download, 10.07.2026) | API field | API (2026-10-04) | Same? |
|---|---|---|---|---|
| `gml:id` | DEBWL52210004e9T | `gml_id` | DEBWL52210004e9T | ✅ |
| `lebenszeitintervall/beginnt` | **2026-06-30T08:06:19Z** | `beginn` | **2010-07-04T23:00:00** | ❌ |
| `lebenszeitintervall/endet` | absent | – | no such field | – |
| `anlass` (reason for change) | absent on the building | – | no such field | – |
| `modellart` | DLKM | – | no such field | – |
| `gebaeudefunktion` | 2081 | `gebaeudefunktion_id` / `_kuerzel` / `_name` | 2081 / Gast / Gaststätte, Restaurant | ✅ |
| `hochhaus` | false | `hochhaus` | false | ✅ |
| `zeigtAuf` (address) | → `DEBWL5221000452X` = Lagebezeichnung mit Hausnummer **1/1**, street key 02380 | `lage_id`, `adressen` | `08111000023800001001`, 1 | consistent (same street key, one address) |
| `hat` (pseudo-number address) | → `DEBWL52210004kjH` = Pseudonummer 1/1, laufende Nummer 2 | – | not in API | – |
| `position` (outline) | 8 vertices | `geometry` | 9 vertices | ❌ one extra vertex in the API |
| `zustand`, `lageZurErdoberflaeche`, `name`, storeys, roof, year built | absent | `nutzung_*`, `lage_oberflaeche_*`, `eigenname`, `qualitaet` | all null | both empty |
| – | – | `object_id` | a6a6c978-4ed0-436c-b5b7-f0b678885dea | API only |

**Geometry difference.** The API outline has one extra vertex on the north edge,
(512868.52, 5405201.54). It lies on the straight line between its neighbours (512870.71, 5405201.67)
and (512864.18, 5405201.28), within 1 mm. All other 8 vertices are identical, so shape and area are
unchanged. The June 2026 version in the download does not have this vertex.

**Other objects with a version start of 30 June 2026.** In the whole Stuttgart file there are
exactly 7, all with the same timestamp, 2026-06-30T08:06:19Z: this building and 6 address objects
on street key 02380. None has a geometry. Every one of them belongs to the cleared site:

| Address object | Type | Used by (version start of the user) |
|---|---|---|
| `DEBWL5221000452X` | Hausnummer 1/1 | building `e9T` (`zeigtAuf`, 2026-06-30); parcel `DEBWL522os0000Bp` (`weistAuf`, 2025-09-12) |
| `DEBWL52210004SRq` | Hausnummer 1/2 | building `DEBWL52210005g4R` (function 2523, 13 m², 2010-07-04); same parcel |
| `DEBWL52210004kjH` | Pseudonummer 1/1, no. 2 | building `e9T` (`hat`) |
| `DEBWL52210005845` | Pseudonummer 1/2, no. 2 | building `g4R` (`hat`) |
| `DEBWL52210004tj8` | Pseudonummer 1/2, no. 4 | building `DEBWL52210004HJU` (function 2140, 3.7 m², 2010-07-04) |
| `DEBWL52210004aBF` | Pseudonummer 1/2, no. 5 | building `DEBWL52210004efS` (function 2140, 8.9 m², 2010-07-04) |

All six address objects carry `anlass` = "Ersteinrichtung" (code 000000). No parcels or structures
in our extract have a 30 June 2026 version start. Each address also has a map label (`AP_PTO`) dated
2025-03-27. The API has no address objects, so it can't be compared for them.

**What the record shows and doesn't show:**
- **Shows:** on 30 June 2026 the building got a new version whose only visible difference from the
  API's 2010 version is the removed on-edge vertex. In the same operation (same second) all six
  addresses of the site's four small buildings got new versions. The other three buildings kept
  their 2010 versions.
- **Doesn't show:** no version end (`endet`), no state (`zustand`), no reason for the building's
  change, and no reference to a replacement object. Nothing in either record indicates demolition,
  a pending change or a replacement. The NAS file is an extract of current versions, so earlier
  versions and their reasons aren't included; the API exposes one version only.
- **Unresolved:** why the API, which holds changes up to 1 October 2026, serves the 2010 version
  of this building (while its parcel's 12 September 2025 version agrees between both sources).
  The data doesn't explain it, and the orthophoto's rubble isn't reflected in either source.

## 6. Performance, errors, limits (2026-10-04)

- 29 data requests (22 logged in `data/oaf/oaf_request_log.json`, 7 more in a follow-up check of
  paging), plus 8 metadata requests: **0 errors**, no HTTP 429, **no rate-limit headers** (only
  `Content-Type`, `Content-Crs`).
- Typical response 170–450 ms (median ≈ 210 ms); metadata 30–300 ms.
- Large pages: 1,000 features ≈ 1.0 s (2.4 MB), 4,277 ≈ 3.2 s (10.4 MB), 10,000 ≈ 7.4 s.
- Neither the API nor the collections state the **data date** (no temporal extent), and no licence or
  credit is shown in the JSON responses.

## 7. Verdict

**For small-area building and parcel geometry, yes; as a full replacement for the cadastre download, not yet.**

- **Works:** the same objects and IDs, footprints within a few centimetres, official areas
  identical; `bbox`, EPSG:25832, filters and paging all work. One request of ~0.3 s replaces
  streaming a 1.7 GB file for an area like ours.
- **Gaps:**
  - **Currency is unstated.** Version dates agree for all 69 buildings in the study area and for
    223 of 224 in the wider square, and the API holds changes up to 1 October 2026. But it doesn't
    publish a data date, and one object carries an older version than our July 2026 download, so
    we can't tell how current any particular record is.
  - **Content is thinner.** Only buildings, parcels and survey points: no structures (so the canopies
    found in the LoD2 comparison can't be checked), no address text, and fewer attributes.
  - **Status is a beta.** It's a proof of concept, with no stated service level, and it advertises
    write operations.
  - **Totals are unknown.** No `numberMatched`, so the size of a result is only known at the end.
- **Recommendation:** use the API for quick queries, prototyping and change checks (e.g. comparing
  `beginn` dates). Keep the NAS download as the dated, complete reference for the case study.

Datenquelle: LGL, www.lgl-bw.de

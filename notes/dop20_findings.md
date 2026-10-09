# DOP20 orthophoto vs. LoD2 – Weissenhofsiedlung

Made with `scripts/render_dop20.py`: the LGL DOP20 orthophoto (20 cm) draped over the DGM1 terrain,
same local origin as the LoD2 buildings (E 513025.2, N 5405261.3, H 298.78 m), LoD2 footprints drawn
as outlines. Every finding below was checked against LoD2 and the ALKIS extract, not just seen.

Renders: `renders/dop20_rathenau_comparison.png`, `renders/dop20_findings.png`,
`renders/dop20_overview_plan.png`, `renders/dop20_aerial.png`, `renders/dop20_scan_{nw,ne,sw,se}.png`.

## Main finding: Rathenaustraße 1–3 (Le Corbusier & Pierre Jeanneret double house)

| | LoD2 | Orthophoto |
|---|---|---|
| Main block (25 m along the street) | 4 pitched faces: 14° and 23° (no. 1), 27° and 32° (no. 3); two ridges across the block; slopes rise 2.3–3 m | Flat roof: a row of open bays bordered by light walls, each bay shaded on its west side (sun from the south-east). No ridge, no light/dark pair of roof faces |
| Two west wings | flat (16–17 m² each) | flat, evenly lit |
| roofType | 3100 (gable) + 1000 (flat), for both no. 1 and no. 3 | – |
| Footprint | matches ALKIS within 3 cm | east side: a light band ≈ 1 m wide runs outside the footprint along the whole street front |

**Verdict:** the orthophoto contradicts LoD2's gable roof and is consistent with a flat roof with a
walled roof terrace.

**Likely cause (interpretation, not verified):** LoD2 roofs are reconstructed automatically from
airborne laser points. The terrace walls stand 2–3 m above the roof slab, about the rise of the LoD2
slopes, and were probably fitted as gables.

**Limits of this check:** a single 20 cm orthophoto shows shape and shading, not heights or pitches.
To confirm, compare the LGL surface model (DOM) along a profile across the block, or use a site or
oblique photo. The ≈ 1 m east band could be a projecting upper floor or roof edge (the house stands
partly on pilotis); the photo alone can't show which.

**Relation to the ALKIS comparison:** it does not contradict it, it complements it. ALKIS and LoD2
agree on the footprint because LoD2 copies it from ALKIS. The roof is the part LoD2 adds on its own,
from laser data, and that is where the error is. The east band is a second, smaller hint that the
real building does not stop at the cadastral footprint.

## Other findings (numbers as in `renders/dop20_findings.png`)

| # | Where | What the photo shows | LoD2 / ALKIS | Confidence |
|---|---|---|---|---|
| 3 | Am Weißenhof 5 (138 m) | rows of rooflights across the whole roof | LoD2: 4 flat parts; rooftop structures are not modelled in LoD2 | high (visible); expected limitation |
| 4 | gardens south of Friedrich-Ebert-Straße (≈ 115–130 m) | several garden huts | no LoD2 or ALKIS building within 30–58 m | high |
| 5 | gardens south-east (≈ 110–140 m) | ≥ 6 garden houses, a greenhouse, sheds | no LoD2 or ALKIS building | high |
| 6 | outside 150 m (≈ 162 m W, Am Weißenhof 1/1, 1/2) | cleared site: bare earth, rubble, concrete pipe sections | LoD2 still has small buildings; ALKIS (July 2026) still has 4 small objects, one changed 2026-06-30 | high (visible); cause unknown |
| 7 | outside 150 m (≈ 164 m SE) | possible construction site beside a large building | not checked | low |

Garden houses are typically below the threshold for cadastral survey, so their absence from ALKIS
(and therefore LoD2) is expected, but it means LoD2 under-counts built structures in garden areas.

Seen on many roofs, not part of LoD2 by design: skylights, rooftop units, solar panels, green roofs.

Checked and consistent (no finding): Friedrich-Ebert-Straße 112 (photo: hip roof; LoD2: hip/shed
21–22°), Rathenaustraße 13 (flat), a white-rimmed structure ≈ 166 m N (an open basin or planter,
not a building).

Not seen within 150 m: buildings in the photo with no LoD2 footprint (other than garden houses), or
LoD2 footprints with no building in the photo.

Datenquelle: LGL, www.lgl-bw.de

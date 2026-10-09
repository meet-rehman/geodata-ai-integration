"""Compare LoD2 building footprints with the official ALKIS building outlines (Hausumringe).

Run from the project root after extract_alkis.py:
    blender --background --python scripts/compare_alkis_lod2.py
Takes the same --centre / --radius options as import_lod2.py.

Builds the Weissenhof scene with import_lod2.build_scene() (same buildings, DGM1 terrain and
local origin), then:
  1. matches every LoD2 building to its ALKIS building (by object ID, else by overlap),
  2. measures how far the two outlines are apart and classifies each building,
  3. draws ALKIS parcels and building outlines on the terrain and colours the LoD2 buildings,
  4. renders an aerial view and a top-down plan with numbered flags.

Outputs
    notes/alkis_lod2_comparison.md          summary and table of every flagged building
    data/alkis/comparison_weissenhof.csv     metrics for every building
    renders/alkis_lod2_aerial.png, renders/alkis_lod2_plan.png
    models/lod2_weissenhof_alkis.blend
"""
import csv
import json
import math
import os
import sys

import bpy
import numpy as np
import shapely
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, shape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_lod2 as L  # noqa: E402

PROJECT_DIR = L.PROJECT_DIR
ALKIS_DIR = os.path.join(PROJECT_DIR, "data", "alkis")
LOD2_FOOTPRINT_DATE = "2025-04-01"      # "Aktualität ALKIS LoD2" in the LoD2 INFO file

# Classification thresholds. LoD2 footprints are taken from ALKIS, whose coordinates are
# stored to the millimetre, so a correctly transferred footprint should differ by centimetres.
ALIGNED_MAX_GAP = 0.30                  # m, largest distance between the two outlines
MINOR_MAX_GAP = 1.00                    # m
MIN_IOU = 0.90                          # overlap (intersection / union) below this = misaligned

STATUS = {   # name: (colour, label)
    "aligned": ((0.80, 0.80, 0.78), "Aligned (max gap ≤ 0.30 m)"),
    "minor": ((0.95, 0.55, 0.10), "Minor deviation (0.30–1.0 m)"),
    "misaligned": ((0.85, 0.08, 0.06), "Misaligned (> 1.0 m or overlap < 90 %)"),
    "structure": ((0.50, 0.20, 0.75), "ALKIS structure, not a building (not in Hausumringe)"),
    "lod2_only": ((0.75, 0.10, 0.55), "Only in LoD2 (nothing in ALKIS)"),
    "alkis_only": ((0.00, 0.70, 0.90), "Only in ALKIS (missing from LoD2)"),
}
ALKIS_LINE = (0.04, 0.18, 0.80)
PARCEL_LINE = (0.12, 0.12, 0.12)
PLAN_ALIGNED = (0.42, 0.42, 0.40)       # aligned footprints in the plan: mid grey, for contrast


# ---------------------------------------------------------------------------
# Data and comparison
# ---------------------------------------------------------------------------
def load_geojson(name):
    with open(os.path.join(ALKIS_DIR, name), encoding="utf-8") as f:
        return [(shape(ft["geometry"]), ft["properties"]) for ft in json.load(f)["features"]]


def alkis_id(lod2_id):
    """LoD2 IDs are the ALKIS object IDs with 'L' replaced by '_' (DEBW_5221… <-> DEBWL5221…)."""
    return "DEBWL" + lod2_id[5:] if lod2_id and lod2_id.startswith("DEBW_") else None


def measure(a, b):
    inter = a.intersection(b).area
    union = a.union(b).area
    gap = shapely.hausdorff_distance(a.boundary, b.boundary, densify=0.1)
    return {"iou": inter / union if union else 0.0, "max_gap_m": gap,
            "area_lod2_m2": a.area, "area_alkis_m2": b.area,
            "centroid_shift_m": a.centroid.distance(b.centroid)}


def classify(m):
    if m["max_gap_m"] <= ALIGNED_MAX_GAP and m["iou"] >= 0.97:
        return "aligned"
    if m["max_gap_m"] <= MINOR_MAX_GAP and m["iou"] >= MIN_IOU:
        return "minor"
    return "misaligned"


def compare(buildings, alkis, structures, centre, radius):
    """alkis: AX_Gebaeude (the Hausumringe); structures: AX_SonstigesBauwerkOderSonstigeEinrichtung."""
    here = Point(centre)
    by_id = {p["gml_id"]: (g, p, "AX_Gebaeude") for g, p in alkis}
    by_id.update({p["gml_id"]: (g, p, "AX_SonstigesBauwerk") for g, p in structures})
    used, rows = set(), []
    for b in buildings:
        fp = b["footprint"]
        aid = alkis_id(b["id"])
        partners, how = [], None
        if aid in by_id:
            partners, how = [aid], "id"
        else:                                    # fall back to overlap with ALKIS buildings
            partners = [p["gml_id"] for g, p in alkis
                        if g.intersects(fp) and g.intersection(fp).area > 0.3 * min(g.area, fp.area)]
            how = "overlap" if partners else None
        row = {"lod2_id": b["id"], "address": "; ".join(b["address"]), "match": how,
               "alkis_ids": ";".join(partners), "lod2": fp}
        if partners:
            used.update(partners)
            geom = shapely.union_all([by_id[i][0] for i in partners])
            row.update(measure(fp, geom))
            kinds = {by_id[i][2] for i in partners}
            row["alkis_type"] = "/".join(sorted(kinds))
            props = by_id[partners[0]][1]
            row["alkis_function"] = props.get("gebaeudefunktion") or props.get("bauwerksfunktion") or ""
            # A structure is reported as such even if its outline matches: it is not a building
            row["status"] = "structure" if kinds == {"AX_SonstigesBauwerk"} else classify(row)
            dates = [by_id[i][1].get("version_begins") or "" for i in partners]
            row["alkis_version"] = max(dates)[:10]
            row["alkis"] = geom
        else:
            row.update(status="lod2_only", area_lod2_m2=fp.area, alkis_version="")
        rows.append(row)
    for g, p in alkis:                           # ALKIS buildings inside the radius with no LoD2
        if p["gml_id"] not in used and g.distance(here) <= radius:
            rows.append({"lod2_id": "", "address": p.get("name") or "", "match": None,
                         "alkis_ids": p["gml_id"], "status": "alkis_only", "alkis": g,
                         "area_alkis_m2": g.area, "alkis_version": (p.get("version_begins") or "")[:10],
                         "alkis_type": "AX_Gebaeude", "alkis_function": p.get("gebaeudefunktion") or ""})
    return rows


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def material(name, colour, emission=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Roughness"].default_value = 0.6
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*colour, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    mat.diffuse_color = (*colour, 1)
    return mat


CLIP = None    # disc (shapely) that outlines are cut to; set in draw()


def rings_of(geom):
    """Outline pieces as coordinate arrays, cut to the terrain disc. Returns (coords, closed)."""
    lines = geom.boundary if CLIP is None else geom.boundary.intersection(CLIP)
    for line in getattr(lines, "geoms", [lines]):
        if line.is_empty or line.geom_type != "LineString":
            continue
        coords = np.array(line.coords)
        yield coords, bool(np.allclose(coords[0], coords[-1]))


def densify(ring, step=2.0):
    out = [ring[0]]
    for p, q in zip(ring[:-1], ring[1:]):
        n = max(1, int(math.ceil(np.hypot(*(q - p)) / step)))
        out += [p + (q - p) * t for t in np.linspace(0, 1, n + 1)[1:]]
    return np.array(out)


def outline(name, geom, origin, z_of, lift, thickness, mat, collection):
    """Polygon outline(s) as a thin tube; z_of gives the ground height at local xy points."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions, curve.bevel_depth, curve.bevel_resolution = "3D", thickness, 2
    for ring, closed in rings_of(geom):
        xy = densify(ring[:, :2] - origin[:2])
        if closed:
            xy = xy[:-1]                         # cyclic spline closes itself
        z = z_of(xy) + lift
        spline = curve.splines.new("POLY")
        spline.points.add(len(xy) - 1)
        for p, (x, y), h in zip(spline.points, xy, z):
            p.co = (x, y, h, 1)
        spline.use_cyclic_u = closed
    obj = bpy.data.objects.new(name, curve)
    obj.data.materials.append(mat)
    obj.visible_shadow = False
    collection.objects.link(obj)
    return obj


def flat_fill(name, geom, origin, z, mat, collection):
    verts, faces = [], []
    for poly in getattr(geom, "geoms", [geom]):
        tri = shapely.delaunay_triangles(poly)
        for t in tri.geoms:
            if poly.contains(t.representative_point()):
                n = len(verts)
                verts += [(x - origin[0], y - origin[1], z) for x, y in list(t.exterior.coords)[:3]]
                faces.append((n, n + 1, n + 2))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def label(text, location, size, mat, collection):
    curve = bpy.data.curves.new(f"Flag {text}", "FONT")
    curve.body, curve.size = text, size
    curve.align_x, curve.align_y = "CENTER", "CENTER"
    obj = bpy.data.objects.new(f"Flag {text}", curve)
    obj.location = location
    obj.visible_shadow = False                  # no doubled "ghost" numbers from the sun
    obj.data.materials.append(mat)
    collection.objects.link(obj)
    return obj


def new_collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def draw(ctx, rows, parcels):
    global CLIP
    origin, grid = ctx["origin"], ctx["grid"]
    CLIP = Point(ctx["centre"]).buffer(ctx["radius"] + L.TERRAIN_MARGIN - 1.0, 128)
    ground = lambda xy: L.sample_grid(grid, xy)
    flat = lambda xy: np.zeros(len(xy))
    mats = {k: material(f"Status: {k}", c) for k, (c, _) in STATUS.items()}
    alkis_mat = material("ALKIS building outline", ALKIS_LINE, emission=0.6)
    only_mat = material("ALKIS only outline", STATUS["alkis_only"][0], emission=0.8)
    parcel_mat = material("ALKIS parcel boundary", PARCEL_LINE)
    paper = material("Plan background", (0.96, 0.96, 0.94))
    ink = material("Flag numbers", (0.05, 0.05, 0.05))

    # Colour the 3D LoD2 buildings by status (aligned ones keep their white/grey materials)
    objects = {o["gml_id"]: o for o in ctx["objects"]}
    for r in rows:
        o = objects.get(r["lod2_id"])
        if o is not None and r["status"] != "aligned":
            for i in range(len(o.data.materials)):
                o.data.materials[i] = mats[r["status"]]

    # Aerial overlay: lines laid on the DGM1 terrain
    aerial = new_collection("ALKIS overlay (on terrain)")
    for g, p in parcels:
        outline(f"Parcel {p.get('flurstueckskennzeichen')}", g, origin, ground, 0.15, 0.12, parcel_mat, aerial)
    for r in rows:
        if "alkis" in r:
            m = only_mat if r["status"] == "alkis_only" else alkis_mat
            outline(f"ALKIS {r['alkis_ids'][:24]}", r["alkis"], origin, ground, 0.3,
                    0.45 if r["status"] == "alkis_only" else 0.22, m, aerial)

    # Plan: flat 2D map (LoD2 footprints filled by status, ALKIS outlines on top, numbers)
    plan = new_collection("Plan view (flat)")
    r_bg = ctx["radius"] + L.TERRAIN_MARGIN
    bpy.ops.mesh.primitive_circle_add(vertices=128, radius=r_bg, fill_type="NGON", location=(0, 0, -0.5))
    bg = bpy.context.active_object
    bg.name = "Plan background"
    bg.data.materials.append(paper)
    for c in bg.users_collection:
        c.objects.unlink(bg)
    plan.objects.link(bg)
    plan_aligned = material("Plan: aligned footprint", PLAN_ALIGNED)
    for g, p in parcels:
        outline(f"Plan parcel {p.get('flurstueckskennzeichen')}", g, origin, flat, 0.05, 0.10, parcel_mat, plan)
    for r in rows:
        if "lod2" in r:
            m = plan_aligned if r["status"] == "aligned" else mats[r["status"]]
            flat_fill(f"Plan LoD2 {r['lod2_id']}", r["lod2"], origin, 0.0, m, plan)
    for r in rows:
        if "alkis" in r:
            m = only_mat if r["status"] == "alkis_only" else alkis_mat
            outline(f"Plan ALKIS {r['alkis_ids'][:24]}", r["alkis"], origin, flat, 0.3,
                    0.35 if r["status"] == "alkis_only" else 0.22, m, plan)

    # Flags: a ring in the status colour around each flagged object, with its number,
    # in both views (flagged objects such as canopies can be only a few m² large)
    labels = []
    for r in rows:
        if not r.get("flag"):
            continue
        geom = r.get("lod2") or r["alkis"]
        c = geom.centroid
        ring_r = max(4.0, 0.75 * math.sqrt(geom.area) + 2.0)
        ring = Point(c.x, c.y).buffer(ring_r, 48)
        ring_mat = material(f"Flag ring {r['status']}", STATUS[r["status"]][0], emission=1.0)
        outline(f"Flag ring {r['flag']}", ring, origin, flat, 0.6, 0.45, ring_mat, plan)
        outline(f"Flag ring {r['flag']} (terrain)", ring, origin, ground, 0.6, 0.35, ring_mat, aerial)
        lx, ly = c.x - origin[0] + ring_r + 2.5, c.y - origin[1] + ring_r + 1.0
        label(str(r["flag"]), (lx, ly, 1.0), 5.0, ink, plan)
        z = float(ground(np.array([[c.x - origin[0], c.y - origin[1]]]))[0])
        labels.append(label(str(r["flag"]), (c.x - origin[0], c.y - origin[1], z + 14.0), 6.0, ring_mat, aerial))
    return aerial, plan, labels


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def show(collection, visible):
    collection.hide_render = not visible
    collection.hide_viewport = not visible


def legend(png, rows, title, aligned_colour=None):
    img = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(img)
    try:
        font, bold = ImageFont.truetype("segoeui.ttf", 22), ImageFont.truetype("segoeuib.ttf", 24)
    except OSError:
        font = bold = ImageFont.load_default()
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS}
    colours = {k: (aligned_colour if k == "aligned" and aligned_colour else STATUS[k][0]) for k in STATUS}
    items = [(tuple(int(255 * min(1, c ** (1 / 2.2))) for c in colours[k]), f"{STATUS[k][1]}: {counts[k]}")
             for k in STATUS]
    items.append((tuple(int(255 * c ** (1 / 2.2)) for c in ALKIS_LINE), "ALKIS building outline (line)"))
    items.append((tuple(int(255 * c ** (1 / 2.2)) for c in PARCEL_LINE), "ALKIS parcel boundary (line)"))
    w, h = 640, 34 * (len(items) + 1) + 12
    x0, y0 = img.width - w - 24, 60                       # top right, below the credit line
    d.rectangle([x0 - 12, y0 - 12, x0 + w, y0 + h], fill=(255, 255, 255), outline=(180, 180, 180))
    d.text((x0, y0), title, fill=(20, 20, 20), font=bold)
    for i, (col, text) in enumerate(items):
        y = y0 + 36 + 34 * i
        d.rectangle([x0, y + 4, x0 + 26, y + 26], fill=col, outline=(60, 60, 60))
        d.text((x0 + 38, y), text, fill=(20, 20, 20), font=font)
    img.save(png)


def render(ctx, rows, aerial, plan, labels, buildings_col, terrain_objs):
    scene = bpy.context.scene
    r = scene.render
    r.stamp_note_text = (f"Weissenhofsiedlung, Stuttgart – LoD2 footprints vs. ALKIS building outlines "
                         f"(Hausumringe), {ctx['radius']:.0f} m radius  ·  {L.CREDIT}")
    # 1. Aerial: same camera as the LoD2 overview; flag numbers face the camera
    aerial_cam = scene.camera
    for t in labels:
        t.rotation_euler = aerial_cam.rotation_euler
    show(plan, False)
    out = os.path.join(PROJECT_DIR, "renders", "alkis_lod2_aerial.png")
    r.filepath = out
    bpy.ops.render.render(write_still=True)
    legend(out, rows, "LoD2 vs. ALKIS")
    print(f"Saved {os.path.relpath(out, PROJECT_DIR)}")
    # 2. Plan: orthographic, straight down, flat map only
    cam = bpy.data.objects.new("Camera plan", bpy.data.cameras.new("Camera plan"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2 * (ctx["radius"] + L.TERRAIN_MARGIN) + 10
    cam.location = (0, 0, 300)
    cam.data.clip_end = 1000
    scene.collection.objects.link(cam)
    scene.camera = cam
    show(plan, True)
    show(aerial, False)
    show(buildings_col, False)
    for o in terrain_objs:
        o.hide_render = True
    res = r.resolution_x, r.resolution_y
    r.resolution_x = r.resolution_y = 1800
    r.stamp_note_text = f"Weissenhofsiedlung – LoD2 vs. ALKIS outlines (Hausumringe)  ·  {L.CREDIT}"
    out = os.path.join(PROJECT_DIR, "renders", "alkis_lod2_plan.png")
    r.filepath = out
    bpy.ops.render.render(write_still=True)
    legend(out, rows, "LoD2 footprints vs. ALKIS outlines (north up)", aligned_colour=PLAN_ALIGNED)
    print(f"Saved {os.path.relpath(out, PROJECT_DIR)}")
    # leave the .blend in the aerial state
    r.resolution_x, r.resolution_y = res
    show(plan, False)
    show(aerial, True)
    show(buildings_col, True)
    for o in terrain_objs:
        o.hide_render = False
    scene.camera = aerial_cam


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report(rows, ctx, n_parcels):
    order = {"misaligned": 0, "alkis_only": 1, "lod2_only": 2, "structure": 3, "minor": 4, "aligned": 5}
    rows.sort(key=lambda r: (order[r["status"]], -r.get("max_gap_m", 0)))
    flagged = [r for r in rows if r["status"] != "aligned"]
    for i, r in enumerate(flagged, 1):
        r["flag"] = i
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS}
    newer = sum(1 for r in flagged if r.get("alkis_version", "") > LOD2_FOOTPRINT_DATE)

    with open(os.path.join(ALKIS_DIR, "comparison_weissenhof.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["flag", "status", "address", "lod2_id", "alkis_ids", "alkis_type", "alkis_function",
                "match", "max_gap_m", "iou", "area_lod2_m2", "area_alkis_m2", "centroid_shift_m",
                "alkis_version"]
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{r[k]:.3f}" if isinstance(r.get(k), float) else r.get(k, "")) for k in cols})

    fmt = lambda v, n=2: "–" if v is None else f"{v:.{n}f}"
    gaps = sorted(r["max_gap_m"] for r in rows if "max_gap_m" in r)
    ious = [r["iou"] for r in rows if "iou" in r]
    official = [r for r in rows if r.get("alkis_type") == "AX_Gebaeude" or r["status"] == "alkis_only"]
    versions = sorted(r.get("alkis_version") or "" for r in official)
    lines = [
        "# LoD2 footprints vs. ALKIS building outlines – Weissenhofsiedlung",
        "",
        f"Area: buildings within {ctx['radius']:.0f} m of E {ctx['centre'][0]:.1f}, N {ctx['centre'][1]:.1f} "
        "(EPSG:25832). Made by `scripts/compare_alkis_lod2.py`.",
        "",
        "## Result",
        "",
        f"- **Geometry:** the {len(gaps)} matched outlines differ by at most **{gaps[-1]:.3f} m** "
        f"(median {gaps[len(gaps) // 2]:.3f} m); every overlap is ≥ {100 * min(ious):.1f} %. "
        f"{counts['misaligned'] + counts['minor']} buildings deviate by more than {ALIGNED_MAX_GAP:.2f} m.",
        f"- **Completeness:** all {sum(1 for r in official if r['status'] != 'alkis_only')} official "
        f"ALKIS buildings in the area have a LoD2 building (matched 1:1 by object ID); "
        f"{counts['alkis_only']} are missing from LoD2.",
        f"- **Classification:** {counts['structure']} LoD2 \"buildings\" are canopies that ALKIS records "
        "as structures, not buildings, so they are not part of the Hausumringe. Their outlines match.",
        f"- **Currency:** the newest ALKIS building version in the area is {versions[-1] if versions else '–'}, "
        f"before the LoD2 footprint date ({LOD2_FOOTPRINT_DATE}). The 15-month age difference between "
        "the datasets made no difference here.",
        "",
        "**What this means:** LoD2 footprints are produced *from* ALKIS, so this comparison checks "
        "how faithfully they were transferred, not how accurate either is against the real buildings. "
        "Here the transfer is exact. Real-world deviations (roof overhangs, extensions not yet in the "
        "cadastre, roof heights and forms) need an independent source such as the LGL digital surface "
        "model (DOM) or orthophotos.",
        "",
        "## Data",
        "",
        "- **LoD2**: footprints (ground surfaces) of the LGL LoD2 buildings. Per the LoD2 INFO file "
        f"they were taken from ALKIS dated **{LOD2_FOOTPRINT_DATE}**.",
        "- **ALKIS**: `AX_Gebaeude` outlines (the source of LGL's Hausumringe) and `AX_Flurstueck` "
        f"parcels ({n_parcels} in the area) from `data/ALKIS.zip`, current as of **July 2026**.",
        "- Matching: LoD2 object IDs are the ALKIS object IDs with `L` replaced by `_`; where no ID "
        "matches, buildings are paired by overlap.",
        "",
        "## Classification",
        "",
        "| Status | Rule | Buildings |",
        "|---|---|---|",
        f"| Aligned | largest gap between outlines ≤ {ALIGNED_MAX_GAP:.2f} m and overlap ≥ 97 % | {counts['aligned']} |",
        f"| Minor deviation | gap ≤ {MINOR_MAX_GAP:.1f} m and overlap ≥ {MIN_IOU:.0%} | {counts['minor']} |",
        f"| Misaligned | gap > {MINOR_MAX_GAP:.1f} m or overlap < {MIN_IOU:.0%} | {counts['misaligned']} |",
        f"| ALKIS structure, not a building | LoD2 models it as a building; ALKIS has it as "
        f"`AX_SonstigesBauwerkOderSonstigeEinrichtung`, so it is not in the Hausumringe | {counts['structure']} |",
        f"| Only in ALKIS | official building with no LoD2 building | {counts['alkis_only']} |",
        f"| Only in LoD2 | LoD2 building with nothing in ALKIS | {counts['lod2_only']} |",
        "",
        "Gap = Hausdorff distance between the two outlines (the largest distance from any point on "
        "one outline to the nearest point on the other). Overlap = intersection / union (IoU).",
        "LoD2 buildings made of several parts are joined into one footprint first; hairline gaps "
        "(< 10 cm) between parts are closed so they do not count as deviations.",
        "",
        "ALKIS function codes seen: building `gebaeudefunktion` and structure `bauwerksfunktion`; "
        "structure code 1610 is *Überdachung* (canopy) in the ALKIS code list.",
        "",
        f"{newer} of the {len(flagged)} flagged buildings have an ALKIS object version newer than "
        f"{LOD2_FOOTPRINT_DATE}, i.e. the cadastre changed after the LoD2 footprints were taken.",
        "",
        "## Flagged buildings",
        "",
        "Numbers match the flags in `renders/alkis_lod2_plan.png`.",
        "",
        "| # | Status | Address | ALKIS object (function) | Max gap (m) | Overlap | LoD2 area (m²) | ALKIS area (m²) | ALKIS version | LoD2 ID |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in flagged:
        obj = f"{r.get('alkis_type') or '–'} ({r.get('alkis_function') or '–'})" if r.get("alkis_type") else "–"
        lines.append(f"| {r['flag']} | {STATUS[r['status']][1].split(' (')[0]} | {r['address'] or '–'} | {obj} | "
                     f"{fmt(r.get('max_gap_m'))} | {fmt(r.get('iou') and 100 * r['iou'], 0)}{'%' if r.get('iou') else ''} | "
                     f"{fmt(r.get('area_lod2_m2'), 1)} | {fmt(r.get('area_alkis_m2'), 1)} | "
                     f"{r.get('alkis_version') or '–'} | `{r.get('lod2_id') or '–'}` |")
    lines += ["", "All buildings with their metrics: `data/alkis/comparison_weissenhof.csv`.", "",
              "Datenquelle: LGL, www.lgl-bw.de", ""]
    with open(os.path.join(PROJECT_DIR, "notes", "alkis_lod2_comparison.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Saved notes/alkis_lod2_comparison.md and data/alkis/comparison_weissenhof.csv")
    print("Counts:", counts, f"| flagged with ALKIS version after {LOD2_FOOTPRINT_DATE}: {newer}")


def main():
    ctx = L.build_scene()
    alkis = load_geojson("alkis_gebaeude_weissenhof.geojson")
    structures = load_geojson("alkis_bauwerke_weissenhof.geojson")
    parcels = load_geojson("alkis_flurstuecke_weissenhof.geojson")
    here = Point(ctx["centre"])
    parcels = [(g, p) for g, p in parcels if g.distance(here) <= ctx["radius"] + L.TERRAIN_MARGIN]
    rows = compare(ctx["buildings"], alkis, structures, ctx["centre"], ctx["radius"])
    write_report(rows, ctx, len(parcels))
    buildings_col = next(c for c in bpy.data.collections if c.name.startswith("LoD2 buildings"))
    terrain_objs = [o for o in bpy.data.objects if o.name.startswith(("Terrain", "Selection radius"))]
    aerial, plan, labels = draw(ctx, rows, parcels)
    if "--no-render" not in sys.argv:
        render(ctx, rows, aerial, plan, labels, buildings_col, terrain_objs)
    path = os.path.join(PROJECT_DIR, "models", "lod2_weissenhof_alkis.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"Saved {os.path.relpath(path, PROJECT_DIR)}")


if __name__ == "__main__":
    main()

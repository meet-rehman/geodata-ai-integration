"""Drape the LGL DOP20 orthophoto over the DGM1 terrain and compare it with the LoD2 model.

Run from the project root (needs the Bonsai extension: lxml, shapely, Pillow):
    blender --background --python scripts/render_dop20.py
Takes the same --centre / --radius options as import_lod2.py.

Uses import_lod2.build_scene() (same LoD2 buildings, DGM1 terrain and local origin), then:
  1. cuts the area out of the DOP20 tiles (data/dop20/<tile>/*.tif + .tfw world files) into
     data/dop20/dop20_weissenhof_crop.png and maps it onto the terrain with UV coordinates
     computed from the same EPSG:25832 coordinates, so photo, terrain and buildings line up,
  2. renders
       renders/dop20_overview_plan.png     top-down, LoD2 footprints as outlines on the photo
       renders/dop20_aerial.png            the aerial camera: LoD2 massing on the draped photo
       renders/dop20_rathenau_photo.png    close-up of Rathenaustraße 1-3, footprints + LoD2 roof edges
       renders/dop20_rathenau_lod2.png     the same building as LoD2 massing, oblique
       renders/dop20_scan_<quadrant>.png   native-resolution quadrants for the visual scan
     and prints the LoD2 roof geometry of the close-up building.
"""
import math
import os
import sys

import bpy
import numpy as np
import shapely
from mathutils import Vector
from PIL import Image
from shapely.geometry import Point

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_lod2 as L  # noqa: E402

PROJECT_DIR = L.PROJECT_DIR
DOP_DIR = os.path.join(PROJECT_DIR, "data", "dop20")
CROP_PNG = os.path.join(DOP_DIR, "dop20_weissenhof_crop.png")
RENDERS = os.path.join(PROJECT_DIR, "renders")
PIXEL = 0.20                                   # m per pixel (DOP20)
CLOSEUP_ADDRESSES = ("Rathenaustraße 1", "Rathenaustraße 3")

# Findings from the visual scan of the orthophoto, each checked against LoD2 and ALKIS
# (see notes/dop20_findings.md). (number, E, N, marker radius m, in radius?, text)
FINDINGS = [
    (1, 513046.5, 5405227.0, 18, True,
     "Rathenaustraße 1–3: photo shows a flat roof with a walled roof terrace; LoD2 models two gables (14–32°)"),
    (2, 513054.0, 5405226.0, 6, True,
     "Rathenaustraße 1–3: ~1 m light band along the whole east side, outside the footprint (projecting upper floor/roof?)"),
    (3, 512895.0, 5405286.0, 45, True,
     "Am Weißenhof 5: rows of rooflights on the roof; LoD2 = flat (roof superstructures are not modelled)"),
    (4, 512963.0, 5405153.0, 25, True,
     "Gardens south of Friedrich-Ebert-Straße: garden huts, in neither LoD2 nor ALKIS"),
    (5, 513080.0, 5405161.0, 30, True,
     "Gardens south-east: ≥ 6 garden houses, a greenhouse and sheds, in neither LoD2 nor ALKIS"),
    (6, 512875.0, 5405199.0, 22, False,
     "Outside 150 m: cleared site (bare earth, rubble); LoD2 and ALKIS still hold small buildings here"),
    (7, 513110.0, 5405121.0, 20, False,
     "Outside 150 m, not checked: possible construction site beside a large building"),
]
FOOTPRINT_COLOUR = (1.0, 0.85, 0.0)            # yellow
ROOF_EDGE_COLOUR = (1.0, 0.15, 0.10)           # red


# ---------------------------------------------------------------------------
# Orthophoto mosaic
# ---------------------------------------------------------------------------
def read_world_file(tfw):
    """Upper-left corner of the upper-left pixel (world files give the pixel centre)."""
    a, _, _, e, c, f = (float(v) for v in open(tfw).read().split())
    return c - a / 2, f - e / 2, a                 # e is negative


def build_mosaic(centre, half):
    """Cut the square centre ± half out of the DOP20 tiles; returns (path, E0, N0, size_m)."""
    x0, y1 = centre[0] - half, centre[1] + half    # upper-left corner of the crop
    n = int(round(2 * half / PIXEL))
    mosaic = Image.new("RGB", (n, n))
    used = []
    Image.MAX_IMAGE_PIXELS = None
    for root, _, files in os.walk(DOP_DIR):
        for name in files:
            if not name.lower().endswith(".tif"):
                continue
            tif = os.path.join(root, name)
            e0, n_top, px = read_world_file(tif[:-4] + ".tfw")
            with Image.open(tif) as img:
                w, h = img.size
                # crop window in this tile's pixels
                left, top = (x0 - e0) / px, (n_top - y1) / px
                box = [round(left), round(top), round(left) + n, round(top) + n]
                clip = [max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])]
                if clip[0] >= clip[2] or clip[1] >= clip[3]:
                    continue
                mosaic.paste(img.crop(clip).convert("RGB"), (clip[0] - box[0], clip[1] - box[1]))
                used.append(name)
    mosaic.save(CROP_PNG)
    print(f"DOP20 mosaic {n} x {n} px from {used} -> {os.path.relpath(CROP_PNG, PROJECT_DIR)}")
    return CROP_PNG, x0, y1 - 2 * half, 2 * half


def drape_photo(terrain, origin, crop):
    """UVs from world coordinates (same local origin), photo shown as-is (emission)."""
    path, e0, n0, size = crop
    mesh = terrain.data
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    u = (co[:, 0] + origin[0] - e0) / size
    v = (co[:, 1] + origin[1] - n0) / size
    loops = np.empty(len(mesh.loops), dtype=int)
    mesh.loops.foreach_get("vertex_index", loops)
    uv = mesh.uv_layers.new(name="DOP20")
    uv.data.foreach_set("uv", np.column_stack([u[loops], v[loops]]).ravel())

    mat = bpy.data.materials.new("DOP20 orthophoto")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(path)
    tex.interpolation = "Cubic"
    tex.extension = "EXTEND"
    emit = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    mesh.materials.clear()
    mesh.materials.append(mat)


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------
def emission_material(name, colour, strength=2.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*colour, 1)
    emit.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def polyline_object(name, lines, z, thickness, mat, collection):
    """lines: list of (n, 2) local xy arrays (closed rings are closed by repeating the first point)."""
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions, curve.bevel_depth, curve.bevel_resolution = "3D", thickness, 1
    for xy in lines:
        spline = curve.splines.new("POLY")
        spline.points.add(len(xy) - 1)
        for p, (x, y) in zip(spline.points, xy):
            p.co = (x, y, z, 1)
    obj = bpy.data.objects.new(name, curve)
    obj.data.materials.append(mat)
    obj.visible_shadow = False
    collection.objects.link(obj)
    return obj


def footprint_lines(geom, origin):
    out = []
    for poly in getattr(geom, "geoms", [geom]):
        for ring in [poly.exterior, *poly.interiors]:
            out.append(np.array(ring.coords)[:, :2] - origin[:2])
    return out


def roof_edges(bld, origin):
    """Every edge of every LoD2 roof polygon, in plan (ridges, hips and roof outlines)."""
    out = []
    for ring in bld["surfaces"]["RoofSurface"]:
        xy = ring[:, :2] - origin[:2]
        out.append(np.vstack([xy, xy[:1]]))
    return out


def translucent_material(name, colour, alpha):
    """Emission colour over the photo with the given opacity (0 = invisible)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*colour, 1)
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = alpha
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(clear.outputs["BSDF"], mix.inputs[1])
    nt.links.new(emit.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def roof_fills(bld, origin, z, pitched_mat, flat_mat, collection, ink, flat_limit=5.0):
    """Each LoD2 roof polygon, flattened into plan and filled: red if pitched, blue if flat,
    with its pitch written on it."""
    for i, (ring, (pitch, area, _, _)) in enumerate(zip(bld["surfaces"]["RoofSurface"], roof_report(bld))):
        xy = ring[:, :2] - origin[:2]
        mesh = bpy.data.meshes.new(f"Roof {bld['id']} {i}")
        mesh.from_pydata([(x, y, z) for x, y in xy], [], [list(range(len(xy)))])
        mesh.materials.append(pitched_mat if pitch > flat_limit else flat_mat)
        obj = bpy.data.objects.new(mesh.name, mesh)
        obj.visible_shadow = False
        collection.objects.link(obj)
        c = xy.mean(axis=0)
        txt = bpy.data.curves.new(f"Pitch {bld['id']} {i}", "FONT")
        txt.body = f"{pitch:.0f}°" if pitch > flat_limit else "flat"
        txt.size, txt.align_x, txt.align_y = 1.1, "CENTER", "CENTER"
        t = bpy.data.objects.new(txt.name, txt)
        t.location = (c[0], c[1], z + 0.3)
        t.data.materials.append(ink)
        t.visible_shadow = False
        collection.objects.link(t)


def roof_report(bld):
    """Pitch and area of every LoD2 roof polygon of a building."""
    rows = []
    for ring in bld["surfaces"]["RoofSurface"]:
        # Newell's method for the polygon normal
        n = np.zeros(3)
        for p, q in zip(ring, np.roll(ring, -1, axis=0)):
            n += [(p[1] - q[1]) * (p[2] + q[2]), (p[2] - q[2]) * (p[0] + q[0]), (p[0] - q[0]) * (p[1] + q[1])]
        area = np.linalg.norm(n) / 2
        pitch = math.degrees(math.acos(min(1.0, abs(n[2]) / np.linalg.norm(n))))
        rows.append((pitch, area, ring[:, 2].min(), ring[:, 2].max()))
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def ortho_camera(name, centre_local, scale):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    cam.data.type, cam.data.ortho_scale, cam.data.clip_end = "ORTHO", scale, 2000
    cam.location = (centre_local[0], centre_local[1], 600)
    bpy.context.scene.collection.objects.link(cam)
    return cam


def render_to(cam, filename, res, note):
    scene = bpy.context.scene
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.stamp_note_text = f"{note}  ·  {L.CREDIT}"
    scene.render.filepath = os.path.join(RENDERS, filename)
    bpy.ops.render.render(write_still=True)
    print(f"Saved renders/{filename}")


def set_visible(objs, visible):
    for o in objs:
        o.hide_render = not visible


def fonts():
    from PIL import ImageFont
    try:
        return (ImageFont.truetype("segoeui.ttf", 26), ImageFont.truetype("segoeuib.ttf", 30),
                ImageFont.truetype("segoeuib.ttf", 40))
    except OSError:
        f = ImageFont.load_default()
        return f, f, f


def wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=font) > width and line:
            lines.append(line)
            line = word
        else:
            line = test
    return lines + [line]


def compose_rathenau():
    """Three labelled panels: photo | LoD2 roof faces on the photo | LoD2 massing."""
    from PIL import ImageDraw
    body, bold, title = fonts()
    panels = [
        ("dop20_rathenau_photo.png",
         "A · Orthophoto DOP20 (20 cm): flat roof. Open bays bordered by light walls, each shaded on "
         "its west side (sun from the south-east) – a walled roof terrace. No ridge, no paired "
         "light/dark roof faces. Wings flat. Yellow = LoD2 footprint, red = LoD2 roof edges."),
        ("dop20_rathenau_faces.png",
         "B · LoD2 roof faces on the same photo: red = pitched (14°, 23°, 27°, 32°), blue = flat. "
         "LoD2 puts two ridges across the main block, where the photo shows terrace walls."),
        ("dop20_rathenau_lod2.png",
         "C · LoD2 massing seen from the east-south-east: the double gable LoD2 reconstructs "
         "(roofType 3100 'gable' + 1000 'flat' for both no. 1 and no. 3)."),
    ]
    size, gap, head, cap = 900, 24, 230, 190
    sheet = Image.new("RGB", (3 * size + 4 * gap, head + size + cap + 70), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    d.text((gap, 20), "Rathenaustraße 1–3 (Le Corbusier & Pierre Jeanneret, 1927): LoD2 roof vs. DOP20 orthophoto",
           fill=(20, 20, 20), font=title)
    d.rectangle([gap, 84, sheet.width - gap, 204], fill=(253, 235, 233), outline=(200, 40, 30), width=3)
    verdict = ("FLAGGED – the orthophoto contradicts LoD2: the main block has a flat roof with a walled roof "
               "terrace, LoD2 models it as two gables (four pitched faces, 14–32°). The footprint itself "
               "matches ALKIS within 3 cm.")
    for i, line in enumerate(wrap(d, verdict, bold, sheet.width - 4 * gap)):
        d.text((2 * gap, 98 + 36 * i), line, fill=(150, 20, 10), font=bold)
    for k, (fname, caption) in enumerate(panels):
        x = gap + k * (size + gap)
        img = Image.open(os.path.join(RENDERS, fname)).convert("RGB").resize((size, size), Image.LANCZOS)
        sheet.paste(img, (x, head))
        for i, line in enumerate(wrap(d, caption, body, size)):
            d.text((x, head + size + 12 + 32 * i), line, fill=(30, 30, 30), font=body)
    foot = ("Interpretation, not verified: LoD2 roofs are fitted automatically to airborne laser points; the "
            "2.3–3 m roof-terrace walls were probably read as gables. Confirm with a site photo or the LGL DOM.   "
            f"·   {L.CREDIT}")
    d.text((gap, sheet.height - 52), foot, fill=(90, 90, 90), font=body)
    out = os.path.join(RENDERS, "dop20_rathenau_comparison.png")
    sheet.save(out)
    print(f"Saved renders/{os.path.basename(out)}")


def add_findings_legend(png):
    from PIL import ImageDraw
    body, bold, _ = fonts()
    img = Image.open(png).convert("RGB")
    panel_w = 820
    sheet = Image.new("RGB", (img.width + panel_w, img.height), (255, 255, 255))
    sheet.paste(img, (0, 0))
    d = ImageDraw.Draw(sheet)
    x, y = img.width + 30, 60
    d.text((x, y), "Visual scan: DOP20 vs. LoD2", fill=(20, 20, 20), font=bold)
    y += 56
    for n, _, _, _, inside, text in FINDINGS:
        col = (200, 0, 160) if inside else (120, 120, 120)
        d.ellipse([x, y + 2, x + 36, y + 38], outline=col, width=4)
        d.text((x + 11, y + 2), str(n), fill=col, font=bold)
        for i, line in enumerate(wrap(d, text, body, panel_w - 100)):
            d.text((x + 52, y + 4 + 32 * i), line, fill=(30, 30, 30), font=body)
        y += 32 * len(wrap(d, text, body, panel_w - 100)) + 26
    y += 10
    for line in wrap(d, "Also seen on many roofs, not in LoD2 by design: skylights, rooftop units, solar "
                     "panels, green roofs. Checked and consistent: Friedrich-Ebert-Straße 112 (hip roof, "
                     "LoD2 21–22°), Rathenaustraße 13 (flat). Magenta = within 150 m, grey = outside.",
                     body, panel_w - 60):
        d.text((x, y), line, fill=(70, 70, 70), font=body)
        y += 32
    sheet.save(png)


def main():
    ctx = L.build_scene()
    origin, radius, centre = ctx["origin"], ctx["radius"], ctx["centre"]
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Standard"      # photo colours as captured
    scene.view_settings.look = "None"
    scene.cycles.use_denoising = False                    # the denoiser would blur the photo
    scene.cycles.samples = 16

    half = radius + L.TERRAIN_MARGIN + 5
    crop = build_mosaic(centre, half)
    terrain = next(o for o in bpy.data.objects if o.name.startswith("Terrain (LGL DGM1"))
    drape_photo(terrain, origin, crop)
    scene["orthophoto"] = "LGL DOP20 (2025-11-08), draped on DGM1 with the same local origin"

    buildings = ctx["buildings"]
    building_objs = list(ctx["objects"])
    ring = [o for o in bpy.data.objects if o.name.startswith("Selection radius")]
    overlay = bpy.data.collections.new("LoD2 outlines on orthophoto")
    scene.collection.children.link(overlay)
    yellow = emission_material("LoD2 footprint outline", FOOTPRINT_COLOUR)
    red = emission_material("LoD2 roof edges", ROOF_EDGE_COLOUR)
    top = 80.0                                           # above every roof, for top-down views
    all_lines = [ln for b in buildings for ln in footprint_lines(b["footprint"], origin)]
    outlines = polyline_object("LoD2 footprints (outline)", all_lines, top, 0.15, yellow, overlay)
    # Context: LoD2 buildings outside the radius but inside the photo, in a second colour, so a
    # roof with no outline at all really is missing from LoD2; plus the selection radius.
    inside = {b["id"] for b in buildings}
    wider, _ = L.load_buildings(L.gml_files(), centre, half)
    ctx_lines = [ln for b in wider if b["id"] not in inside for ln in footprint_lines(b["footprint"], origin)]
    cyan = emission_material("LoD2 footprint outside radius", (0.2, 0.9, 1.0))
    context = polyline_object("LoD2 footprints outside radius", ctx_lines, top, 0.10, cyan, overlay)
    a = np.linspace(0, 2 * math.pi, 361)
    radius_line = polyline_object(f"Radius {radius:.0f} m (plan)", [np.column_stack([radius * np.cos(a), radius * np.sin(a)])],
                                  top, 0.25, emission_material("Radius line", (1.0, 0.25, 0.1)), overlay)

    # 1. Overview, top-down: photo + LoD2 footprint outlines (buildings hidden)
    set_visible(building_objs + ring, False)
    cam = ortho_camera("Camera DOP plan", (0, 0), 2 * half)
    render_to(cam, "dop20_overview_plan.png", (1850, 1850),
              "DOP20 orthophoto with LoD2 footprints: yellow = within 150 m (red ring), cyan = outside; north up")

    # 1b. Findings map: the overview with numbered markers, list added beside it
    marks = bpy.data.collections.new("Scan findings")
    scene.collection.children.link(marks)
    magenta = emission_material("Finding (in radius)", (0.85, 0.0, 0.65), 3.0)
    grey = emission_material("Finding (outside radius)", (0.6, 0.6, 0.6), 2.0)
    white = emission_material("Finding numbers", (1, 1, 1), 3.0)
    a = np.linspace(0, 2 * math.pi, 97)
    for n, e, nn, r_m, inside, _ in FINDINGS:
        cx, cy = e - origin[0], nn - origin[1]
        polyline_object(f"Finding {n}", [np.column_stack([cx + r_m * np.cos(a), cy + r_m * np.sin(a)])],
                        top + 1, 0.45, magenta if inside else grey, marks)
        txt = bpy.data.curves.new(f"Finding {n} label", "FONT")
        txt.body, txt.size, txt.align_x, txt.align_y = str(n), 9.0, "CENTER", "CENTER"
        t = bpy.data.objects.new(txt.name, txt)
        t.location = (cx + r_m * 0.75 + 5, cy + r_m * 0.75 + 5, top + 2)
        t.data.materials.append(magenta if inside else grey)
        marks.objects.link(t)
    render_to(cam, "dop20_findings.png", (1850, 1850),
              "Visual scan of DOP20 vs. LoD2 – numbered findings (see list)")
    add_findings_legend(os.path.join(RENDERS, "dop20_findings.png"))
    set_visible(list(marks.objects), False)

    # 2. Scan quadrants at native resolution (0.2 m per pixel)
    q = half / 2
    for name, (cx, cy) in {"nw": (-q, q), "ne": (q, q), "sw": (-q, -q), "se": (q, -q)}.items():
        cam = ortho_camera(f"Camera scan {name}", (cx, cy), half)
        render_to(cam, f"dop20_scan_{name}.png", (int(half / PIXEL),) * 2,
                  f"Scan {name.upper()}: DOP20 + LoD2 footprints")

    # 3. Close-up of Rathenaustraße 1-3: footprints (yellow) and LoD2 roof edges (red)
    close = [b for b in buildings if any(a in CLOSEUP_ADDRESSES for a in b["address"])]
    for b in close:
        print(f"LoD2 {', '.join(b['address'])} ({b['id']}): roof types {b['roof_types']}, "
              f"measured height {b['height']} m")
        for pts, (pitch, area, zmin, zmax) in zip(b["surfaces"]["RoofSurface"], roof_report(b)):
            c = pts[:, :2].mean(axis=0)
            print(f"    roof polygon: pitch {pitch:5.1f} deg, area {area:6.1f} m2, "
                  f"z {zmin - origin[2]:.2f}-{zmax - origin[2]:.2f} m (local), "
                  f"centre E {c[0]:.1f} N {c[1]:.1f}, extent {np.ptp(pts[:, 0]):.1f} x {np.ptp(pts[:, 1]):.1f} m")
    union = shapely.union_all([b["footprint"] for b in close])
    c = union.centroid
    c_local = (c.x - origin[0], c.y - origin[1])
    edges = [ln for b in close for ln in roof_edges(b, origin)]
    roof_obj = polyline_object("LoD2 roof edges (close-up)", edges, top + 0.5, 0.06, red, overlay)
    outlines.data.bevel_depth = 0.08
    cam = ortho_camera("Camera Rathenau photo", c_local, 42.0)
    render_to(cam, "dop20_rathenau_photo.png", (1600, 1600),
              "Rathenaustraße 1–3: DOP20, LoD2 footprint (yellow), LoD2 roof edges (red)")

    # 3b. Same close-up with LoD2's roof faces filled: red = pitched, blue = flat
    fills = bpy.data.collections.new("LoD2 roof faces (close-up)")
    scene.collection.children.link(fills)
    ink = emission_material("Pitch labels", (1, 1, 1), 3.0)
    for b in close:
        roof_fills(b, origin, top + 0.2, translucent_material("LoD2 pitched roof face", (1.0, 0.1, 0.05), 0.40),
                   translucent_material("LoD2 flat roof face", (0.1, 0.45, 1.0), 0.40), fills, ink)
    render_to(cam, "dop20_rathenau_faces.png", (1600, 1600),
              "Rathenaustraße 1–3: LoD2 roof faces on DOP20 – red = pitched, blue = flat")

    # 4. Same building as LoD2 massing, oblique from the south-west, on the draped photo
    set_visible(building_objs, True)
    set_visible([outlines, roof_obj, context, radius_line] + list(fills.objects), False)
    z = float(L.sample_grid(ctx["grid"], np.array([c_local]))[0])
    cam = bpy.data.objects.new("Camera Rathenau LoD2", bpy.data.cameras.new("Camera Rathenau LoD2"))
    cam.data.lens = 50
    # From the east-south-east: the LoD2 ridges run east-west, so their gables face this way
    target = Vector((c_local[0], c_local[1], z + 6))
    cam.location = target + Vector((44, -22, 26))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.view_settings.view_transform = "AgX"
    scene.cycles.samples, scene.cycles.use_denoising = 64, True
    render_to(cam, "dop20_rathenau_lod2.png", (1600, 1600),
              "Rathenaustraße 1–3 as LoD2 massing (roof forms from LoD2)")
    compose_rathenau()

    # 5. Aerial overview (same camera as the LoD2 renders): massing on the draped photo
    aerial = bpy.data.objects["Camera aerial"]
    set_visible(ring, True)
    render_to(aerial, "dop20_aerial.png", (1920, 1080),
              "Weissenhofsiedlung – LoD2 massing on DOP20 orthophoto draped over DGM1")

    scene.camera = aerial
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    path = os.path.join(PROJECT_DIR, "models", "lod2_weissenhof_dop20.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"Saved {os.path.relpath(path, PROJECT_DIR)}")


if __name__ == "__main__":
    main()

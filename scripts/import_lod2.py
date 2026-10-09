"""Import LGL LoD2 buildings (CityGML) around a point into Blender as white massing.

Run from the project root (needs the Bonsai extension, which provides lxml and shapely):
    blender --background --python scripts/import_lod2.py
Options after "--":
    --centre E N   centre in EPSG:25832 (default: the Weissenhofsiedlung, see ANCHORS)
    --radius R     metres (default 150)
    --preview      quick 480 x 270, 16-sample render
    --no-render    only build and save the .blend

Reads every tile in data/lod2/<tile>/<tile>/*.gml, keeps buildings whose footprint comes
within the radius, and writes:
    models/lod2_weissenhof.blend        georeferenced scene (origin stored as scene properties)
    renders/lod2_weissenhof_overview.png aerial overview with the LGL credit

Terrain: the LGL DGM1 (1 m grid, XYZ) from data/dgm1/<tile>/<tile>/*.xyz. If it does not
cover the area, the script falls back to a surface estimated from the buildings' ground
heights and says so.

Coordinates: ETRS89 / UTM 32N (EPSG:25832), heights DHHN2016 for both LoD2 and DGM1.
Blender works in single precision, so everything is shifted to one local origin (the
centre and the lowest LoD2 ground height); the shift is stored on the scene so positions
can be converted back.
"""
import glob
import math
import os
import sys
from collections import Counter

import bmesh
import bpy
import numpy as np
import shapely
from lxml import etree
from mathutils import Vector
from shapely.geometry import MultiPoint, Point, Polygon

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOD2_DIR = os.path.join(PROJECT_DIR, "data", "lod2")
DGM_DIR = os.path.join(PROJECT_DIR, "data", "dgm1")
TERRAIN_MARGIN = 30.0                       # terrain extends this far past the radius, m
BLEND_PATH = os.path.join(PROJECT_DIR, "models", "lod2_weissenhof.blend")
PNG_PATH = os.path.join(PROJECT_DIR, "renders", "lod2_weissenhof_overview.png")
CREDIT = "Datenquelle: LGL, www.lgl-bw.de"

# Default centre: midpoint of two buildings of the 1927 Weissenhofsiedlung, found by address:
# Am Weißenhof 14-20 (Mies van der Rohe's apartment block) and Rathenaustraße 1-3
# (Le Corbusier's double house, today the Weissenhofmuseum).
ANCHORS = {"Am Weißenhof": {"14", "16", "18", "20"}, "Rathenaustraße": {"1", "3"}}

# CityGML roofType codes (AdV / SIG3D code list) -> readable names
ROOF_TYPES = {"1000": "flat", "2100": "shed", "2200": "sawtooth", "3100": "gable", "3200": "hip",
              "3300": "half-hip", "3400": "pyramid", "3500": "mansard", "3600": "barrel",
              "3700": "conical", "3800": "dome", "4000": "mixed", "5000": "combination",
              "9999": "other"}


def arg(name, n=1, default=None):
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if name not in args:
        return default
    i = args.index(name)
    return [float(v) for v in args[i + 1:i + 1 + n]] if n else True


# ---------------------------------------------------------------------------
# Reading CityGML
# ---------------------------------------------------------------------------
def gml_files():
    return sorted(glob.glob(os.path.join(LOD2_DIR, "*", "*", "*.gml")))


def envelope(path):
    """lower/upper corner from the file header, without parsing the whole file."""
    with open(path, encoding="utf-8") as f:
        head = f.read(4000)
    lo = head.split("lowerCorner")[1].split(">")[1].split("<")[0].split()
    hi = head.split("upperCorner")[1].split(">")[1].split("<")[0].split()
    return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


def rings(surface):
    """Exterior rings of all polygons under a surface element, as (n, 3) arrays."""
    out = []
    for ext in surface.iter("{*}exterior"):
        for pl in ext.iter("{*}posList"):
            pts = np.array(pl.text.split(), dtype=float).reshape(-1, 3)
            if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
                pts = pts[:-1]                     # GML repeats the first point at the end
            if len(pts) >= 3:
                out.append(pts)
    return out


def addresses(b):
    """(street, number) pairs. LGL writes numbers as '52, null' (number, empty suffix)."""
    out = []
    for t in b.iter("{*}Thoroughfare"):
        name = next((e.text for e in t.iter("{*}ThoroughfareName")), None)
        raw = next((e.text for e in t.iter("{*}ThoroughfareNumber")), None) or ""
        parts = [p.strip() for p in raw.split(",") if p.strip() and p.strip() != "null"]
        if name:
            out.append((name, " ".join(parts)))
    return out


def read_building(b):
    """Geometry and attributes of one bldg:Building (including its BuildingParts)."""
    surfaces = {}
    interior = 0
    for kind in ("RoofSurface", "WallSurface", "GroundSurface"):
        surfaces[kind] = [r for s in b.iter("{*}" + kind) for r in rings(s)]
        interior += sum(1 for s in b.iter("{*}" + kind) for _ in s.iter("{*}interior"))
    address = sorted({f"{s} {n}".strip() for s, n in addresses(b)})
    heights = [float(e.text) for e in b.iter("{*}measuredHeight") if e.text]
    return {
        "id": b.get("{http://www.opengis.net/gml}id"),
        "surfaces": surfaces,
        "roof_types": [e.text for e in b.iter("{*}roofType")],
        "height": max(heights) if heights else None,
        "address": address,
        "interior_rings": interior,
    }


def footprint(bld):
    """2D footprint: union of the ground surfaces. Building parts often do not touch exactly,
    so hairline gaps (< 10 cm) between parts are closed; mitre joins keep the corners sharp."""
    ground = [Polygon(r[:, :2]).buffer(0) for r in bld["surfaces"]["GroundSurface"]]
    if ground:
        u = shapely.union_all(ground)
        return u.buffer(0.05, join_style="mitre").buffer(-0.05, join_style="mitre")
    pts = [p for k in bld["surfaces"].values() for r in k for p in r[:, :2]]
    return MultiPoint(pts).convex_hull


def find_anchor_centre(files):
    found = []
    for path in files:
        for _, b in etree.iterparse(path, tag="{*}Building"):
            if any(s in ANCHORS and n in ANCHORS[s] for s, n in addresses(b)):
                bld = read_building(b)
                c = footprint(bld).centroid
                street = next(s for s, n in addresses(b) if s in ANCHORS)
                found.append((street, c.x, c.y, ", ".join(bld["address"])))
            b.clear()
    if not found:
        raise SystemExit("Anchor addresses not found; pass --centre E N.")
    for _, x, y, a in found:
        print(f"  anchor {a}: E {x:.1f} N {y:.1f}")
    # Midpoint of the two anchor buildings (average each street first, so the
    # four-part Mies block does not outweigh the double house)
    groups = [[(x, y) for s, x, y, _ in found if s == street] for street in ANCHORS]
    means = [np.mean(g, axis=0) for g in groups if g]
    return tuple(float(v) for v in np.mean(means, axis=0))


def load_buildings(files, centre, radius):
    cx, cy = centre
    here = Point(cx, cy)
    selected, ground_pts = [], []
    for path in files:
        x0, y0, x1, y1 = envelope(path)
        if x1 < cx - radius - 50 or x0 > cx + radius + 50 or y1 < cy - radius - 50 or y0 > cy + radius + 50:
            continue
        for _, b in etree.iterparse(path, tag="{*}Building"):
            bld = read_building(b)
            b.clear()
            if not any(bld["surfaces"].values()):
                continue
            fp = footprint(bld)
            d = fp.distance(here)
            if d <= radius + 60:                   # a little wider: support points for the terrain
                ground_pts += [p for r in bld["surfaces"]["GroundSurface"] for p in r]
            if d <= radius:
                bld["footprint"] = fp
                selected.append(bld)
    return selected, np.array(ground_pts)


# ---------------------------------------------------------------------------
# Blender scene
# ---------------------------------------------------------------------------
def clear_scene():
    for obj in list(bpy.data.objects):        # never read_factory_settings(): it removes Bonsai
        bpy.data.objects.remove(obj, do_unlink=True)


def material(name, colour, roughness=0.8):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = (*colour, 1)
    return mat


def add_building(bld, origin, mats, collection):
    """One object per building: walls white, roofs light grey (so roof forms read clearly)."""
    verts, faces, mat_index = [], [], []
    for kind, idx in (("WallSurface", 0), ("RoofSurface", 1)):
        for ring in bld["surfaces"][kind]:
            start = len(verts)
            verts += (ring - origin).tolist()
            faces.append(list(range(start, start + len(ring))))
            mat_index.append(idx)
    if not faces:
        return None
    mesh = bpy.data.meshes.new(bld["id"])
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mats["wall"])
    mesh.materials.append(mats["roof"])
    for poly, m in zip(mesh.polygons, mat_index):
        poly.material_index = m
    bm = bmesh.new()                           # weld shared corners so shading is smooth
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.005)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(", ".join(bld["address"]) or bld["id"], mesh)
    obj["gml_id"] = bld["id"]
    obj["roof_type"] = ", ".join(ROOF_TYPES.get(r, r) for r in bld["roof_types"])
    if bld["height"] is not None:
        obj["measured_height_m"] = bld["height"]
    obj["address"] = "; ".join(bld["address"])
    collection.objects.link(obj)
    return obj


def ground_height(query_xy, points, origin, k=24, power=1.5):
    """Estimated ground height (local z) at local xy points: inverse distance weighting of the
    k nearest LoD2 ground points. Many neighbours and a low power give a smooth surface."""
    src = points[:, :2] - origin[:2]
    z = np.empty(len(query_xy))
    for i in range(0, len(query_xy), 2000):             # chunked to keep memory small
        q = query_xy[i:i + 2000]
        d = np.hypot(q[:, None, 0] - src[None, :, 0], q[:, None, 1] - src[None, :, 1])
        idx = np.argpartition(d, k, axis=1)[:, :k]
        w = 1.0 / np.maximum(np.take_along_axis(d, idx, axis=1), 1.0) ** power
        z[i:i + 2000] = (w * points[idx, 2]).sum(1) / w.sum(1)
    return z - origin[2]


def add_terrain(points, centre, radius, origin, mat, spacing=4.0, margin=30.0, smooth_passes=4):
    """Approximate ground on a disc: a regular grid with heights estimated from the buildings'
    ground heights, then smoothed. LoD2 has no terrain between buildings, so this is an
    estimate, not a terrain model; far from buildings it is only a rough guess."""
    r = radius + margin
    n = int(2 * r / spacing) + 1
    gx, gy = np.meshgrid(np.linspace(-r, r, n), np.linspace(-r, r, n))
    inside = np.hypot(gx, gy) <= r + spacing * 0.75     # keep a ring of cells just past the disc
    heights = np.full(gx.shape, np.nan)
    heights[inside] = ground_height(np.column_stack([gx[inside], gy[inside]]), points, origin)
    for _ in range(smooth_passes):                      # 3 x 3 mean, ignoring cells outside the disc
        padded = np.pad(heights, 1, constant_values=np.nan)
        stack = np.stack([padded[1 + di:n + 1 + di, 1 + dj:n + 1 + dj]
                          for di in (-1, 0, 1) for dj in (-1, 0, 1)])
        heights = np.where(inside, np.nanmean(stack, axis=0), np.nan)
    heights -= 0.15                                     # a little below the buildings' ground
    verts, index, faces = [], -np.ones(gx.shape, dtype=int), []
    for (i, j), h in np.ndenumerate(heights):
        if not np.isnan(h):
            x, y = gx[i, j], gy[i, j]
            if math.hypot(x, y) > r:                    # pull the outer ring onto a clean circle
                s = r / math.hypot(x, y)
                x, y = x * s, y * s
            index[i, j] = len(verts)
            verts.append((x, y, h))
    for i in range(n - 1):
        for j in range(n - 1):
            q = [index[i, j], index[i, j + 1], index[i + 1, j + 1], index[i + 1, j]]
            if min(q) >= 0:
                faces.append(q)
    grid = (np.linspace(-r, r, n), np.linspace(-r, r, n), heights)
    mesh = bpy.data.meshes.new("Terrain (approximate)")
    mesh.from_pydata(verts, [], faces)
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.materials.append(mat)
    obj = bpy.data.objects.new("Terrain (approximate, from LoD2 ground heights)", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return grid


def load_dgm(centre, half_size):
    """Real terrain: LGL DGM1 points (1 m cell centres) in a square around the centre.

    Returns a regular grid (x axis, y axis, heights in m above sea level, rows = y) or
    None if the DGM files do not cover the whole square.
    """
    cx, cy = centre
    x0, x1, y0, y1 = cx - half_size, cx + half_size, cy - half_size, cy + half_size
    chunks = []
    for path in sorted(glob.glob(os.path.join(DGM_DIR, "*", "*", "*.xyz"))):
        # File names carry the 1 km tile's lower-left corner in km: dgm1_32_<E>_<N>_1_bw_<year>
        e_km, n_km = (int(v) for v in os.path.basename(path).split("_")[2:4])
        if e_km * 1000 > x1 or (e_km + 1) * 1000 < x0 or n_km * 1000 > y1 or (n_km + 1) * 1000 < y0:
            continue
        pts = np.fromfile(path, sep=" ").reshape(-1, 3)
        keep = (pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)
        chunks.append(pts[keep])
        print(f"  DGM1 {os.path.basename(path)}: {keep.sum():,} points used")
    if not chunks:
        return None
    pts = np.vstack(chunks)
    xs, ys = np.unique(pts[:, 0]), np.unique(pts[:, 1])
    heights = np.full((len(ys), len(xs)), np.nan)
    heights[np.searchsorted(ys, pts[:, 1]), np.searchsorted(xs, pts[:, 0])] = pts[:, 2]
    if np.isnan(heights).any() or xs[0] > x0 + 1 or xs[-1] < x1 - 1 or ys[0] > y0 + 1 or ys[-1] < y1 - 1:
        print("  DGM1 does not cover the whole area")
        return None
    return xs, ys, heights


def add_dgm_terrain(dgm, origin, radius, mat):
    """Mesh from the DGM1 grid at full 1 m resolution, on a disc, in local coordinates."""
    xs, ys, heights = dgm
    lx, ly = xs - origin[0], ys - origin[1]
    gx, gy = np.meshgrid(lx, ly)
    inside = np.hypot(gx, gy) <= radius + TERRAIN_MARGIN
    index = np.full(gx.shape, -1)
    index[inside] = np.arange(inside.sum())
    verts = np.column_stack([gx[inside], gy[inside], heights[inside] - origin[2]])
    a, b, c, d = index[:-1, :-1], index[:-1, 1:], index[1:, 1:], index[1:, :-1]
    ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
    faces = np.column_stack([a[ok], b[ok], c[ok], d[ok]])
    mesh = bpy.data.meshes.new("Terrain DGM1")
    mesh.from_pydata(verts.tolist(), [], faces.tolist())
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.materials.append(mat)
    obj = bpy.data.objects.new("Terrain (LGL DGM1, 1 m grid)", mesh)
    bpy.context.scene.collection.objects.link(obj)
    print(f"  terrain mesh: {len(verts):,} vertices, {len(faces):,} faces")
    return lx, ly, heights - origin[2]


def compare_grounds(buildings, grid, origin):
    """How far each building's LoD2 ground height is from the DGM1 at its ground points."""
    diffs = []
    for b in buildings:
        g = np.vstack(b["surfaces"]["GroundSurface"]) if b["surfaces"]["GroundSurface"] else None
        if g is None:
            continue
        dgm = sample_grid(grid, g[:, :2] - origin[:2])
        diffs.append(float(np.median(g[:, 2] - origin[2] - dgm)))
    d = np.abs(diffs)
    print(f"LoD2 ground vs DGM1 at {len(diffs)} buildings: median |diff| {np.median(d):.2f} m, "
          f"90th percentile {np.percentile(d, 90):.2f} m, max {d.max():.2f} m")


def sample_grid(grid, xy):
    """Bilinear height of a terrain grid (x axis, y axis, heights; rows = y) at local xy points."""
    xaxis, yaxis, heights = grid
    # clamp to the grid so points just outside get the edge height instead of an error
    fx = np.clip((xy[:, 0] - xaxis[0]) / (xaxis[1] - xaxis[0]), 0, len(xaxis) - 1.001)
    fy = np.clip((xy[:, 1] - yaxis[0]) / (yaxis[1] - yaxis[0]), 0, len(yaxis) - 1.001)
    j, i = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - j, fy - i
    h = lambda a, b: heights[a, b]
    return ((1 - tx) * (1 - ty) * h(i, j) + tx * (1 - ty) * h(i, j + 1)
            + (1 - tx) * ty * h(i + 1, j) + tx * ty * h(i + 1, j + 1))


def add_radius_ring(radius, grid, mat, segments=256):
    """Thin line at the selection radius, laid on the (smoothed) terrain."""
    a = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    xy = np.column_stack([radius * np.cos(a), radius * np.sin(a)])
    z = sample_grid(grid, xy) + 0.5
    curve = bpy.data.curves.new(f"Selection radius {radius:.0f} m", "CURVE")
    curve.dimensions, curve.bevel_depth = "3D", 0.4
    spline = curve.splines.new("POLY")
    spline.points.add(segments - 1)
    for p, (x, y), h in zip(spline.points, xy, z):
        p.co = (x, y, h, 1)
    spline.use_cyclic_u = True
    ring = bpy.data.objects.new(curve.name, curve)
    ring.data.materials.append(mat)
    ring.visible_shadow = False
    bpy.context.scene.collection.objects.link(ring)
    return ring


def setup_render(radius, centre_ground_local):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    scene.cycles.device = "GPU" if any(d.type == "OPTIX" for d in prefs.devices) else "CPU"
    scene.cycles.samples = 128
    scene.cycles.use_denoising, scene.cycles.denoiser = True, "OPTIX"
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.view_settings.view_transform = "AgX"

    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.62, 0.72, 0.88, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    scene.world = world

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy, sun.data.angle = 4.0, math.radians(1.0)
    sun.rotation_euler = (math.radians(50), 0, math.radians(-130))   # from the south-west
    scene.collection.objects.link(sun)

    # Aerial camera from the south-south-west, 48 degrees down, framing the whole radius
    cam = bpy.data.objects.new("Camera aerial", bpy.data.cameras.new("Camera aerial"))
    cam.data.lens = 35
    dist = radius * 3.6
    az, el = math.radians(200), math.radians(48)
    target = Vector((0, 0, centre_ground_local))
    cam.location = target + dist * Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = 5000
    scene.collection.objects.link(cam)
    scene.camera = cam

    # Credit burned into the image (Blender's "stamp"), nothing else from the stamp
    r = scene.render
    r.use_stamp = True
    for flag in ("date", "time", "render_time", "frame", "frame_range", "memory", "hostname",
                 "camera", "lens", "scene", "marker", "filename", "sequencer_strip", "note"):
        if hasattr(r, f"use_stamp_{flag}"):
            setattr(r, f"use_stamp_{flag}", False)
    r.use_stamp_note = True
    terrain = "DGM1 terrain" if "DGM1" in scene.get("terrain", "") else "estimated terrain"
    r.stamp_note_text = (f"Weissenhofsiedlung, Stuttgart – LoD2 buildings within {radius:.0f} m, "
                         f"{terrain}  ·  {CREDIT}")
    r.stamp_font_size = 22
    r.stamp_foreground = (1, 1, 1, 1)
    r.stamp_background = (0, 0, 0, 0.55)


def build_scene():
    """Buildings, terrain, ring, lights, camera and credit; returns what other scripts need."""
    radius = (arg("--radius") or [150.0])[0]
    files = gml_files()
    print(f"{len(files)} CityGML files in data/lod2")
    centre = tuple(arg("--centre", 2) or find_anchor_centre(files))
    print(f"Centre E {centre[0]:.1f} N {centre[1]:.1f}, radius {radius:.0f} m")

    buildings, ground_pts = load_buildings(files, centre, radius)
    origin_h = float(ground_pts[:, 2].min())
    origin = np.array([centre[0], centre[1], origin_h])

    clear_scene()
    scene = bpy.context.scene
    scene["crs"] = "EPSG:25832 (ETRS89 / UTM 32N), heights DHHN2016"
    scene["origin_E"], scene["origin_N"], scene["origin_H"] = centre[0], centre[1], origin_h
    scene["source"] = CREDIT
    mats = {"wall": material("LoD2 walls (white)", (0.80, 0.80, 0.78)),
            "roof": material("LoD2 roofs (light grey)", (0.55, 0.55, 0.55)),
            "terrain": material("Terrain", (0.16, 0.18, 0.14), 0.95),
            "ring": material("Selection radius", (0.75, 0.20, 0.10), 0.6)}
    col = bpy.data.collections.new(f"LoD2 buildings within {radius:.0f} m")
    scene.collection.children.link(col)
    objs = [o for o in (add_building(b, origin, mats, col) for b in buildings) if o]

    # Terrain: real DGM1 if it covers the area, otherwise the estimate from LoD2 ground heights
    dgm = load_dgm(centre, radius + TERRAIN_MARGIN + 2)
    if dgm is not None:
        grid = add_dgm_terrain(dgm, origin, radius, mats["terrain"])
        scene["terrain"] = "LGL DGM1, 1 m grid (same CRS, height datum and local origin as LoD2)"
        compare_grounds(buildings, grid, origin)
    else:
        print("WARNING: no DGM1 coverage; using terrain estimated from LoD2 ground heights")
        grid = add_terrain(ground_pts, centre, radius, origin, mats["terrain"])
        scene["terrain"] = "estimated from LoD2 building ground heights (not measured)"

    # Ground height at the centre, for the camera target
    centre_ground = float(sample_grid(grid, np.zeros((1, 2)))[0])
    add_radius_ring(radius, grid, mats["ring"])

    roof_counts = Counter(ROOF_TYPES.get(r, r) for b in buildings for r in (b["roof_types"] or ["(none)"]))
    heights = [b["height"] for b in buildings if b["height"] is not None]
    print(f"Imported {len(objs)} buildings; roof types {dict(roof_counts)}")
    print(f"Measured heights {min(heights):.1f}-{max(heights):.1f} m; ground {origin_h:.1f}-"
          f"{ground_pts[:, 2].max():.1f} m above sea level; interior rings skipped: "
          f"{sum(b['interior_rings'] for b in buildings)}")

    setup_render(radius, centre_ground)
    return {"centre": centre, "radius": radius, "origin": origin, "buildings": buildings,
            "objects": objs, "grid": grid, "materials": mats, "centre_ground": centre_ground}


def main():
    build_scene()
    scene = bpy.context.scene
    if arg("--preview", 0):
        scene.render.resolution_percentage, scene.cycles.samples = 25, 16
    if not arg("--no-render", 0):
        scene.render.filepath = PNG_PATH
        os.makedirs(os.path.dirname(PNG_PATH), exist_ok=True)
        bpy.ops.render.render(write_still=True)
        print(f"Saved {os.path.relpath(PNG_PATH, PROJECT_DIR)}")
    scene.render.resolution_percentage, scene.cycles.samples = 100, 128
    scene.render.filepath = "//../renders/lod2_weissenhof_overview.png"
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    print(f"Saved {os.path.relpath(BLEND_PATH, PROJECT_DIR)}")


if __name__ == "__main__":
    main()

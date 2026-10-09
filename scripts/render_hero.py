"""Hero render of the Weissenhofsiedlung for a general audience.

Run from the project root (needs the Bonsai extension: lxml, shapely, Pillow):
    blender --background --python scripts/render_hero.py
Options after "--": --preview (quarter resolution, few samples), --no-render (only save .blend)

Builds the LoD2 scene with import_lod2.build_scene() (same buildings, DGM1 terrain and local
origin), drapes the DOP20 orthophoto on an extended terrain, gives the 1927 estate buildings a
warm "hero" material and everything else a light stone, lights it with a warm late-afternoon
sun and renders a 3/4 aerial view with only the LGL credit.

Outputs: renders/weissenhof_hero.png, models/weissenhof_hero.blend
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_lod2 as L  # noqa: E402
import render_dop20 as D  # noqa: E402

PROJECT_DIR = L.PROJECT_DIR
OUT_PNG = os.path.join(PROJECT_DIR, "renders", "weissenhof_hero.png")
OUT_BLEND = os.path.join(PROJECT_DIR, "models", "weissenhof_hero.blend")
HERO_CROP = os.path.join(PROJECT_DIR, "data", "dop20", "dop20_weissenhof_hero_crop.png")

# The surviving buildings of the 1927 Weissenhofsiedlung, by address (architect: addresses).
# Verified by the user against the Weissenhofmuseum's building list
# (weissenhofmuseum.de/en/siedlung/), 2026-10-03.
WEISSENHOF_1927 = {
    "Ludwig Mies van der Rohe": [("Am Weißenhof", "16 18 20")],
    "Le Corbusier & Pierre Jeanneret (double house)": [("Rathenaustraße", "1 3")],
    "Le Corbusier (single house)": [("Bruckmannweg", "2")],
    "J. J. P. Oud": [("Pankokweg", "1 3 5 7 9")],
    "Mart Stam": [("Am Weißenhof", "24 26 28")],
    "Hans Scharoun": [("Hölzelweg", "1")],
    "Peter Behrens": [("Am Weißenhof", "30 32"), ("Hölzelweg", "3 5")],
    "Josef Frank": [("Rathenaustraße", "13 15")],
    "Victor Bourgeois": [("Friedrich-Ebert-Straße", "118")],
    "Adolf Gustav Schneck": [("Bruckmannweg", "1"), ("Friedrich-Ebert-Straße", "114")],
}
CONTEXT_RADIUS = 300.0          # neighbouring LoD2 buildings shown around the estate, m
TERRAIN_RADIUS = 330.0          # DGM1 + orthophoto extent, so no edge shows in the shot
SUN_AZIMUTH, SUN_ELEVATION = 245.0, 22.0     # late afternoon, from the west-south-west
RESOLUTION = (3840, 2160)
SAMPLES = 768


def arg(name):
    return name in (sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])


def is_hero(addresses):
    for addr in addresses:
        for entries in WEISSENHOF_1927.values():
            for street, numbers in entries:
                if addr.startswith(street + " ") and set(addr[len(street) + 1:].split()) & set(numbers.split()):
                    return True
    return False


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
def stone_material(name, colour, roughness=0.55, emission=0.0, bump=0.06):
    """Matte architectural material with a very fine bump, so walls catch the light softly."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*colour, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 40.0
    noise.inputs["Detail"].default_value = 6.0
    b = nt.nodes.new("ShaderNodeBump")
    b.inputs["Strength"].default_value = bump
    nt.links.new(noise.outputs["Fac"], b.inputs["Height"])
    nt.links.new(b.outputs["Normal"], bsdf.inputs["Normal"])
    mat.diffuse_color = (*colour, 1)
    return mat


def ground_material(image_path):
    """The orthophoto mostly as captured (emission), plus a diffuse part so the 3D buildings
    cast soft shadows onto it. Note: the photo has its own baked-in shadows from the flight."""
    mat = bpy.data.materials.new("DOP20 ground (hero)")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(image_path)
    tex.interpolation, tex.extension = "Cubic", "EXTEND"
    diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 0.55
    add = nt.nodes.new("ShaderNodeAddShader")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    for target in (diffuse.inputs["Color"], emit.inputs["Color"]):
        nt.links.new(tex.outputs["Color"], target)
    nt.links.new(diffuse.outputs["BSDF"], add.inputs[0])
    nt.links.new(emit.outputs["Emission"], add.inputs[1])
    nt.links.new(add.outputs["Shader"], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Light, camera, credit
# ---------------------------------------------------------------------------
def setup_light():
    scene = bpy.context.scene
    for o in [o for o in bpy.data.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(o, do_unlink=True)
    sun = bpy.data.objects.new("Sun (late afternoon)", bpy.data.lights.new("Sun (late afternoon)", "SUN"))
    sun.data.energy, sun.data.angle = 4.2, math.radians(1.8)          # soft-edged shadows
    sun.data.color = (1.0, 0.82, 0.62)                                # warm
    # Blender sun shines along its -Z axis; this points it from SUN_AZIMUTH at SUN_ELEVATION
    sun.rotation_euler = (math.radians(90 - SUN_ELEVATION), 0, math.radians(180 - SUN_AZIMUTH))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new("Late afternoon sky")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.55, 0.66, 0.86, 1)          # cool sky fill for the shade
    bg.inputs["Strength"].default_value = 0.65
    scene.world = world


def setup_camera(centre_ground):
    scene = bpy.context.scene
    cam = bpy.data.objects.new("Camera hero", bpy.data.cameras.new("Camera hero"))
    cam.data.lens, cam.data.clip_end = 45, 3000
    az, el, dist = math.radians(205), math.radians(36), 400.0       # from the south-south-west
    target = Vector((0, 8, centre_ground + 4))
    cam.location = target + dist * Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def setup_render(preview):
    scene = bpy.context.scene
    scene.render.use_stamp = False
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 25 if preview else 100
    scene.cycles.samples = 64 if preview else SAMPLES
    scene.cycles.use_adaptive_sampling, scene.cycles.adaptive_threshold = True, 0.005
    scene.cycles.use_denoising, scene.cycles.denoiser = True, "OPTIX"
    scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    scene.view_settings.view_transform, scene.view_settings.look = "AgX", "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0.15


def add_credit(png):
    img = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    size = max(14, img.height // 80)
    try:
        font = ImageFont.truetype("segoeui.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    text = L.CREDIT
    w = d.textlength(text, font=font)
    x, y = img.width - w - size * 1.5, img.height - size * 2.2
    d.text((x + 1, y + 1), text, fill=(0, 0, 0, 110), font=font)
    d.text((x, y), text, fill=(255, 255, 255, 215), font=font)
    img.save(png)


def main():
    preview = arg("--preview")
    L.TERRAIN_MARGIN = TERRAIN_RADIUS - 150.0          # extend the DGM1 terrain for this shot
    ctx = L.build_scene()
    origin, centre = ctx["origin"], ctx["centre"]
    scene = bpy.context.scene
    for o in [o for o in bpy.data.objects if o.name.startswith("Selection radius")]:
        bpy.data.objects.remove(o, do_unlink=True)

    # Neighbouring LoD2 buildings beyond 150 m as context
    inside = {b["id"] for b in ctx["buildings"]}
    wider, _ = L.load_buildings(L.gml_files(), centre, CONTEXT_RADIUS)
    context_col = bpy.data.collections.new("LoD2 context (150-300 m)")
    scene.collection.children.link(context_col)
    context = [L.add_building(b, origin, ctx["materials"], context_col) for b in wider if b["id"] not in inside]

    # Materials: warm hero for the 1927 estate, light stone for everything else
    stone = (stone_material("Stone walls", (0.80, 0.78, 0.73)), stone_material("Stone roofs", (0.64, 0.62, 0.58)))
    hero = (stone_material("Weissenhof 1927 walls", (0.93, 0.70, 0.47), emission=0.04),
            stone_material("Weissenhof 1927 roofs", (0.82, 0.58, 0.40), emission=0.03))
    n_hero, found = 0, set()
    for b, o in zip(ctx["buildings"], ctx["objects"]):
        mats = hero if is_hero(b["address"]) else stone
        if mats is hero:
            n_hero += 1
            found.update(b["address"])
        for i, m in enumerate(mats):
            o.data.materials[i] = m
    for o in context:
        if o is not None:
            for i, m in enumerate(stone):
                o.data.materials[i] = m
    print(f"Hero (1927 estate) buildings: {n_hero}: {sorted(found)}")
    # Every listed address: found within the radius or not?
    here = L.Point(*centre)
    for street, numbers in [e for entries in WEISSENHOF_1927.values() for e in entries]:
        for num in numbers.split():
            hits = [b for b in ctx["buildings"] if any(a.startswith(street + " ") and num in a[len(street) + 1:].split()
                                                       for a in b["address"])]
            where = ", ".join(f"{b['footprint'].distance(here):.0f} m" for b in hits) or "NOT within radius"
            print(f"  {street} {num}: {where}")
    print(f"Context buildings 150-{CONTEXT_RADIUS:.0f} m: {sum(1 for o in context if o)}")

    # Orthophoto on the extended terrain
    D.CROP_PNG = HERO_CROP
    crop = D.build_mosaic(centre, TERRAIN_RADIUS + 5)
    terrain = next(o for o in bpy.data.objects if o.name.startswith("Terrain (LGL DGM1"))
    D.drape_photo(terrain, origin, crop)
    terrain.data.materials[0] = ground_material(crop[0])

    setup_light()
    cam = setup_camera(ctx["centre_ground"])
    setup_render(preview)
    if not arg("--no-render"):
        scene.render.filepath = OUT_PNG
        bpy.ops.render.render(write_still=True)
        add_credit(OUT_PNG)
        print(f"Saved {os.path.relpath(OUT_PNG, PROJECT_DIR)}")
    scene.render.resolution_percentage, scene.cycles.samples = 100, SAMPLES
    scene.render.filepath = "//../renders/weissenhof_hero.png"
    bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
    print(f"Saved {os.path.relpath(OUT_BLEND, PROJECT_DIR)}")


if __name__ == "__main__":
    main()

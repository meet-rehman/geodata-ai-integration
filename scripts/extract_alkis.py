"""Extract ALKIS parcels (AX_Flurstueck) and building outlines (AX_Gebaeude) around a point.

Run from the project root (needs the Bonsai extension, which provides lxml and shapely):
    blender --background --python scripts/extract_alkis.py
Options after "--":
    --centre E N     centre in EPSG:25832 (default: Weissenhofsiedlung, as in import_lod2.py)
    --half-size M    half width of the square to keep, metres (default 210)

Streams data/ALKIS.zip (NAS XML, ~1.7 GB for all of Stuttgart) without unpacking it and writes
    data/alkis/alkis_flurstuecke_weissenhof.geojson
    data/alkis/alkis_gebaeude_weissenhof.geojson
    data/alkis/alkis_bauwerke_weissenhof.geojson   (other structures: canopies, carports, ...)
in EPSG:25832. ALKIS building outlines are the source of LGL's "Hausumringe" product.
"""
import json
import math
import os
import sys
import time
import zipfile

from lxml import etree
from shapely.geometry import MultiPolygon, Polygon, box, mapping

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP_PATH = os.path.join(PROJECT_DIR, "data", "ALKIS.zip")
OUT_DIR = os.path.join(PROJECT_DIR, "data", "alkis")
DEFAULT_CENTRE = (513025.2, 5405261.3)      # same centre as import_lod2.py
WFS_MEMBER = "{http://www.opengis.net/wfs/2.0}member"
# Parcels, buildings, and "other structures" (canopies, carports, walls, ...). LoD2 models some
# structures as buildings, but they are not AX_Gebaeude and so not part of the Hausumringe.
KEEP = {"AX_Flurstueck", "AX_Gebaeude", "AX_SonstigesBauwerkOderSonstigeEinrichtung"}


def arg(name, n=1):
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if name not in args:
        return None
    i = args.index(name)
    return [float(v) for v in args[i + 1:i + 1 + n]]


def local(tag):
    return tag.rsplit("}", 1)[-1]


def arc_points(p0, p1, p2, steps=8):
    """Densify a circular arc given by start, middle and end point."""
    (x1, y1), (x2, y2), (x3, y3) = p0, p1, p2
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return [p0, p1, p2]
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (p0, p1, p2))
    # go from a1 to a3 in the direction that passes a2
    def norm(a):
        return a % (2 * math.pi)
    ccw = norm(a2 - a1) < norm(a3 - a1)
    span = norm(a3 - a1) if ccw else -norm(a1 - a3)
    return [(ux + r * math.cos(a1 + span * i / steps), uy + r * math.sin(a1 + span * i / steps))
            for i in range(steps + 1)]


def ring_coords(ring):
    """Coordinates of a gml:Ring / LinearRing (LineStringSegments and Arcs) as (x, y) tuples."""
    pts = []
    for seg in ring.iter("{*}LineStringSegment", "{*}Arc", "{*}ArcString", "{*}LinearRing"):
        for pl in seg.iter("{*}posList"):
            v = [float(t) for t in pl.text.split()]
            seg_pts = list(zip(v[0::2], v[1::2]))
            if local(seg.tag) in ("Arc", "ArcString"):
                dense = []
                for i in range(0, len(seg_pts) - 2, 2):
                    dense += arc_points(*seg_pts[i:i + 3])[(1 if dense else 0):]
                seg_pts = dense
            pts += seg_pts[1:] if pts and seg_pts and pts[-1] == seg_pts[0] else seg_pts
    return pts


def geometry(feature):
    polys = []
    for patch in feature.iter("{*}PolygonPatch", "{*}Polygon"):
        ext = next(patch.iter("{*}exterior"), None)
        if ext is None:
            continue
        shell = ring_coords(ext)
        holes = [ring_coords(i) for i in patch.iter("{*}interior")]
        if len(shell) >= 3:
            polys.append(Polygon(shell, [h for h in holes if len(h) >= 3]).buffer(0))
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon([p for g in polys for p in getattr(g, "geoms", [g])])


def text(feature, name):
    e = next(feature.iter("{*}" + name), None)
    return e.text if e is not None and e.text else None


def attributes(feature, kind):
    props = {"gml_id": feature.get("{http://www.opengis.net/gml/3.2}id"),
             "version_begins": text(feature, "beginnt")}
    if kind == "AX_Flurstueck":
        props.update(flurstueckskennzeichen=text(feature, "flurstueckskennzeichen"),
                     amtlicheFlaeche_m2=float(text(feature, "amtlicheFlaeche") or "nan"),
                     flurnummer=text(feature, "flurnummer"))
    elif kind == "AX_Gebaeude":
        props.update(gebaeudefunktion=text(feature, "gebaeudefunktion"),
                     geschosse_oberirdisch=text(feature, "anzahlDerOberirdischenGeschosse"),
                     name=text(feature, "name"), zustand=text(feature, "zustand"))
    else:
        props.update(bauwerksfunktion=text(feature, "bauwerksfunktion"), name=text(feature, "name"))
    return props


def main():
    centre = tuple(arg("--centre", 2) or DEFAULT_CENTRE)
    half = (arg("--half-size") or [210.0])[0]
    area = box(centre[0] - half, centre[1] - half, centre[0] + half, centre[1] + half)
    found = {k: [] for k in KEEP}
    t0, seen = time.time(), 0
    with zipfile.ZipFile(ZIP_PATH) as z:
        name = next(n for n in z.namelist() if n.endswith(".xml"))
        with z.open(name) as f:
            for _, member in etree.iterparse(f, tag=WFS_MEMBER, huge_tree=True):
                seen += 1
                feature = member[0] if len(member) else None
                kind = local(feature.tag) if feature is not None else None
                if kind in KEEP:
                    # quick reject on the first coordinate pair before building the geometry
                    pl = next(feature.iter("{*}posList"), None)
                    if pl is not None:
                        x, y = (float(t) for t in pl.text.split()[:2])
                        if abs(x - centre[0]) < half + 500 and abs(y - centre[1]) < half + 500:
                            geom = geometry(feature)
                            if geom is not None and geom.intersects(area):
                                found[kind].append((geom, attributes(feature, kind)))
                member.clear()
                while member.getprevious() is not None:     # free memory as we go
                    del member.getparent()[0]
                if seen % 500000 == 0:
                    print(f"  {seen:,} features read, {time.time() - t0:.0f} s")
    print(f"Read {seen:,} features in {time.time() - t0:.0f} s")
    os.makedirs(OUT_DIR, exist_ok=True)
    for kind, fname in (("AX_Flurstueck", "alkis_flurstuecke_weissenhof.geojson"),
                        ("AX_Gebaeude", "alkis_gebaeude_weissenhof.geojson"),
                        ("AX_SonstigesBauwerkOderSonstigeEinrichtung", "alkis_bauwerke_weissenhof.geojson")):
        fc = {"type": "FeatureCollection",
              "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}},
              "features": [{"type": "Feature", "properties": p, "geometry": mapping(g)}
                           for g, p in found[kind]]}
        with open(os.path.join(OUT_DIR, fname), "w", encoding="utf-8") as out:
            json.dump(fc, out, ensure_ascii=False)
        print(f"Saved data/alkis/{fname}: {len(found[kind])} {kind}")


if __name__ == "__main__":
    main()

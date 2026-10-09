"""Read-only check of record currency: ALKIS download (NAS) vs. LGL OGC API Features (beta).

Run from the project root with Blender's Python:
    blender --background --python scripts/check_currency.py

- Version start/end ("beginnt"/"endet") for the buildings is read straight from data/ALKIS.zip
  (streamed, nothing unpacked or changed) and from the API (GET only).
- Timestamps are normalised to UTC instants; the NAS gives them with "Z", the API without a time
  zone (treated as UTC, which makes every matching record agree to the second). The calendar date
  is reported in German local time, because ALKIS stores local midnight as 23:00Z / 22:00Z.
Writes data/oaf/currency_buildings.csv (all buildings in the extract square, flagged "in_150m").
"""
import csv
import json
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone

from lxml import etree
from shapely.geometry import Point, shape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_oaf as T  # noqa: E402  (GET helper, URLs, centre)
# import_lod2 needs Blender (bpy); it is imported inside main() so the helpers above
# (parse_ts, local_date, nas_header_and_versions) can be reused outside Blender.

PROJECT_DIR = T.PROJECT_DIR
ZIP = os.path.join(PROJECT_DIR, "data", "ALKIS.zip")
CSV_OUT = os.path.join(PROJECT_DIR, "data", "oaf", "currency_buildings.csv")


def parse_ts(s):
    """'2001-08-14T23:00:00Z' or '2001-08-14T23:00:00' -> aware UTC datetime (naive = UTC)."""
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_sunday(year, month):
    d = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def local_date(dt):
    """Calendar date in Germany (CET/CEST, EU rules) for a UTC instant."""
    if dt is None:
        return ""
    start = last_sunday(dt.year, 3).replace(hour=1, tzinfo=timezone.utc)
    end = last_sunday(dt.year, 10).replace(hour=1, tzinfo=timezone.utc)
    return (dt + timedelta(hours=2 if start <= dt < end else 1)).date().isoformat()


def nas_header_and_versions(ids):
    """Header comments of the NAS file and beginnt/endet for the given object IDs."""
    found, header = {}, ""
    with zipfile.ZipFile(ZIP) as z:
        name = next(n for n in z.namelist() if n.endswith(".xml"))
        info = z.getinfo(name)
        with z.open(name) as f:
            header = f.read(2000).decode("utf-8", "replace")
        with z.open(name) as f:
            for _, m in etree.iterparse(f, tag="{http://www.opengis.net/wfs/2.0}member", huge_tree=True):
                feat = m[0] if len(m) else None
                if feat is not None:
                    fid = feat.get("{http://www.opengis.net/gml/3.2}id")
                    if fid in ids:
                        b = next(feat.iter("{*}beginnt"), None)
                        e = next(feat.iter("{*}endet"), None)
                        found[fid] = (b.text if b is not None else None, e.text if e is not None else None,
                                      etree.QName(feat).localname)
                m.clear()
                while m.getprevious() is not None:
                    del m.getparent()[0]
    return header, info, found


def main():
    import import_lod2 as L  # LoD2 addresses (Blender only)
    centre = Point(T.CENTRE)
    square = (T.CENTRE[0] - T.HALF, T.CENTRE[1] - T.HALF, T.CENTRE[0] + T.HALF, T.CENTRE[1] + T.HALF)

    # Today's API data (GET)
    api_feats, pages = T.fetch_all("gebaeude", square, limit=1000)
    api = {f["properties"]["gml_id"]: f for f in api_feats}
    print(f"API gebaeude in extract square: {len(api)} features, {[ms for _, ms in pages]} ms")
    print("API version-end attribute present:", any("ende" in k.lower() for k in api_feats[0]["properties"]))

    # Our download: geometry from the extract, versions straight from the NAS file
    with open(os.path.join(PROJECT_DIR, "data", "alkis", "alkis_gebaeude_weissenhof.geojson"), encoding="utf-8") as f:
        ours = {ft["properties"]["gml_id"]: shape(ft["geometry"]) for ft in json.load(f)["features"]}
    header, info, nas = nas_header_and_versions(set(ours))
    print(f"NAS entry date in zip: {datetime(*info.date_time)}, size {info.file_size / 1e9:.2f} GB")
    for line in re.findall(r"<!--(.*?)-->", header, re.S):
        print("NAS comment:", " ".join(line.split())[:200])
    print("NAS objects with an 'endet' (version end):", sum(1 for v in nas.values() if v[1]))

    # LoD2 addresses (LoD2 IDs = ALKIS IDs with 'L' -> '_')
    lod2, _ = L.load_buildings(L.gml_files(), T.CENTRE, T.HALF + 20)
    address = {"DEBWL" + b["id"][5:]: ", ".join(b["address"]) for b in lod2 if b["id"].startswith("DEBW_")}

    rows = []
    for gid, geom in ours.items():
        nb, ne, kind = nas.get(gid, (None, None, None))
        ab = api.get(gid, {}).get("properties", {}).get("beginn")
        t_n, t_a = parse_ts(nb), parse_ts(ab)
        diff = (t_n - t_a).days if t_n and t_a else None
        rows.append({"gml_id": gid, "address": address.get(gid, ""),
                     "distance_m": round(geom.distance(centre), 1),
                     "in_150m": geom.distance(centre) <= T.RADIUS,
                     "download_version_start_utc": t_n.isoformat() if t_n else "",
                     "api_version_start_utc": t_a.isoformat() if t_a else "",
                     "download_date_local": local_date(t_n), "api_date_local": local_date(t_a),
                     "download_version_end": ne or "", "difference_days": diff,
                     "newer": "" if not diff else ("download" if diff > 0 else "API")})

    rows.sort(key=lambda r: (not r["in_150m"], r["distance_m"]))
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {os.path.relpath(CSV_OUT, PROJECT_DIR)}")

    for label, sel in (("within 150 m", [r for r in rows if r["in_150m"]]), ("extract square", rows)):
        same = sum(1 for r in sel if r["difference_days"] == 0)
        diff = [r for r in sel if r["difference_days"]]
        missing = sum(1 for r in sel if r["difference_days"] is None)
        print(f"CUR {label}: {len(sel)} buildings, identical {same}, differ {len(diff)}, not comparable {missing}")
        for r in diff:
            print(f"CUR   differs: {r['gml_id']} {r['address'] or '(no address)'} at {r['distance_m']} m: "
                  f"download {r['download_date_local']} vs API {r['api_date_local']}, {r['newer']} newer by "
                  f"{abs(r['difference_days'])} days")
        yd = Counter(r["download_date_local"][:4] for r in sel)
        ya = Counter(r["api_date_local"][:4] for r in sel)
        years = sorted(set(yd) | set(ya))
        print(f"YEARS {label}: " + ", ".join(f"{y}: {yd[y]}/{ya[y]}" for y in years) + "  (download/API)")

    # Newest version date anywhere in the API (lower bound for its currency)
    for coll in ("gebaeude", "flurstueck"):
        data, rec = T.get(f"{T.BASE}/collections/{coll}/items?f=json&limit=3&sortby=-beginn", f"{coll} newest")
        if data:
            print(f"NEWEST {coll} in API: {[f['properties'].get('beginn') for f in data['features']]} ({rec['ms']} ms)")
        else:
            print(f"NEWEST {coll}: HTTP {rec['status']} {rec.get('error', '')[:150]}")
    errors = [r for r in T.LOG if r.get("status") != 200]
    print(f"LOG {len(T.LOG)} GET requests, {len(errors)} errors")


if __name__ == "__main__":
    main()

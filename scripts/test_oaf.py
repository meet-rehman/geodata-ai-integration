"""Test LGL's beta OGC API Features (pygeoapi) against our downloaded ALKIS extract.

Run from the project root with Blender's Python (needs shapely from the Bonsai extension):
    blender --background --python scripts/test_oaf.py

Read-only: only GET requests. Saves the API responses to data/oaf/ (new files; the downloaded
ALKIS data in data/alkis/ is only read) and prints everything notes/oaf_findings.md is based on.
"""
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import shapely
from shapely.geometry import Point, box, shape

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://ogcapi.lgl-bw.de/beta/pygeoapi"
EPSG25832 = "http://www.opengis.net/def/crs/EPSG/0/25832"
CENTRE = (513025.2, 5405261.3)
RADIUS = 150.0
HALF = 210.0                      # half size of the square our ALKIS extract covers
OUT = os.path.join(PROJECT_DIR, "data", "oaf")
LOG = []                          # one entry per request
CANOPIES = ["DEBWL5221000Bwby", "DEBWL5221000BwiO", "DEBWL5221000Bwhn", "DEBWL5221000BwiZ"]


def get(url, note=""):
    """GET a JSON document; returns (data or None, record)."""
    t0 = time.perf_counter()
    rec = {"url": url, "note": note}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/geo+json, application/json"}),
                                    timeout=120) as r:
            body = r.read()
            rec.update(status=r.status, bytes=len(body),
                       headers={k: v for k, v in r.headers.items()
                                if any(s in k.lower() for s in ("rate", "limit", "retry", "crs", "content-type"))})
            data = json.loads(body)
    except urllib.error.HTTPError as e:
        rec.update(status=e.code, error=e.read()[:300].decode("utf-8", "replace"))
        data = None
    except Exception as e:  # network errors, timeouts
        rec.update(status=None, error=repr(e))
        data = None
    rec["ms"] = round((time.perf_counter() - t0) * 1000)
    LOG.append(rec)
    return data, rec


def items_url(collection, bbox, **params):
    q = {"f": "json", "bbox": ",".join(f"{v:.1f}" for v in bbox), "bbox-crs": EPSG25832, "crs": EPSG25832}
    q.update(params)
    return f"{BASE}/collections/{collection}/items?" + urllib.parse.urlencode(q)


def fetch_all(collection, bbox, limit):
    """Follow 'next' links until the last page; returns features and per-page timings."""
    url, feats, pages = items_url(collection, bbox, limit=limit), [], []
    while url:
        data, rec = get(url, f"{collection} page {len(pages) + 1}")
        if data is None:
            raise RuntimeError(f"{collection}: page {len(pages) + 1} failed: {rec}")
        feats += data["features"]
        pages.append((data.get("numberReturned"), rec["ms"]))
        url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
        if data.get("numberReturned", 0) == 0:
            break
    return feats, pages


def probe_page_size():
    """Default page size, and what happens when asking for very large pages."""
    big = (CENTRE[0] - 1000, CENTRE[1] - 1000, CENTRE[0] + 1000, CENTRE[1] + 1000)
    result = {}
    data, rec = get(items_url("gebaeude", big), "default page size")
    result["default"] = data and data.get("numberReturned")
    for lim in (100, 1000, 5000, 10000, 50000):
        data, rec = get(items_url("gebaeude", big, limit=lim), f"limit={lim}")
        result[lim] = (data.get("numberReturned") if data else f"HTTP {rec['status']}: {rec.get('error', '')[:120]}",
                       rec["ms"], rec.get("bytes"))
    return result


def probe_filters(bbox):
    out = {}
    for label, extra in (("CQL2 filter gebaeudefunktion_id=1010", {"filter": "gebaeudefunktion_id=1010", "filter-lang": "cql2-text"}),
                         ("queryable parameter gebaeudefunktion_id=1010", {"gebaeudefunktion_id": "1010"}),
                         ("CQL2 filter gml_id IN canopies", {"filter": "gml_id IN (" + ",".join(f"'{c}'" for c in CANOPIES) + ")",
                                                              "filter-lang": "cql2-text"})):
        data, rec = get(items_url("gebaeude", bbox, limit=1000, **extra), label)
        if data is None:
            out[label] = f"HTTP {rec['status']}: {rec.get('error', '')[:160]}"
        else:
            funcs = sorted({f["properties"].get("gebaeudefunktion_id") for f in data["features"]}, key=str)
            out[label] = f"{data.get('numberReturned')} features, functions {funcs[:6]}, {rec['ms']} ms"
    return out


def load_ours(name):
    with open(os.path.join(PROJECT_DIR, "data", "alkis", name), encoding="utf-8") as f:
        return {ft["properties"]["gml_id"]: (shape(ft["geometry"]), ft["properties"]) for ft in json.load(f)["features"]}


def geom_diff(a, b):
    inter, union = a.intersection(b).area, a.union(b).area
    return {"iou": inter / union if union else 0,
            "gap": shapely.hausdorff_distance(a.boundary, b.boundary, densify=0.1),
            "darea": b.area - a.area}


def compare(ours, api_feats, area, label, attr_pairs):
    api = {}
    for f in api_feats:
        api.setdefault(f["properties"]["gml_id"], []).append((shape(f["geometry"]), f["properties"]))
    dupes = {k: len(v) for k, v in api.items() if len(v) > 1}
    api1 = {k: v[0] for k, v in api.items()}
    ours_in = {k: v for k, v in ours.items() if v[0].intersects(area)}
    only_ours, only_api = sorted(set(ours_in) - set(api1)), sorted(set(api1) - set(ours_in))
    both = sorted(set(ours_in) & set(api1))
    diffs = [geom_diff(ours_in[k][0], api1[k][0]) for k in both]
    attr_mismatch = {}
    for ours_key, api_key, conv in attr_pairs:
        bad = [k for k in both if conv(ours_in[k][1].get(ours_key)) != conv(api1[k][1].get(api_key))]
        attr_mismatch[f"{ours_key} vs {api_key}"] = (len(bad), bad[:3])
    gaps = sorted(d["gap"] for d in diffs)
    res = {"label": label, "ours": len(ours_in), "api": len(api1), "api_raw": len(api_feats), "duplicates": dupes,
           "matched": len(both), "only_ours": only_ours, "only_api": only_api,
           "gap_median": gaps[len(gaps) // 2] if gaps else None, "gap_max": gaps[-1] if gaps else None,
           "iou_min": min((d["iou"] for d in diffs), default=None),
           "darea_max": max((abs(d["darea"]) for d in diffs), default=None),
           "worst": sorted(zip(both, diffs), key=lambda t: -t[1]["gap"])[:3],
           "attr_mismatch": attr_mismatch}
    return res, api1


def report(res):
    print(f"CMP {res['label']}: ours {res['ours']}, API {res['api']} (raw {res['api_raw']}, duplicates {res['duplicates']}), "
          f"matched by gml_id {res['matched']}")
    print(f"CMP   only ours: {len(res['only_ours'])} {res['only_ours'][:6]}")
    print(f"CMP   only API:  {len(res['only_api'])} {res['only_api'][:6]}")
    print(f"CMP   geometry: max gap {res['gap_max']:.3f} m, median {res['gap_median']:.3f} m, min IoU {res['iou_min']:.5f}, "
          f"max |area diff| {res['darea_max']:.3f} m2")
    for k, d in res["worst"]:
        print(f"CMP     worst {k}: gap {d['gap']:.3f} m, IoU {d['iou']:.5f}, area diff {d['darea']:.3f} m2")
    for k, (n, ex) in res["attr_mismatch"].items():
        print(f"CMP   attribute {k}: {n} mismatches {ex}")


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"DATE {date.today().isoformat()}")
    square = (CENTRE[0] - HALF, CENTRE[1] - HALF, CENTRE[0] + HALF, CENTRE[1] + HALF)
    circle_bbox = (CENTRE[0] - RADIUS, CENTRE[1] - RADIUS, CENTRE[0] + RADIUS, CENTRE[1] + RADIUS)

    for k, v in probe_page_size().items():
        print(f"PAGE {k}: {v}")
    for k, v in probe_filters(circle_bbox).items():
        print(f"FILTER {k}: {v}")

    num = lambda v: None if v in (None, "") else round(float(v))
    func = lambda v: None if v in (None, "") else int(v)
    date10 = lambda v: (v or "")[:10]

    # Buildings: 150 m radius (the request) and the full extract square, with paging
    geb_circle, pages = fetch_all("gebaeude", circle_bbox, limit=10)
    print(f"FETCH gebaeude 150 m bbox, limit 10: {len(geb_circle)} features in {len(pages)} pages, "
          f"page times {[ms for _, ms in pages]} ms")
    geb, pages = fetch_all("gebaeude", square, limit=1000)
    print(f"FETCH gebaeude extract square, limit 1000: {len(geb)} features in {len(pages)} pages, {[ms for _, ms in pages]} ms")
    ours_geb = load_ours("alkis_gebaeude_weissenhof.geojson")
    here = Point(CENTRE)
    circle = here.buffer(RADIUS, 256)
    res, api_geb = compare(ours_geb, geb, box(*square), "gebaeude, extract square",
                           [("gebaeudefunktion", "gebaeudefunktion_id", func), ("version_begins", "beginn", date10)])
    report(res)
    # The 150 m set used in the LoD2 comparison: footprint within 150 m of the centre
    ours150 = {k: v for k, v in ours_geb.items() if v[0].distance(here) <= RADIUS}
    api150 = {k: v for k, v in api_geb.items() if v[0].distance(here) <= RADIUS}
    print(f"CMP gebaeude within 150 m: ours {len(ours150)}, API {len(api150)}, same IDs: {set(ours150) == set(api150)}, "
          f"only ours {sorted(set(ours150) - set(api150))}, only API {sorted(set(api150) - set(ours150))}")
    found = [c for c in CANOPIES if c in {f['properties']['gml_id'] for f in geb}]
    print(f"CANOPY 1610 structures in API gebaeude: {found or 'none'}")
    funcs = sorted({f["properties"]["gebaeudefunktion_id"] for f in geb})
    print(f"FUNCS gebaeudefunktion_id in API result: {funcs}")

    # Parcels
    flst, pages = fetch_all("flurstueck", square, limit=1000)
    print(f"FETCH flurstueck extract square, limit 1000: {len(flst)} features in {len(pages)} pages, {[ms for _, ms in pages]} ms")
    res, _ = compare(load_ours("alkis_flurstuecke_weissenhof.geojson"), flst, box(*square), "flurstueck, extract square",
                     [("flurstueckskennzeichen", "flurstueckskennzeichen", lambda v: (v or "").replace("_", "").strip()),
                      ("amtlicheFlaeche_m2", "amtliche_flaeche", num), ("version_begins", "beginn", date10)])
    report(res)
    sample = next(iter(load_ours("alkis_flurstuecke_weissenhof.geojson").values()))[1]["flurstueckskennzeichen"]
    api_sample = flst[0]["properties"]["flurstueckskennzeichen"] if flst else None
    print(f"FORMAT flurstueckskennzeichen ours '{sample}' vs API '{api_sample}'")

    for name, feats in (("oaf_gebaeude_weissenhof.geojson", geb), ("oaf_flurstueck_weissenhof.geojson", flst)):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": feats}, f, ensure_ascii=False)
    with open(os.path.join(OUT, "oaf_request_log.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "requests": LOG}, f, ensure_ascii=False, indent=1)
    ok = [r["ms"] for r in LOG if r.get("status") == 200]
    errors = [r for r in LOG if r.get("status") != 200]
    hdrs = {k for r in LOG for k in r.get("headers", {})}
    print(f"LOG {len(LOG)} requests, {len(errors)} errors, response time median {sorted(ok)[len(ok) // 2]} ms, "
          f"max {max(ok)} ms; headers seen: {sorted(hdrs)}")
    for r in errors:
        print(f"ERR {r['status']} {r['note']}: {r.get('error', '')[:200]}")


if __name__ == "__main__":
    main()

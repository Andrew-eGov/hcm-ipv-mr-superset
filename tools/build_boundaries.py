"""Build approximate health-district polygons for the 36 microplan districts.

Source shapes: geoBoundaries NAM ADM1 (14 regions, Natural Earth) and ADM2
(109 constituencies, NSA 2007). Namibia's health districts have no public
shapefile, so each constituency (clipped to its region) is assigned to the
nearest district seat town (geocoded via OSM Nominatim) inside that region,
then dissolved. Result is an approximation: replace data/districts.geojson
with official shapes when available - nothing else needs to change.

Outputs:
  data/districts.geojson   one feature per district, keyed by boundary_code
  data/regions.geojson     regions = union of their districts
"""
import json
import os
import sys
from pathlib import Path

import openpyxl
from shapely.geometry import shape, mapping, Point, MultiPoint
from shapely.ops import unary_union, voronoi_diagram

ROOT = Path(__file__).resolve().parent.parent
# Not committed (contains user list). Default: next to this repo; override with MICROPLAN_XLSX.
MICROPLAN = Path(os.environ.get("MICROPLAN_XLSX", ROOT.parent / "Copy of Namibia_IPV_MR_Microplan.xlsx"))

# geoBoundaries ADM1 names -> microplan regions that can claim the shape
ADM1_TO_REGIONS = {
    # Natural Earth still uses the pre-2013 Kavango/Caprivi line (20.99E), so
    # Andara (Kavango East) sits inside the old Caprivi shape.
    "Caprivi": ["Zambezi", "Kavango East"],
    "Kavango": ["Kavango East", "Kavango West"],
    "Cunene": ["Kunene"],
}

# Nominatim returned a conservancy for Nyangana; use the hospital village instead
SEAT_OVERRIDES = {"Nyangana": (-17.985, 20.735)}


def load_districts():
    wb = openpyxl.load_workbook(MICROPLAN, read_only=True, data_only=True)
    rows = []
    for i, r in enumerate(wb["Boundary List"].iter_rows(values_only=True)):
        if i < 2 or not r or not r[3]:
            continue
        rows.append({"region": r[1], "district": r[2], "boundary_code": r[3]})
    return rows


def main():
    districts = load_districts()
    seats = json.load(open(ROOT / "geo_raw/seats.json"))
    for k, v in SEAT_OVERRIDES.items():
        seats[k] = [v[0], v[1], "override"]
    adm1 = json.load(open(ROOT / "geo_raw/adm1.geojson"))["features"]
    adm2 = json.load(open(ROOT / "geo_raw/adm2.geojson"))["features"]

    pieces = {d["boundary_code"]: [] for d in districts}
    for a1 in adm1:
        name = a1["properties"]["shapeName"]
        regions = ADM1_TO_REGIONS.get(name, [name])
        cands = [d for d in districts if d["region"] in regions
                 and (name != "Caprivi" or d["district"] in ("Katima Mulilo", "Andara"))]
        if not cands:
            print("WARN no districts for ADM1", name, file=sys.stderr)
            continue
        g1 = shape(a1["geometry"]).buffer(0)
        if len(cands) == 1:
            pieces[cands[0]["boundary_code"]].append(g1)
            continue
        # Voronoi partition of the region around the district seat towns
        pts = MultiPoint([(seats[d["district"]][1], seats[d["district"]][0]) for d in cands])
        cells = voronoi_diagram(pts, envelope=g1.envelope.buffer(2))
        for cell in cells.geoms:
            d = min(cands, key=lambda d: Point(seats[d["district"]][1], seats[d["district"]][0]).distance(cell.representative_point()) if not cell.contains(Point(seats[d["district"]][1], seats[d["district"]][0])) else -1)
            part = cell.intersection(g1)
            if not part.is_empty:
                pieces[d["boundary_code"]].append(part)

    feats, by_region = [], {}
    for d in districts:
        if not pieces[d["boundary_code"]]:
            print("WARN empty district", d["district"], file=sys.stderr)
            continue
        g = unary_union(pieces[d["boundary_code"]]).simplify(0.01, preserve_topology=True)
        by_region.setdefault(d["region"], []).append(g)
        lat, lon = seats[d["district"]][:2]
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {**d, "seat_lat": lat, "seat_lon": lon,
                                     "centroid_lat": g.centroid.y, "centroid_lon": g.centroid.x}})
    json.dump({"type": "FeatureCollection", "features": feats}, open(ROOT / "data/districts.geojson", "w"))
    rfeats = [{"type": "Feature", "geometry": mapping(unary_union(gs).simplify(0.01)), "properties": {"region": r}}
              for r, gs in by_region.items()]
    json.dump({"type": "FeatureCollection", "features": rfeats}, open(ROOT / "data/regions.geojson", "w"))
    print(f"{len(feats)} districts, {len(rfeats)} regions written")


if __name__ == "__main__":
    main()

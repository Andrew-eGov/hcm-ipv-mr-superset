"""Load the IPV+MR microplan + district shapes into Postgres (catalog `microplan`).

Reads ../Copy of Namibia_IPV_MR_Microplan.xlsx (Boundary List, Facilities List,
User List) and data/districts.geojson. Only roles/boundaries are taken from the
User List - names, phones and payment details are never loaded.

Tables (schema public):
  dim_district          targets, teams, centroid, seat, GeoJSON
  dim_district_polygon  one row per polygon part (deck.gl Polygon layer input)
  dim_region            region totals + GeoJSON
  dim_facility          51 stores (CMS / regional / district), mock coordinates
  dim_user              user_id, role_group, roles, boundary (no PII)
  dim_product           products, doses per vial, eligibility (WHO), wastage
  dim_campaign_day      9-19 Nov 2026, planned cumulative %
"""
import datetime as dt
import json
import os
from pathlib import Path

import openpyxl
import psycopg2
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
# Not committed (contains user list). Default: next to this repo; override with MICROPLAN_XLSX.
MICROPLAN = Path(os.environ.get("MICROPLAN_XLSX", ROOT.parent / "Copy of Namibia_IPV_MR_Microplan.xlsx"))
PG = dict(host="localhost", port=5433, user="hcm", password="hcm", dbname="microplan")

CAMPAIGN_START = dt.date(2026, 11, 9)
CAMPAIGN_DAYS = 11
# Regional store sits in the region's largest district (by U5 population)

PRODUCTS = [
    # code, name, kind, unit, doses_per_unit, min_age_m, max_age_m, wastage_pct
    ("MR", "Measles-Rubella vaccine", "VACCINE", "vial", 10, 9, 119, 5.0),
    ("IPV", "Inactivated polio vaccine (fIPV, 0.1 mL ID)", "VACCINE", "vial", 25, 4, 59, 5.0),
    ("ADS_05", "AD syringe 0.5 mL (MR)", "DEVICE", "piece", 1, None, None, 5.0),
    ("ADS_01", "AD syringe 0.1 mL (fIPV)", "DEVICE", "piece", 1, None, None, 5.0),
    ("RUP_5", "Reconstitution syringe 5 mL (MR)", "DEVICE", "piece", 1, None, None, 5.0),
]


def n(v):
    return None if v in (None, "") else float(str(v).replace(",", ""))


def main():
    wb = openpyxl.load_workbook(MICROPLAN, read_only=True, data_only=True)
    shapes = {f["properties"]["boundary_code"]: f for f in json.load(open(ROOT / "data/districts.geojson"))["features"]}
    regions_geo = {f["properties"]["region"]: f for f in json.load(open(ROOT / "data/regions.geojson"))["features"]}

    districts = []
    for i, r in enumerate(wb["Boundary List"].iter_rows(values_only=True)):
        if i < 2 or not r or not r[3]:
            continue
        f = shapes[r[3]]
        p = f["properties"]
        districts.append(dict(
            boundary_code=r[3], country=r[0], region=r[1], district=r[2],
            u5_population=n(r[4]), ipv_target=n(r[5]), mr_target=n(r[6]),
            ipv_doses_required=n(r[7]), mr_doses_required=n(r[8]),
            teams_total=n(r[9]), teams_fixed=n(r[10]), teams_temp_fixed=n(r[11]),
            teams_mobile=n(r[12]), hr_total=n(r[13]),
            seat_lat=p["seat_lat"], seat_lon=p["seat_lon"],
            centroid_lat=p["centroid_lat"], centroid_lon=p["centroid_lon"],
            geojson=json.dumps(f["geometry"]),
        ))
    dmap = {d["district"].lower(): d for d in districts}
    region_seat = {}
    for d in sorted(districts, key=lambda d: -d["u5_population"]):
        region_seat.setdefault(d["region"], d)

    facilities = []
    for i, r in enumerate(wb["Facilities List"].iter_rows(values_only=True)):
        if i < 2 or not r or not r[7]:
            continue
        code = r[5]
        if r[8] == "Central Facility":
            seat, region, district = dmap["windhoek"], None, None
        elif r[8] == "Regional Facility":
            seat, region, district = region_seat[r[2]], r[2], None
        else:
            seat, region, district = next(d for d in districts if d["boundary_code"] == code), r[2], r[4]
        facilities.append(dict(
            facility_code="FAC_" + code, facility_name=r[7], facility_type=r[8],
            level={"Central Facility": 1, "Regional Facility": 2}.get(r[8], 3),
            boundary_code=code, region=region, district=district, capacity=n(r[10]),
            # mock: store located at the seat town; replace with real coordinates
            latitude=seat["seat_lat"], longitude=seat["seat_lon"],
        ))

    users, seq = [], 0
    for i, r in enumerate(wb["User List"].iter_rows(values_only=True)):
        if i < 2 or not r or not r[5]:
            continue
        roles = [x for x in r[8:13] if x]
        if not roles:
            continue
        seq += 1
        group = ("VACCINATOR" if "DISTRIBUTOR" in roles else
                 "REGISTRAR" if roles == ["REGISTRAR"] else roles[0])
        users.append(dict(user_id=f"NAM-U-{seq:05d}", roles=",".join(roles), role_group=group,
                          boundary_code=r[5], region=r[2], district=r[4] or None,
                          employment_type=r[13]))

    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute(open(ROOT / "sql/01_microplan_schema.sql").read())

    def insert(table, rows):
        cols = list(rows[0])
        cur.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                        [tuple(x[c] for c in cols) for x in rows])

    insert("dim_district", districts)
    polys = []
    for d in districts:
        g = shape(json.loads(d["geojson"]))
        parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        for k, part in enumerate(parts):
            polys.append(dict(boundary_code=d["boundary_code"], region=d["region"], district=d["district"],
                              part_no=k, polygon=json.dumps([[list(c) for c in part.exterior.coords]])))
    insert("dim_district_polygon", polys)
    regs = {}
    for d in districts:
        x = regs.setdefault(d["region"], dict(region=d["region"], u5_population=0, ipv_target=0, mr_target=0))
        for k in ("u5_population", "ipv_target", "mr_target"):
            x[k] += d[k]
    for r in regs.values():
        r["geojson"] = json.dumps(regions_geo[r["region"]]["geometry"])
    insert("dim_region", list(regs.values()))
    insert("dim_facility", facilities)
    insert("dim_user", users)
    insert("dim_product", [dict(zip(("product_code", "product_name", "kind", "unit", "doses_per_unit",
                                     "min_age_months", "max_age_months", "planned_wastage_pct"), p)) for p in PRODUCTS])
    insert("dim_campaign_day", [dict(campaign_date=CAMPAIGN_START + dt.timedelta(days=k), day_no=k + 1,
                                     planned_cum_pct=round(100.0 * (k + 1) / CAMPAIGN_DAYS, 2))
                                for k in range(CAMPAIGN_DAYS)])
    conn.commit()
    print(f"districts={len(districts)} polygons={len(polys)} regions={len(regs)} "
          f"facilities={len(facilities)} users={len(users)}")


if __name__ == "__main__":
    main()

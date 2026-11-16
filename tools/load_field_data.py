"""Load the Zambezi MR/IPV child and stock database (field workbook) into Elasticsearch.

This replaces the synthetic HCM data. The workbook stays outside git (it is
field data); point FIELD_XLSX at it, or put it next to this repo.

Sheets -> indexes (one document per row, TOTAL rows dropped):
  Children                      -> field-child-v1     one doc per child
  Agg_MR + Stock_MR, Agg_IPV +  -> field-site-day-v1  one doc per site x date x vaccine
  Stock_IPV                                           (target, vaccinated by age group, vials)
Sites (code, type, district, coordinates) come from data/sites.csv -> Postgres dim_site.

Districts: the workbook's Cluster column is the district (owner's instruction): Katima -> Katima
Mulilo, Bukalo, Sangwali. The microplan has a single Zambezi district (Katima Mulilo), so this
loader replaces it in dim_district / dim_district_polygon with the three districts. Their shapes
are approximate: the Zambezi region split into Voronoi cells around each district's sites
(written to data/zambezi_districts.geojson for the review page).

Campaign day is computed from the date (9 Nov 2026 = day 1). The workbook's own
Campaign_Day disagrees between sheets (Children: 10 Nov = day 1; Agg/Stock: day 2),
so it is kept only as source_campaign_day for the data-quality tab.

    tools/.venv/bin/python -I tools/load_field_data.py               # workbook -> ES, sites -> Postgres
    tools/.venv/bin/python -I tools/load_field_data.py --sites-only  # sites only (real HCM ES already connected)
"""
import csv
import datetime as dt
import hashlib
import http.client
import json
import os
import sys
from pathlib import Path

import openpyxl
import psycopg2
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import voronoi_diagram

ROOT = Path(__file__).resolve().parent.parent
FIELD_XLSX = Path(os.environ.get(
    "FIELD_XLSX", ROOT.parent / "Zambezi_region_MR_IPV_child_and_stock_database_VAA_updated.xlsx"))
ES_HOST, ES_PORT = os.environ.get("ES_HOST", "localhost"), int(os.environ.get("ES_PORT", "9200"))
PG = dict(host="localhost", port=5433, user="hcm", password="hcm", dbname="microplan")
CAMPAIGN_START = dt.date(2026, 11, 9)
REGION, MICROPLAN_DISTRICT = "Zambezi", "Katima Mulilo"   # the microplan's only Zambezi district
# Workbook Cluster -> district, and boundary codes (Katima Mulilo keeps its microplan code; the two
# new codes follow the microplan pattern and are assigned by this dashboard until official ones exist)
DISTRICTS = {"Katima": ("Katima Mulilo", "NAMIBIA_NA_14_01_KATIMA_MULILO"),
             "Bukalo": ("Bukalo", "NAMIBIA_NA_14_02_BUKALO"),
             "Sangwali": ("Sangwali", "NAMIBIA_NA_14_03_SANGWALI")}
CHILD_IDX, SITE_IDX, SYNC_IDX = "field-child-v1", "field-site-day-v1", "field-user-sync-v1"
# Synthetic HCM indexes from tools/legacy/generate_mock.py - removed so nothing synthetic remains
LEGACY_IDX = ["project-task-index-v1", "individual-index-v1", "household-index-v1", "stock-index-v1",
              "service-task-v1", "pgr-services-index-v1", "downsync-index-v1", "aefi-index-v1"]

KW, INT = {"type": "keyword"}, {"type": "integer"}
SITE_FIELDS = dict(vaccine=KW, event_date={"type": "date"}, campaign_day=INT, source_campaign_day=INT,
                   site_code=KW, site_name=KW, cluster=KW, target=INT,
                   vaccinated_6_11m=INT, vaccinated_14w_11m=INT, vaccinated_12_59m=INT, vaccinated_5_10y=INT,
                   total_vaccinated=INT, vials_received=INT, additional_vials_received=INT, vials_opened=INT,
                   vials_returned_unopened=INT)
CHILD_FIELDS = dict(child_id=KW, event_date={"type": "date"}, campaign_day=INT, source_campaign_day=INT,
                    site_code=KW, site_name=KW, cluster=KW, age_group=KW, ipv=INT, mr=INT, ipv_eligible=INT,
                    vaccine_status=KW, gender=KW, gender_synthetic=INT)


SYNC_FIELDS = dict(user_id=KW, role_group=KW, boundary_code=KW, synced=INT, downsynced=INT,
                   last_sync_date={"type": "date"}, synthetic=INT)


def unit(key):
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def synthetic_sync(cur):
    """The field database has no app sync data. Until HCM is connected, every frontline user in the
    microplan gets a stable synthetic sync status (about 93% synced, about 86% of vaccinators
    downsynced), flagged synthetic = 1, so the Data Quality sync charts keep working."""
    cur.execute("SELECT user_id, role_group, boundary_code FROM dim_user WHERE role_group IN ('VACCINATOR', 'REGISTRAR')")
    docs = []
    for uid, role, bcode in cur.fetchall():
        synced = int(unit(f"sync-20261109-{uid}") < 0.93)
        down = int(role == "VACCINATOR" and unit(f"downsync-20261109-{uid}") < 0.86)
        last = f"2026-11-{10 + int(unit(f'day-{uid}') * 2):02d}" if synced else None
        docs.append((uid, dict(user_id=uid, role_group=role, boundary_code=bcode, synced=synced, downsynced=down,
                               last_sync_date=last, synthetic=1)))
    return docs


def synthetic_gender(child_id):
    """The workbook has no gender column. Until it does, give each child a stable synthetic
    gender (about 50.7% male, Namibia's sex ratio at birth), flagged gender_synthetic = 1."""
    h = int(hashlib.sha256(f"gender-20261109-{child_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "MALE" if h < 0.507 else "FEMALE"


def es(method, path, body=None, ndjson=False):
    c = http.client.HTTPConnection(ES_HOST, ES_PORT, timeout=120)
    c.request(method, path, body=body, headers={"Content-Type": "application/x-ndjson" if ndjson else "application/json"})
    r = c.getresponse()
    out = r.read()
    if r.status >= 400 and not (method == "DELETE" and r.status == 404):
        raise RuntimeError(f"{method} {path} -> {r.status} {out[:300]}")
    return json.loads(out or b"{}")


def recreate(index, fields, docs):
    es("DELETE", f"/{index}")
    es("PUT", f"/{index}", json.dumps({"settings": {"number_of_replicas": 0},
                                       "mappings": {"dynamic": "strict", "properties": fields}}))
    for i in range(0, len(docs), 5000):
        lines = []
        for _id, d in docs[i:i + 5000]:
            lines += [json.dumps({"index": {"_index": index, "_id": _id}}), json.dumps(d)]
        res = es("POST", "/_bulk?refresh=wait_for", "\n".join(lines) + "\n", ndjson=True)
        if res.get("errors"):
            raise RuntimeError(next(x for x in res["items"] if x["index"].get("error")))


def sheet(wb, name):
    rows = list(wb[name].iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:] if r and r[2]]   # r[2] = Site_Code; drops TOTAL / blank rows


def day(date_text):
    return (dt.date.fromisoformat(str(date_text)[:10]) - CAMPAIGN_START).days + 1


def split_districts(cur, sites):
    """Replace the single microplan Zambezi district with the three field districts (approximate shapes)."""
    cur.execute("SELECT * FROM dim_district WHERE region=%s AND district=%s", (REGION, MICROPLAN_DISTRICT))
    cols = [c[0] for c in cur.description]
    base = dict(zip(cols, cur.fetchone()))
    zone = shape(json.loads(base["geojson"])).buffer(0)
    by_d = {}
    for s in sites:
        by_d.setdefault(s["district"], []).append((float(s["longitude"]), float(s["latitude"])))
    seeds = {d: MultiPoint(pts).centroid for d, pts in by_d.items()}
    cells = voronoi_diagram(MultiPoint(list(seeds.values())), envelope=zone.envelope.buffer(1))
    feats, rows, polys = [], [], []
    for name, code in DISTRICTS.values():
        cell = next(c for c in cells.geoms if c.contains(seeds[name]))
        geom = cell.intersection(zone)
        row = dict(base, boundary_code=code, district=name, geojson=json.dumps(mapping(geom)),
                   seat_lat=seeds[name].y, seat_lon=seeds[name].x, centroid_lat=geom.centroid.y, centroid_lon=geom.centroid.x)
        if name != MICROPLAN_DISTRICT:   # microplan targets and teams belong to the whole region (Katima Mulilo)
            for k in cols:
                if k.endswith(("_target", "_population", "_required")) or k.startswith(("teams_", "hr_")):
                    row[k] = None
        rows.append(row)
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for k, part in enumerate(parts):
            polys.append((code, REGION, name, k, json.dumps([[round(x, 5), round(y, 5)] for x, y in part.exterior.coords])))
        feats.append({"type": "Feature", "properties": {"boundary_code": code, "district": name, "region": REGION},
                      "geometry": mapping(geom)})
    cur.execute("DELETE FROM dim_district WHERE region=%s", (REGION,))
    cur.execute("DELETE FROM dim_district_polygon WHERE region=%s", (REGION,))
    cur.executemany(f"INSERT INTO dim_district ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                    [tuple(r[c] for c in cols) for r in rows])
    cur.executemany("INSERT INTO dim_district_polygon VALUES (%s,%s,%s,%s,%s)", polys)
    (ROOT / "data/zambezi_districts.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def load_sites():
    sites = list(csv.DictReader(open(ROOT / "data/sites.csv")))
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM dim_district WHERE region=%s", (REGION,))
    if cur.fetchone()[0] == 1:   # fresh microplan load (one Zambezi district): split it into the three field districts
        split_districts(cur, sites)
    codes = {name: code for name, code in DISTRICTS.values()}
    cur.execute("""DROP TABLE IF EXISTS dim_site;
        CREATE TABLE dim_site (site_code text PRIMARY KEY, site_name text, facility_type text,
          team_note text, region text, district text, boundary_code text,
          latitude double precision, longitude double precision, coord_source text)""")
    cur.executemany("INSERT INTO dim_site VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(s["site_code"], s["site_name"], s["facility_type"], s["team_note"] or None,
                      REGION, s["district"], codes[s["district"]], float(s["latitude"]), float(s["longitude"]),
                      s["coord_source"]) for s in sites])
    conn.commit()
    return sites


def main():
    if "--sites-only" in sys.argv:
        print(f"dim_site={len(load_sites())}")
        return
    wb = openpyxl.load_workbook(FIELD_XLSX, read_only=True, data_only=True)
    site_docs = {}
    for v in ("MR", "IPV"):
        stock = {(r["Site_Code"], str(r["Date"])[:10]): r for r in sheet(wb, f"Stock_{v}")}
        for a in sheet(wb, f"Agg_{v}"):
            d = str(a["Date"])[:10]
            s = stock.pop((a["Site_Code"], d), {})
            doc = dict(vaccine=v, event_date=d, campaign_day=day(d), source_campaign_day=a["Campaign_Day"],
                       site_code=a["Site_Code"], site_name=a["Site"], cluster=a["Cluster"], target=a["Target"],
                       total_vaccinated=a["Total_Vaccinated"],
                       vials_received=s.get(f"{v} vials received"),
                       additional_vials_received=s.get(f"Additional {v} vials received"),
                       vials_opened=s.get(f"{v} vials opened"),
                       vials_returned_unopened=s.get(f"{v} vials returned unopened"))
            for src, dst in (("Vaccinated 6-11 months", "vaccinated_6_11m"), ("Vaccinated 14 weeks-11 months", "vaccinated_14w_11m"),
                             ("Vaccinated 12-59 months", "vaccinated_12_59m"), ("Vaccinated 5-10 years", "vaccinated_5_10y")):
                if src in a:
                    doc[dst] = a[src]
            site_docs[f"{a['Site_Code']}|{d}|{v}"] = doc
        for (code, d), s in stock.items():   # stock row without an Agg row
            site_docs[f"{code}|{d}|{v}"] = dict(vaccine=v, event_date=d, campaign_day=day(d), site_code=code,
                                                site_name=s["Site"], cluster=s["Cluster"],
                                                source_campaign_day=s["Campaign_Day"],
                                                vials_received=s[f"{v} vials received"],
                                                additional_vials_received=s[f"Additional {v} vials received"],
                                                vials_opened=s[f"{v} vials opened"],
                                                vials_returned_unopened=s[f"{v} vials returned unopened"])
    children = []
    for c in sheet(wb, "Children"):
        d = str(c["Date"])[:10]
        children.append((c["Child_ID"], dict(child_id=c["Child_ID"], event_date=d, campaign_day=day(d),
                                             source_campaign_day=c["Campaign_Day"], site_code=c["Site_Code"],
                                             site_name=c["Site"], cluster=c["Cluster"], age_group=c["Age_Group"],
                                             ipv=c["IPV"], mr=c["MR"], ipv_eligible=c["IPV_Eligible"],
                                             vaccine_status=c["Vaccine_Status"],
                                             gender=(c.get("Gender") or c.get("Sex") or synthetic_gender(c["Child_ID"])),
                                             gender_synthetic=0 if (c.get("Gender") or c.get("Sex")) else 1)))

    for idx in LEGACY_IDX:
        es("DELETE", f"/{idx}")
    recreate(SITE_IDX, SITE_FIELDS, list(site_docs.items()))
    recreate(CHILD_IDX, CHILD_FIELDS, children)

    sites = load_sites()
    conn = psycopg2.connect(**PG)
    sync = synthetic_sync(conn.cursor())
    recreate(SYNC_IDX, SYNC_FIELDS, sync)
    unknown = {d["site_code"] for d in site_docs.values()} - {s["site_code"] for s in sites}
    if unknown:
        raise SystemExit(f"Sites missing from data/sites.csv: {sorted(unknown)}")
    print(f"{SITE_IDX}={len(site_docs)} {CHILD_IDX}={len(children)} {SYNC_IDX}={len(sync)} (synthetic) dim_site={len(sites)}")


if __name__ == "__main__":
    main()

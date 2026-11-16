"""Load the Zambezi MR/IPV child and stock database (field workbook) into Elasticsearch.

This replaces the synthetic HCM data. The workbook stays outside git (it is
field data); point FIELD_XLSX at it, or put it next to this repo.

Sheets -> indexes (one document per row, TOTAL rows dropped):
  Children                      -> field-child-v1     one doc per child
  Agg_MR + Stock_MR, Agg_IPV +  -> field-site-day-v1  one doc per site x date x vaccine
  Stock_IPV                                           (target, vaccinated by age group, vials)
Sites (code, type, cluster, coordinates) come from data/sites.csv -> Postgres dim_site.

Campaign day is computed from the date (9 Nov 2026 = day 1). The workbook's own
Campaign_Day disagrees between sheets (Children: 10 Nov = day 1; Agg/Stock: day 2),
so it is kept only as source_campaign_day for the data-quality tab.

    tools/.venv/bin/python -I tools/load_field_data.py               # workbook -> ES, sites -> Postgres
    tools/.venv/bin/python -I tools/load_field_data.py --sites-only  # sites only (real HCM ES already connected)
"""
import csv
import datetime as dt
import http.client
import json
import os
import sys
from pathlib import Path

import openpyxl
import psycopg2

ROOT = Path(__file__).resolve().parent.parent
FIELD_XLSX = Path(os.environ.get(
    "FIELD_XLSX", ROOT.parent / "Zambezi_region_MR_IPV_child_and_stock_database_VAA_updated.xlsx"))
ES_HOST, ES_PORT = os.environ.get("ES_HOST", "localhost"), int(os.environ.get("ES_PORT", "9200"))
PG = dict(host="localhost", port=5433, user="hcm", password="hcm", dbname="microplan")
CAMPAIGN_START = dt.date(2026, 11, 9)
REGION, DISTRICT = "Zambezi", "Katima Mulilo"   # every cluster in the workbook sits in this microplan district
CHILD_IDX, SITE_IDX = "field-child-v1", "field-site-day-v1"
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
                    vaccine_status=KW, gender=KW)


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


def load_sites():
    sites = list(csv.DictReader(open(ROOT / "data/sites.csv")))
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("""DROP TABLE IF EXISTS dim_site;
        CREATE TABLE dim_site (site_code text PRIMARY KEY, site_name text, cluster text, facility_type text,
          team_note text, region text, district text, boundary_code text,
          latitude double precision, longitude double precision, coord_source text)""")
    cur.execute("SELECT boundary_code FROM dim_district WHERE region=%s AND district=%s", (REGION, DISTRICT))
    bcode = cur.fetchone()[0]
    cur.executemany("INSERT INTO dim_site VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(s["site_code"], s["site_name"], s["cluster"], s["facility_type"], s["team_note"] or None,
                      REGION, DISTRICT, bcode, float(s["latitude"]), float(s["longitude"]), s["coord_source"])
                     for s in sites])
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
                                             gender=c.get("Gender") or c.get("Sex"))))   # not in the workbook yet

    for idx in LEGACY_IDX:
        es("DELETE", f"/{idx}")
    recreate(SITE_IDX, SITE_FIELDS, list(site_docs.items()))
    recreate(CHILD_IDX, CHILD_FIELDS, children)

    sites = load_sites()
    unknown = {d["site_code"] for d in site_docs.values()} - {s["site_code"] for s in sites}
    if unknown:
        raise SystemExit(f"Sites missing from data/sites.csv: {sorted(unknown)}")
    print(f"{SITE_IDX}={len(site_docs)} {CHILD_IDX}={len(children)} dim_site={len(sites)}")


if __name__ == "__main__":
    main()

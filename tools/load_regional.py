"""Prepare (and, later, load) regional MR/IPV child databases for COVERAGE only: Oshana and Khomas.

Each workbook has the Zambezi layout without stock: Children (one row per child), Agg_MR and
Agg_IPV (one row per site x date: target, children vaccinated by age group). There is no stock,
sync or gender data, and every Target cell is blank.

Default is a DRY RUN: it reads and checks the workbooks and prints what would be loaded. --load writes
them (run after tools/load_field_data.py, which recreates the indexes and dim_site).

Targets: the workbooks' Target cells are blank, so each site-day gets the microplan's per-team daily
target for its district: district target / number of teams / 11 campaign days (owner's instruction:
targets from the microplan). Sites load with data_scope = 'coverage' (no Inventory or sync).

    tools/.venv/bin/python -I tools/load_regional.py                 # dry run, both workbooks
    tools/.venv/bin/python -I tools/load_regional.py path/to/X_region_MR_IPV_child_database.xlsx

Workbooks default to ../<Region>_region_MR_IPV_child_database.xlsx next to this repo. Region comes from
the file name; district, cluster and clean site names come from data/regional_sites.csv (sites marked
include=no, such as the 'test' site, are dropped). Clusters: Oshana as in the workbook's Cluster column;
Khomas is the Katutura cluster (owner's instruction; the workbook labels it Windhoek Central Hospital).

What --load will write (same shapes as the Zambezi loader, so Overview and Coverage pick them up):
  field-child-v1      the children (with the same synthetic gender / zero-dose / AEFI flags as Zambezi)
  field-site-day-v1   one doc per site x date x vaccine (vial fields empty: no inventory)
  dim_site            the sites from data/regional_sites.csv
"""
import argparse
import json
import collections
import csv
import datetime as dt
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_field_data import (CAMPAIGN_START, CHILD_IDX, PG, SITE_IDX, bulk, day, es, sheet,  # noqa: E402
                             synthetic_aefi, synthetic_gender, synthetic_zero_dose)

CAMPAIGN_DAYS = 11

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = [ROOT.parent / f"{r}_region_MR_IPV_child_database.xlsx" for r in ("Oshana", "Khomas")]
AGE_COLS = {"Vaccinated 6-11 months": "vaccinated_6_11m", "Vaccinated 14 weeks-11 months": "vaccinated_14w_11m",
            "Vaccinated 12-59 months": "vaccinated_12_59m", "Vaccinated 5-10 years": "vaccinated_5_10y"}


def load_sites():
    return {s["site_code"]: s for s in csv.DictReader(open(ROOT / "data/regional_sites.csv"))}


def read(path, sites):
    region = Path(path).name.split("_region_")[0]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    issues, site_docs, children = [], {}, []
    for v in ("MR", "IPV"):
        for a in sheet(wb, f"Agg_{v}"):
            s = sites.get(a["Site_Code"])
            if s is None:
                issues.append(("ERROR", f"{region}: site {a['Site_Code']} ({a['Site']}) missing from data/regional_sites.csv"))
                continue
            if s["include"] != "yes":
                issues.append(("INFO", f"{region}: dropped {v} row for excluded site '{a['Site']}' on {a['Date']}"))
                continue
            d = str(a["Date"])[:10]
            ages = {dst: a[src] for src, dst in AGE_COLS.items() if src in a}
            doc = dict(vaccine=v, event_date=d, campaign_day=day(d), source_campaign_day=a["Campaign_Day"],
                       site_code=a["Site_Code"], site_name=s["site_name"], cluster=a["Cluster"], target=a["Target"],
                       total_vaccinated=a["Total_Vaccinated"], **ages)
            site_docs[f"{a['Site_Code']}|{d}|{v}"] = doc
            gap = (a["Total_Vaccinated"] or 0) - sum(x or 0 for x in ages.values())
            if gap and v == "IPV":   # 5-10 year olds who got IPV: counted in the total, not in an age column
                doc["vaccinated_5_10y"] = gap
            if gap:
                issues.append(("WARN", f"{region}: {s['site_name']} {d} {v} total {a['Total_Vaccinated']} is {gap} more "
                                       f"than its age groups (IPV given to 5-10 year olds, outside the IPV age range)"))
            if a["Target"] is None:
                issues.append(("TARGET", f"{region}: {s['site_name']} {d} {v} has no target"))
            if a["Campaign_Day"] != day(d):
                issues.append(("DAY", f"{region}: {s['site_name']} {d} labelled day {a['Campaign_Day']}, date says day {day(d)}"))
    listed = collections.Counter()
    for c in sheet(wb, "Children"):
        s = sites.get(c["Site_Code"])
        if s is None or s["include"] != "yes":
            continue
        d = str(c["Date"])[:10]
        children.append(c)
        listed[(c["Site_Code"], d, "MR")] += c["MR"] or 0
        listed[(c["Site_Code"], d, "IPV")] += c["IPV"] or 0
    for k, doc in site_docs.items():
        n = listed[(doc["site_code"], doc["event_date"], doc["vaccine"])]
        if n != doc["total_vaccinated"]:
            issues.append(("WARN", f"{region}: {doc['site_name']} {doc['event_date']} {doc['vaccine']}: "
                                   f"{n} children in the line list vs {doc['total_vaccinated']} in the aggregate"))
    over_age = sum(1 for c in children if c["IPV"] and c["Age_Group"] == "5-10 years")
    if over_age:
        issues.append(("WARN", f"{region}: {over_age} children aged 5-10 years recorded with IPV (outside the 14 weeks-59 months range)"))
    return region, site_docs, children, issues


def tally_overlap(site_docs):
    """Same site and date in the MoHSS tally workbook would be counted twice."""
    try:
        from load_tally import load_sites as tally_sites, read_rows
        rows, ts = read_rows(), tally_sites()
    except Exception:   # tally workbook not present
        return []
    names = {s["site_name"].lower() for s in ts.values()}
    tally = collections.Counter()
    for r in rows:
        if r["indicator_code"].startswith(("MR_", "IPV_")) and r["indicator_group"].endswith("vaccinated"):
            d = r["date"].date().isoformat() if isinstance(r["date"], dt.datetime) else str(r["date"])[:10]
            tally[(r["site"].lower(), d, r["indicator_code"].split("_")[0])] += r["count"]
    out = []
    for doc in site_docs.values():
        key = (doc["site_name"].lower(), doc["event_date"], doc["vaccine"])
        if doc["site_name"].lower() in names and key in tally:
            out.append(("OVERLAP", f"{doc['site_name']} {doc['event_date']} {doc['vaccine']}: {doc['total_vaccinated']} here "
                                   f"vs {int(tally[key])} in the tally workbook - load one source only"))
    return out


def per_team_targets(cur):
    cur.execute("SELECT region, district, boundary_code, mr_target, ipv_target, teams_total FROM dim_district")
    return {(r, d): {"code": c, "MR": mr / t / CAMPAIGN_DAYS, "IPV": ipv / t / CAMPAIGN_DAYS}
            for r, d, c, mr, ipv, t in cur.fetchall() if t}


def load(site_docs, children, sites):
    import psycopg2
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    targets = per_team_targets(cur)
    used = {s["site_code"] for s in sites.values() if s["include"] == "yes"}
    # idempotent: drop anything previously loaded for these sites, then append
    for idx in (SITE_IDX, CHILD_IDX):
        es("POST", f"/{idx}/_delete_by_query?refresh=true",
           json.dumps({"query": {"terms": {"site_code": sorted(used)}}}))
    for doc in site_docs.values():
        s = sites[doc["site_code"]]
        doc["target"] = round(targets[(s["region"], s["district"])][doc["vaccine"]])
    bulk(SITE_IDX, list(site_docs.items()))
    child_docs = []
    for c in children:
        d = str(c["Date"])[:10]
        child_docs.append((c["Child_ID"], dict(
            child_id=c["Child_ID"], event_date=d, campaign_day=day(d), source_campaign_day=c["Campaign_Day"],
            site_code=c["Site_Code"], site_name=sites[c["Site_Code"]]["site_name"], cluster=c["Cluster"],
            age_group=c["Age_Group"], ipv=c["IPV"], mr=c["MR"], ipv_eligible=c["IPV_Eligible"],
            vaccine_status=c["Vaccine_Status"], gender=c.get("Gender") or synthetic_gender(c["Child_ID"]),
            gender_synthetic=0 if c.get("Gender") else 1, zero_dose=synthetic_zero_dose(c), zero_dose_synthetic=1,
            aefi=synthetic_aefi(c), aefi_synthetic=1)))
    bulk(CHILD_IDX, child_docs)
    cur.execute("DELETE FROM dim_site WHERE site_code = ANY(%s)", (sorted(used),))
    cur.executemany("INSERT INTO dim_site VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(s["site_code"], s["site_name"], s["facility_type"], None, s["region"], s["district"], s["cluster"],
                      targets[(s["region"], s["district"])]["code"], float(s["latitude"]), float(s["longitude"]),
                      s["coord_source"], "coverage") for s in sites.values() if s["include"] == "yes"])
    conn.commit()
    print(f"Loaded {len(site_docs)} site-day docs, {len(child_docs)} children, {len(used)} sites (coverage only).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workbooks", nargs="*", default=[str(p) for p in DEFAULT])
    ap.add_argument("--load", action="store_true", help="write to Elasticsearch and Postgres (not enabled yet)")
    a = ap.parse_args()
    sites = load_sites()
    all_docs, all_children, all_issues = {}, [], []
    for path in a.workbooks:
        region, docs, children, issues = read(path, sites)
        all_docs.update(docs), all_children.extend(children), all_issues.extend(issues)
        print(f"{Path(path).name}: region {region}, {len(children)} children, {len(docs)} site-day rows")
    all_issues += tally_overlap(all_docs)

    print(f"\n{'site':28} {'date':10} day {'vaccine':4} {'children':>8}  district")
    for k in sorted(all_docs, key=lambda k: (all_docs[k]["site_code"][:0] + sites[all_docs[k]["site_code"]]["region"],
                                             all_docs[k]["site_name"], all_docs[k]["event_date"], all_docs[k]["vaccine"])):
        d = all_docs[k]
        print(f"{d['site_name']:28} {d['event_date']} {d['campaign_day']:3} {d['vaccine']:4} {d['total_vaccinated']:8}  "
              f"{sites[d['site_code']]['district']}")
    tot = collections.Counter()
    for d in all_docs.values():
        tot[(sites[d["site_code"]]["region"], d["vaccine"])] += d["total_vaccinated"]
    print("\nTotals:", {f"{r} {v}": n for (r, v), n in sorted(tot.items())})
    levels = collections.Counter(level for level, _ in all_issues)
    print(f"\nChecks: {dict(levels)}")
    seen = set()
    for level, msg in all_issues:
        if level in ("TARGET", "DAY"):   # one line each, not per row
            if level in seen:
                continue
            seen.add(level)
            msg = {"TARGET": "every Agg row has a blank Target", "DAY": "Campaign_Day labels are 3 ahead of the date "
                   "(12 Nov written as day 7); day is taken from the date"}[level]
        print(f"  {level:7} {msg}")
    print(f"\nWould write: {len(all_children)} children to field-child-v1, {len(all_docs)} docs to field-site-day-v1, "
          f"{sum(1 for s in sites.values() if s['include'] == 'yes')} rows to dim_site.")
    if a.load:
        load(all_docs, all_children, sites)


if __name__ == "__main__":
    main()

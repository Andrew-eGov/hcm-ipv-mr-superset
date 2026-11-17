"""Prepare (and, later, load) the MoHSS paper-tally workbook: Oshana + Omusati, Overview and Coverage only.

The tally workbook (sheet `tally_long`, one row per site x day x indicator) has children vaccinated by
age group for MR and IPV, IPV children who also got MR, zero-dose, refusals and AEFI. It has no
inventory, sync, gender or child line list, and no daily targets (blank on every sheet).

Default is a DRY RUN: it reads and checks the workbook and prints what would be loaded. Nothing is
written. Run with --load only once the owner has decided the target rule (see TARGET_RULES).

    tools/.venv/bin/python -I tools/load_tally.py                       # dry run (default)
    tools/.venv/bin/python -I tools/load_tally.py --target-rule per-team  # dry run with estimated targets
    tools/.venv/bin/python -I tools/load_tally.py --load ...            # NOT YET: writes ES + dim_site

What --load will write (kept separate from the Zambezi field database so either can be reloaded):
  field-tally-v1      one doc per tally row (indicator, count, data_status, notes), for zero-dose,
                      AEFI, refusals and co-administration
  field-site-day-v1   one doc per site x date x vaccine in the same shape as the Zambezi data
                      (vials left empty), so Overview and Coverage charts pick the sites up
  dim_site            the two sites from data/tally_sites.csv
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
TALLY_XLSX = Path(os.environ.get("TALLY_XLSX", ROOT.parent / "Namibia_MR-IPV_Tally_Ingestion.xlsx"))
CAMPAIGN_START = dt.date(2026, 11, 9)
CAMPAIGN_DAYS = 11
TALLY_IDX, SITE_IDX = "field-tally-v1", "field-site-day-v1"

# tally indicator_code -> field-site-day-v1 age field (same names as the Zambezi loader)
AGE_FIELD = {"MR_6_11M": ("MR", "vaccinated_6_11m"), "MR_12_59M": ("MR", "vaccinated_12_59m"),
             "MR_5_10Y": ("MR", "vaccinated_5_10y"), "IPV_14W_11M": ("IPV", "vaccinated_14w_11m"),
             "IPV_12_59M": ("IPV", "vaccinated_12_59m")}
OTHER_CODES = {"IPV_ALSO_MR", "ZERO_DOSE", "REFUSAL_MR", "REFUSAL_IPV", "AEFI_MR_MINOR", "AEFI_MR_SERIOUS",
               "AEFI_IPV_MINOR", "AEFI_IPV_SERIOUS"}

# Daily targets are blank on the tally sheets. Choose one before loading:
#   none      no target: the sites add children vaccinated, zero-dose and AEFI, but are left out of
#             coverage % (needs coverage SQL to sum target only where it exists)
#   per-team  estimate a daily site target from the microplan: district target / district teams / 11 days
TARGET_RULES = ("none", "per-team")


def read_rows():
    wb = openpyxl.load_workbook(TALLY_XLSX, read_only=True, data_only=True)
    rows = list(wb["tally_long"].iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:] if r and r[0]]


def load_sites():
    return {s["site_name"]: s for s in csv.DictReader(open(ROOT / "data/tally_sites.csv"))}


def microplan_targets():
    """Per-team daily targets by district from Postgres (only used with --target-rule per-team)."""
    import psycopg2
    conn = psycopg2.connect(host="localhost", port=5433, user="hcm", password="hcm", dbname="microplan")
    cur = conn.cursor()
    cur.execute("SELECT district, mr_target, ipv_target, teams_total FROM dim_district")
    return {d: {"MR": mr / teams / CAMPAIGN_DAYS, "IPV": ipv / teams / CAMPAIGN_DAYS}
            for d, mr, ipv, teams in cur.fetchall() if teams}


def check(rows, sites):
    """Data checks; returns a list of (level, message)."""
    out = []
    ids = collections.Counter(r["record_id"] for r in rows)
    out += [("ERROR", f"duplicate record_id {k}") for k, n in ids.items() if n > 1]
    for r in rows:
        d = r["date"].date() if isinstance(r["date"], dt.datetime) else dt.date.fromisoformat(str(r["date"])[:10])
        if (d - CAMPAIGN_START).days + 1 != r["campaign_day"]:
            out.append(("ERROR", f"{r['record_id']}: campaign_day {r['campaign_day']} does not match date {d}"))
        if r["site"] not in sites:
            out.append(("ERROR", f"{r['record_id']}: site '{r['site']}' missing from data/tally_sites.csv"))
        elif (sites[r["site"]]["region"], sites[r["site"]]["district"]) != (r["region"], r["district"]):
            out.append(("ERROR", f"{r['record_id']}: region/district differ from data/tally_sites.csv"))
        if r["indicator_code"] not in AGE_FIELD and r["indicator_code"] not in OTHER_CODES:
            out.append(("ERROR", f"{r['record_id']}: unknown indicator_code {r['indicator_code']}"))
        if not isinstance(r["count"], (int, float)) or r["count"] < 0:
            out.append(("ERROR", f"{r['record_id']}: count is not a non-negative number"))
    days = collections.defaultdict(dict)
    for r in rows:
        days[(r["site"], r["campaign_day"])][r["indicator_code"]] = r
    for (site, day), c in sorted(days.items()):
        status = {x["data_status"] for x in c.values()}
        if "provisional" in status:
            out.append(("WARN", f"{site} day {day}: provisional (counted mid-session) - replace when final arrives"))
        mr = sum(c[k]["count"] for k in ("MR_6_11M", "MR_12_59M", "MR_5_10Y") if k in c)
        ipv = sum(c[k]["count"] for k in ("IPV_14W_11M", "IPV_12_59M") if k in c)
        both = c.get("IPV_ALSO_MR", {}).get("count")
        if both is not None and both > min(mr, ipv):
            out.append(("WARN", f"{site} day {day}: IPV-also-MR ({both}) exceeds MR ({mr}) or IPV ({ipv}) total"))
        if both == 0 and mr and ipv:
            out.append(("WARN", f"{site} day {day}: IPV-also-MR is 0 with {mr} MR and {ipv} IPV children - likely blank on paper"))
        missing = sorted(OTHER_CODES - set(c))
        if missing:
            out.append(("INFO", f"{site} day {day}: not on the sheet (left empty, not 0): {', '.join(missing)}"))
    return out


def site_day_docs(rows, sites, rule, targets):
    by = collections.defaultdict(dict)
    for r in rows:
        if r["indicator_code"] in AGE_FIELD:
            vaccine, field = AGE_FIELD[r["indicator_code"]]
            key = (r["site"], r["campaign_day"], vaccine)
            doc = by[key]
            d = (CAMPAIGN_START + dt.timedelta(days=r["campaign_day"] - 1)).isoformat()
            doc.update(vaccine=vaccine, event_date=d, campaign_day=r["campaign_day"], source_campaign_day=r["campaign_day"],
                       site_code=sites[r["site"]]["site_code"], site_name=r["site"], cluster=None)
            doc[field] = int(r["count"])
            doc["data_status"] = "provisional" if r["data_status"] == "provisional" or doc.get("data_status") == "provisional" else "final"
    docs = {}
    for (site, day, vaccine), doc in by.items():
        doc["total_vaccinated"] = sum(v for k, v in doc.items() if k.startswith("vaccinated_"))
        district = sites[site]["district"]
        doc["target"] = round(targets[district][vaccine]) if rule == "per-team" else None
        docs[f"{doc['site_code']}|{doc['event_date']}|{vaccine}"] = doc
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-rule", choices=TARGET_RULES, default="none")
    ap.add_argument("--load", action="store_true", help="write to Elasticsearch and Postgres (not enabled yet)")
    a = ap.parse_args()

    rows, sites = read_rows(), load_sites()
    issues = check(rows, sites)
    targets = microplan_targets() if a.target_rule == "per-team" else {}
    docs = site_day_docs(rows, sites, a.target_rule, targets)

    print(f"Workbook: {TALLY_XLSX.name}  rows={len(rows)}  sites={sorted({r['site'] for r in rows})}")
    print(f"Target rule: {a.target_rule}")
    print(f"\n{'site':22} {'date':10} day {'vaccine':4} {'children':>8} {'target':>7}  status")
    for k in sorted(docs, key=lambda k: (docs[k]['site_name'], docs[k]['event_date'], docs[k]['vaccine'])):
        d = docs[k]
        print(f"{d['site_name']:22} {d['event_date']} {d['campaign_day']:3} {d['vaccine']:4} {d['total_vaccinated']:8} "
              f"{'' if d['target'] is None else d['target']:>7}  {d['data_status']}")
    other = collections.Counter()
    for r in rows:
        if r["indicator_code"] in OTHER_CODES:
            other[r["indicator_code"]] += int(r["count"])
    print("\nOther indicators (totals):", dict(other))
    print(f"\nChecks: {sum(1 for l, _ in issues if l == 'ERROR')} errors, {sum(1 for l, _ in issues if l == 'WARN')} warnings")
    for level, msg in issues:
        print(f"  {level:5} {msg}")
    print(f"\nWould write: {len(rows)} docs to {TALLY_IDX}, {len(docs)} docs to {SITE_IDX}, {len(sites)} rows to dim_site.")

    if a.load:
        raise SystemExit("--load is not enabled yet: the owner asked to prepare the tally data without ingesting it. "
                         "See CLAUDE.md, 'Tally data (prepared, not loaded)'.")


if __name__ == "__main__":
    main()

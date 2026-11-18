"""Load manually reported records (data/manual_records.csv): Overview and Coverage only.

One row per site x date x vaccine, for records reported outside the field workbooks (e.g. a new outreach
point added on the day). Each row becomes a field-site-day-v1 doc and its site a dim_site row with
data_scope = 'coverage' (no inventory or sync). There is no child line list, so the record counts in
children vaccinated and coverage but not in the age, gender or vaccine-status breakdowns.

Target: the microplan's per-team daily target for the site's district (district target / teams / 11
days), the same rule as tools/load_regional.py. Run after tools/load_regional.py; idempotent.

    tools/.venv/bin/python -I tools/load_manual.py
"""
import csv
import json
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_field_data import PG, SITE_IDX, bulk, day, es  # noqa: E402
from load_regional import per_team_targets  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main():
    rows = list(csv.DictReader(open(ROOT / "data/manual_records.csv")))
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    targets = per_team_targets(cur)
    codes = sorted({r["site_code"] for r in rows})
    es("POST", f"/{SITE_IDX}/_delete_by_query?refresh=true", json.dumps({"query": {"terms": {"site_code": codes}}}))
    docs = []
    for r in rows:
        t = targets[(r["region"], r["district"])]
        docs.append((f"{r['site_code']}|{r['date']}|{r['vaccine']}", dict(
            vaccine=r["vaccine"], event_date=r["date"], campaign_day=day(r["date"]), source_campaign_day=None,
            site_code=r["site_code"], site_name=r["site_name"], cluster=r["cluster"],
            target=round(t[r["vaccine"]]), total_vaccinated=int(r["vaccinated"]))))
    bulk(SITE_IDX, docs)
    sites = {r["site_code"]: r for r in rows}
    cur.execute("DELETE FROM dim_site WHERE site_code = ANY(%s)", (codes,))
    cur.executemany("INSERT INTO dim_site VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(s["site_code"], s["site_name"], s["facility_type"], None, s["region"], s["district"], s["cluster"],
                      targets[(s["region"], s["district"])]["code"], float(s["latitude"]), float(s["longitude"]),
                      s["coord_source"], "coverage") for s in sites.values()])
    conn.commit()
    print(f"Loaded {len(docs)} manual site-day docs for {len(sites)} sites.")


if __name__ == "__main__":
    main()

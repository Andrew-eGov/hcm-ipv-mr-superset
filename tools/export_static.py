"""Export a static snapshot of the dashboard data for the review site (static/).

Runs the same dataset SQL as Superset (tools/hcm_datasets.py) through Trino and
writes static/data.json. Mock data only - re-run after regenerating mocks.

    tools/.venv/bin/python -I tools/export_static.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

import trino

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hcm_datasets as H  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
conn = trino.dbapi.connect(host="localhost", port=8080, user="export", catalog="hcm", schema="default")


def q(sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = []
    for r in cur.fetchall():
        rows.append({c: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else
                         round(v, 5) if isinstance(v, float) else v) for c, v in zip(cols, r)})
    return rows


def ds(fn, select, where="", group=""):
    sql = f"SELECT {select} FROM ({fn().strip()}) t"
    if where:
        sql += f" WHERE {where}"
    if group:
        sql += f" GROUP BY {group}"
    return q(sql)


def main():
    out = {"generated": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"}
    out["districts"] = q("SELECT boundary_code AS code, region, district, mr_target, ipv_target, u5_population, "
                         "teams_total, teams_fixed, teams_temp_fixed, teams_mobile FROM microplan.public.dim_district "
                         "ORDER BY region, district")
    out["coverage"] = ds(H.ds_coverage, "boundary_code AS code, product, doses, attempts, target, planned_to_date, days_elapsed")
    out["coadmin"] = ds(H.ds_coadmin, "boundary_code AS code, children_9_59 AS kids, both_9_59 AS both")
    out["daily"] = ds(H.ds_delivery_daily, "event_date AS d, boundary_code AS code, product, delivery_mode AS mode, "
                      "status, reason, sum(records) AS n, sum(doses) AS doses",
                      group="1,2,3,4,5,6")
    out["age"] = ds(H.ds_age, "boundary_code AS code, product, age_group, sum(doses) AS doses", group="1,2,3")
    out["households"] = ds(H.ds_household_daily, "boundary_code AS code, visit_outcome AS outcome, sum(households) AS n",
                           group="1,2")
    out["sync"] = ds(H.ds_sync, "district, region, user_group AS g, count(*) AS total, sum(synced) AS synced", group="1,2,3")
    out["wastage"] = ds(H.ds_wastage, "boundary_code AS code, product, doses_opened, doses_administered, doses_wasted")
    out["stock"] = ds(H.ds_stock_position, "region, district, boundary_code AS code, facility_name AS name, facility_type AS type, "
                      "level, latitude AS lat, longitude AS lon, product, unit, received, dispatched, returned, stock_in_hand, "
                      "daily_use, days_of_stock, stock_status", where="product IN ('MR','IPV')")
    out["discrepancy"] = ds(H.ds_stock_discrepancy, "region, district, waybill, product, sender_name AS sender, "
                            "receiving_facility AS receiver, sent, received, discrepancy", where="discrepancy <> 0")
    out["flow"] = ds(H.ds_stock_flow, "product, source, target, sum(quantity) AS qty", group="1,2,3")
    out["arcs"] = ds(H.ds_stock_arcs, "product, source_name, target_name, source_lat, source_lon, target_lat, target_lon, "
                     "region, district, sum(quantity) AS qty", group="1,2,3,4,5,6,7,8,9")
    out["dq"] = ds(H.ds_dq_district, "boundary_code AS code, records, missing_gps, low_accuracy, off_hours, duplicates, "
                   "outside_district, registrations, incomplete")
    out["dq_users"] = ds(H.ds_dq_users, "district, user_id, event_date AS d, doses_recorded AS n", where="doses_recorded > 120")
    out["dq_teams"] = ds(H.ds_dq_teams, "district, team_id, team_type, event_date AS d, doses_recorded AS n",
                         where="doses_recorded < 20")
    out["checklist_completion"] = ds(H.ds_checklist_completion, "region, district, supervisor_level AS level, "
                                     "sum(submitted) AS submitted, sum(expected) AS expected", group="1,2,3")
    out["checklist_findings"] = ds(H.ds_checklist_findings, "boundary_code AS code, question, sum(yes_count) AS yes, "
                                   "sum(submissions) AS n", group="1,2")
    out["checklist_daily"] = ds(H.ds_checklist_daily, "event_date AS d, boundary_code AS code, supervisor_role AS role, "
                                "sum(submissions) AS n", group="1,2,3")
    out["complaints"] = ds(H.ds_complaints_daily, "event_date AS d, boundary_code AS code, complaint_type AS type, "
                           "status_group AS status, sum(complaints) AS n, sum(resolved) AS resolved, "
                           "sum(resolution_hours) AS hours", group="1,2,3,4")
    out["tiles"] = ds(H.ds_map_delivery_tiles, "boundary_code AS code, product, delivery_mode AS mode, "
                      "round(latitude, 4) AS lat, round(longitude, 4) AS lon, doses")
    out["missed"] = ds(H.ds_points_missed, "boundary_code AS code, product, reason, round(latitude, 4) AS lat, "
                       "round(longitude, 4) AS lon")[:4000]
    out["gps_issues"] = ds(H.ds_points_gps_issues, "boundary_code AS code, round(accuracy_m) AS acc, "
                           "round(latitude, 4) AS lat, round(longitude, 4) AS lon")[:3000]
    out["checklist_points"] = ds(H.ds_points_checklists, "boundary_code AS code, supervisor_role AS role, "
                                 "round(latitude, 4) AS lat, round(longitude, 4) AS lon")
    out["complaint_points"] = ds(H.ds_points_complaints, "boundary_code AS code, complaint_type AS type, status, "
                                 "round(latitude, 4) AS lat, round(longitude, 4) AS lon")
    out["planned"] = q("SELECT campaign_date AS d, day_no, planned_cum_pct FROM microplan.public.dim_campaign_day ORDER BY 1")

    geo = json.load(open(ROOT / "data/districts.geojson"))
    for f in geo["features"]:
        p = f["properties"]
        f["properties"] = {"code": p["boundary_code"], "district": p["district"], "region": p["region"]}

        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 3), round(c[1], 3)]
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    out["geo"] = geo

    dst = ROOT / "static/data.json"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(out, separators=(",", ":")))
    print({k: len(v) if isinstance(v, list) else "" for k, v in out.items()}, f"{dst.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()

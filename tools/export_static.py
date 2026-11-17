"""Export a static snapshot of the dashboard data for the review site (static/).

Runs the same dataset SQL as Superset (tools/datasets.py) through Trino and writes
static/data.json. Only aggregates leave the stack: no child ids or line-list rows.
static/data.json is git-ignored because it holds field data.

    tools/.venv/bin/python -I tools/export_static.py
"""
import datetime as dt
import json
import sys
from pathlib import Path

import trino
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import datasets as DS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
conn = trino.dbapi.connect(host="localhost", port=8080, user="export", catalog="hcm", schema="default")


def q(sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    return [{c: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else
                 round(v, 4) if isinstance(v, float) else v) for c, v in zip(cols, r)} for r in cur.fetchall()]


def ds(fn, select, where="", group=""):
    sql = f"SELECT {select} FROM ({fn().strip()}) t"
    if where:
        sql += f" WHERE {where}"
    if group:
        sql += f" GROUP BY {group}"
    return q(sql)


def rnd(c, n=3):
    return [rnd(x, n) for x in c] if isinstance(c[0], list) else [round(c[0], n), round(c[1], n)]


def geo(path, keep):
    g = json.load(open(ROOT / path))
    for f in g["features"]:
        f["properties"] = {k: f["properties"][k] for k in keep}
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    return g


def main():
    out = {"generated": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", "campaign_days": DS.CAMPAIGN_DAYS,
           "campaign_start": "2026-11-09"}
    out["sites"] = ds(DS.ds_sites, "site_code AS code, site_name AS name, region, district, cluster, boundary_code AS bcode, "
                      "facility_type AS type, team_note AS team, latitude AS lat, longitude AS lon, coord_source AS src, "
                      "data_scope AS scope")
    out["site_day"] = ds(DS.ds_site_day, "site_code AS code, product AS p, event_date AS d, target, vaccinated AS vac, "
                         "vials_received AS rec, additional_vials_received AS add, vials_opened AS opened, "
                         "vials_returned_unopened AS ret, doses_per_vial AS dpv, source_campaign_day AS src_day")
    out["age"] = ds(DS.ds_age, "site_name, product AS p, event_date AS d, age_group AS g, age_order AS o, vaccinated AS n")
    names = {s["name"]: s["code"] for s in out["sites"]}
    for r in out["age"]:
        r["code"] = names[r.pop("site_name")]
    out["children"] = ds(DS.ds_children, "site_code AS code, product AS p, event_date AS d, gender, sum(children) AS n",
                         group="1, 2, 3, 4")
    out["status"] = ds(DS.ds_child_status, "site_code AS code, event_date AS d, vaccine_status AS s, sum(children) AS n, "
                       "sum(zero_dose) AS zd, sum(aefi) AS aefi",
                       group="1, 2, 3")
    out["sync"] = ds(DS.ds_sync, "region, district, cluster, user_group AS g, count(*) AS total, sum(synced) AS synced",
                     group="1, 2, 3, 4")
    out["districts"] = q("SELECT boundary_code AS code, region, district FROM microplan.public.dim_district ORDER BY 2, 3")
    out["geo_districts"] = geo("data/districts.geojson", ("boundary_code", "district", "region"))
    # district names as in dim_district (the loader renames Zambezi's "Katima Mulilo" to "Katima")
    names = {d["code"]: d["district"] for d in out["districts"]}
    for f in out["geo_districts"]["features"]:
        f["properties"]["district"] = names.get(f["properties"]["boundary_code"], f["properties"]["district"])
    out["geo_regions"] = geo("data/regions.geojson", ("region",))
    # Mask: everything outside Namibia, so the basemap shows Namibia only
    nam = unary_union([shape(f["geometry"]) for f in out["geo_regions"]["features"]]).buffer(0.01).simplify(0.01)
    out["mask"] = json.loads(json.dumps(mapping(box(-60, -60, 80, 40).difference(nam))))
    out["mask"]["coordinates"] = rnd(out["mask"]["coordinates"])

    dst = ROOT / "static/data.json"
    dst.write_text(json.dumps(out, separators=(",", ":")))
    print({k: len(v) if isinstance(v, list) else "" for k, v in out.items()}, f"{dst.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()

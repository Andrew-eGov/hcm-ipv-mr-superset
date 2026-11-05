"""Build the HCM IPV+MR dashboard in Superset via its REST API (idempotent).

Creates: Trino database connection -> 28 virtual datasets (tools/hcm_datasets.py)
-> ~75 charts -> one dashboard with 6 tabs and native filters.
Re-running replaces everything it created (matched by name prefix).

    tools/.venv/bin/python -I tools/build_superset.py
"""
import json
import re
import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hcm_datasets import DATASETS  # noqa: E402

BASE = "http://localhost:8088"
DB_NAME = "HCM Elasticsearch (Trino)"
DB_URI = "trino://admin@trino:8080/hcm"
DASH_TITLE = "IPV + MR Integrated Campaign - National Dashboard (Namibia 2026)"
SLUG = "hcm-ipv-mr-namibia"
CHART_PREFIX = "[IPV-MR] "
TILE = "tile://https://tile.openstreetmap.org/{z}/{x}/{y}.png"
VIEWPORT = {"latitude": -22.4, "longitude": 18.4, "zoom": 4.25, "bearing": 0, "pitch": 0}
ORANGE = {"r": 244, "g": 119, "b": 56, "a": 1}
BLUE = {"r": 46, "g": 117, "b": 182, "a": 0.85}

s = requests.Session()


def api(method, path, **kw):
    r = s.request(method, BASE + path, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
    return r.json() if r.text else {}


def login():
    tok = api("POST", "/api/v1/security/login",
              json={"username": "admin", "password": "admin", "provider": "db", "refresh": True})["access_token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    s.headers["Referer"] = BASE


def find(resource, col, value):
    q = json.dumps({"filters": [{"col": col, "opr": "eq", "value": value}], "page_size": 100})
    return api("GET", f"/api/v1/{resource}/?q={q}")["result"]


# ------------------------------------------------------------------ teardown
def teardown():
    for d in find("dashboard", "slug", SLUG):
        api("DELETE", f"/api/v1/dashboard/{d['id']}")
    q = json.dumps({"filters": [{"col": "slice_name", "opr": "sw", "value": CHART_PREFIX}], "page_size": 500})
    for c in api("GET", f"/api/v1/chart/?q={q}")["result"]:
        api("DELETE", f"/api/v1/chart/{c['id']}")
    for name in DATASETS:
        for d in find("dataset", "table_name", name):
            api("DELETE", f"/api/v1/dataset/{d['id']}")


def ensure_db():
    found = find("database", "database_name", DB_NAME)
    if found:
        return found[0]["id"]
    return api("POST", "/api/v1/database/", json={
        "database_name": DB_NAME, "sqlalchemy_uri": DB_URI, "expose_in_sqllab": True,
        "allow_run_async": False, "extra": json.dumps({"metadata_cache_timeout": {}, "allows_virtual_table_explore": True}),
    })["id"]


def create_datasets(db_id):
    ids, cols = {}, {}
    for name, (fn, dttm) in DATASETS.items():
        sql = fn().strip()
        res = api("POST", "/api/v1/dataset/", json={"database": db_id, "schema": "default", "table_name": name, "sql": sql})
        did = res["id"]
        api("PUT", f"/api/v1/dataset/{did}/refresh")
        info = api("GET", f"/api/v1/dataset/{did}")["result"]
        cols[name] = {c["column_name"] for c in info["columns"]}
        upd = {"cache_timeout": 60, "description": (fn.__doc__ or "").strip()}
        if dttm:
            upd["main_dttm_col"] = dttm
            upd["columns"] = [{"id": c["id"], "column_name": c["column_name"],
                               "is_dttm": c["column_name"] == dttm or c.get("is_dttm", False),
                               "type": c.get("type"), "groupby": True, "filterable": True}
                              for c in info["columns"]]
        api("PUT", f"/api/v1/dataset/{did}?override_columns=false", json=upd)
        ids[name] = did
        print(f"  dataset {name:28s} id={did} cols={len(cols[name])}")
    return ids, cols


# ------------------------------------------------------------------ chart helpers
def M(sql, label):
    return {"expressionType": "SQL", "sqlExpression": sql, "label": label, "hasCustomLabel": True,
            "optionName": "metric_" + re.sub(r"\W+", "_", label.lower())[:40]}


def F(col, op, val):
    f = {"expressionType": "SIMPLE", "clause": "WHERE", "subject": col, "operator": op,
         "filterOptionName": "f_" + uuid.uuid4().hex[:10]}
    if op in ("IN", "NOT IN"):
        f["comparator"] = val if isinstance(val, list) else [val]
    elif op not in ("IS NULL", "IS NOT NULL"):
        f["comparator"] = val
    return f


def FSQL(sql):
    return {"expressionType": "SQL", "clause": "WHERE", "sqlExpression": sql, "filterOptionName": "f_" + uuid.uuid4().hex[:10]}


TIME_F = lambda: {"expressionType": "SIMPLE", "clause": "WHERE", "subject": "event_date", "operator": "TEMPORAL_RANGE",
                  "comparator": "No filter", "filterOptionName": "f_" + uuid.uuid4().hex[:10]}

CHARTS = []  # (tab, row, width, height, name, dataset, viz, params)


def chart(tab, row, width, height, name, ds, viz, **p):
    CHARTS.append(dict(tab=tab, row=row, width=width, height=height, name=name, ds=ds, viz=viz, params=p))


def big(tab, row, width, name, ds, metric, subheader="", fmt="SMART_NUMBER", filters=(), height=22):
    chart(tab, row, width, height, name, ds, "big_number_total", metric=metric, subheader=subheader, subtitle=subheader,
          y_axis_format=fmt, header_font_size=0.35, subheader_font_size=0.15, adhoc_filters=list(filters))


def sync_strip(tab, group, label):
    f = [F("user_group", "IN", [group])]
    big(tab, 1, 4, f"{label}: total", "hcm_sync", M("COUNT(*)", f"Total {label.lower()}"), f"Total {label.lower()}", ",d", f, 18)
    big(tab, 1, 4, f"{label}: synced at least once", "hcm_sync", M("SUM(synced)", "Synced at least once"),
        f"{label} synced at least once", ",d", f, 18)
    big(tab, 1, 4, f"{label}: sync rate", "hcm_sync", M("AVG(CAST(synced AS double))", "Sync rate"), "Sync rate", ".1%", f, 18)


def bar(tab, row, width, name, ds, x, metrics, groupby=(), height=50, fmt="SMART_NUMBER", stack=False,
        horizontal=False, filters=(), sort_by_metric=True, temporal=False, y_max=None, **extra):
    p = dict(x_axis=x, metrics=metrics, groupby=list(groupby), adhoc_filters=list(filters), row_limit=10000,
             orientation="horizontal" if horizontal else "vertical", y_axis_format=fmt, show_legend=True,
             legendOrientation="top", legendType="scroll", rich_tooltip=True, show_value=False,
             stack="Stack" if stack else None, color_scheme="supersetColors", truncate_metric=True,
             x_axis_title_margin=15, y_axis_title_margin=15, y_axis_bounds=[0, y_max],
             xAxisLabelRotation=45 if not horizontal else 0, zoomable=False)
    if temporal:
        p.update(time_grain_sqla="P1D", x_axis_time_format="%d %b", x_axis_sort_asc=True)
        p["adhoc_filters"].append(TIME_F())
    elif sort_by_metric:
        p.update(x_axis_sort=metrics[0]["label"], x_axis_sort_asc=False)
    p.update(extra)
    chart(tab, row, width, height, name, ds, "echarts_timeseries_bar", **p)


def line(tab, row, width, name, ds, metrics, groupby=(), height=50, fmt="SMART_NUMBER", filters=(), **extra):
    p = dict(x_axis="event_date", time_grain_sqla="P1D", metrics=metrics, groupby=list(groupby),
             adhoc_filters=list(filters) + [TIME_F()], row_limit=10000, y_axis_format=fmt, show_legend=True,
             legendOrientation="top", rich_tooltip=True, markerEnabled=True, x_axis_time_format="%d %b",
             color_scheme="supersetColors", y_axis_bounds=[0, None])
    p.update(extra)
    chart(tab, row, width, height, name, ds, "echarts_timeseries_line", **p)


def pie(tab, row, width, name, ds, groupby, metric, height=50, filters=()):
    chart(tab, row, width, height, name, ds, "pie", groupby=[groupby], metric=metric, adhoc_filters=list(filters),
          donut=True, show_labels=True, label_type="key_percent", show_legend=True, legendOrientation="bottom",
          color_scheme="supersetColors", row_limit=100, outerRadius=70, innerRadius=35, number_format="SMART_NUMBER")


def table(tab, row, width, name, ds, groupby, metrics, height=60, order=None, filters=(), percent=(), formats=None,
          cond=None, row_limit=1000):
    chart(tab, row, width, height, name, ds, "table", query_mode="aggregate", groupby=groupby, metrics=metrics,
          percent_metrics=list(percent), adhoc_filters=list(filters), row_limit=row_limit,
          timeseries_limit_metric=order or metrics[0], order_desc=True, server_pagination=False,
          include_search=True, page_length=10, show_cell_bars=True, color_pn=True, allow_rearrange_columns=True,
          column_config=formats or {}, conditional_formatting=cond or [])


def gauge(tab, row, width, name, ds, metric, filters=(), height=36):
    chart(tab, row, width, height, name, ds, "gauge_chart", metric=metric, groupby=[], adhoc_filters=list(filters),
          min_val=0, max_val=100, start_angle=210, end_angle=-30, number_format=",.1f", value_formatter="{value}%",
          show_progress=True, overlap=False, round_cap=True, show_pointer=False, show_split_line=False, show_axis_label=False,
          show_axis_tick=False, split_number=5, font_size=14, color_scheme="supersetColors",
          intervals="50,80,100", interval_color_indices="9,6,4", row_limit=10)


def choropleth(tab, row, width, name, metric, scheme="schemeRdYlGn", height=70, legend=".0f", tooltip=("district",),
               ds="hcm_map_coverage"):
    chart(tab, row, width, height, name, ds, "deck_polygon",
          line_column="polygon", line_type="json", metric=metric, adhoc_filters=[],
          point_radius_fixed={"type": "fix", "value": 1000}, filled=True, stroked=True, extruded=False,
          fill_color_picker=ORANGE, stroke_color_picker={"r": 90, "g": 90, "b": 90, "a": 1}, line_width=1,
          line_width_unit="pixels", linear_color_scheme=scheme, num_buckets="5", break_points=[],
          legend_position="tr", legend_format=legend, opacity=80, multiplier=1, reverse_long_lat=False,
          mapbox_style=TILE, viewport=VIEWPORT, autozoom=False, js_columns=[], js_data_mutator="",
          js_tooltip="", js_onclick_href="", tooltip_contents=list(tooltip), row_limit=1000,
          table_filter=False, time_range="No filter", granularity_sqla=None)


def hexmap(tab, row, width, name, ds, size_sql, size_label, height=70, grid=18, filters=(), scheme="oranges"):
    """Clustered event layer: deck.gl screen grid re-aggregates by pixel cell at every zoom level,
    so national view shows clusters and zooming into a district resolves them."""
    chart(tab, row, width, height, name, ds, "deck_screengrid",
          spatial={"type": "latlong", "latCol": "latitude", "lonCol": "longitude"},
          size=M(size_sql, size_label), grid_size=grid, color_picker=ORANGE,
          mapbox_style=TILE, viewport=VIEWPORT, row_limit=50000, adhoc_filters=list(filters),
          autozoom=False, js_columns=[], js_data_mutator="", js_tooltip="", js_onclick_href="",
          time_range="No filter")


def heatmap(tab, row, width, name, ds, size_sql, size_label, height=70, filters=()):
    chart(tab, row, width, height, name, ds, "deck_heatmap",
          spatial={"type": "latlong", "latCol": "latitude", "lonCol": "longitude"},
          size=M(size_sql, size_label), intensity=1, radius_pixels=25, linear_color_scheme="oranges",
          mapbox_style=TILE, viewport=VIEWPORT, row_limit=50000, adhoc_filters=list(filters), autozoom=False,
          js_columns=[], js_data_mutator="", js_tooltip="", js_onclick_href="", time_range="No filter")


def scatter(tab, row, width, name, ds, dimension=None, height=70, radius=1500, color=ORANGE, filters=(), tooltip=()):
    p = dict(spatial={"type": "latlong", "latCol": "latitude", "lonCol": "longitude"},
             point_radius_fixed={"type": "fix", "value": radius}, point_unit="square_m", min_radius=2, max_radius=40,
             multiplier=1, color_picker=color, mapbox_style=TILE, viewport=VIEWPORT, row_limit=10000,
             adhoc_filters=list(filters), autozoom=False, js_columns=[], js_data_mutator="", js_tooltip="",
             js_onclick_href="", time_range="No filter", tooltip_contents=list(tooltip))
    if dimension:
        p.update(dimension=dimension, color_scheme="supersetColors", legend_position="tr", legend_format=None)
    chart(tab, row, width, height, name, ds, "deck_scatter", **p)


def markdown(tab, row, width, height, text):
    CHARTS.append(dict(tab=tab, row=row, width=width, height=height, markdown=text))


# ------------------------------------------------------------------ dashboard definition
PCT = lambda num, den: f"CAST({num} AS double) / NULLIF({den}, 0)"
MR = [F("product", "IN", ["MR"])]
IPV = [F("product", "IN", ["IPV"])]

BANNER = """<div style="padding:4px 2px;font-family:Inter,Roboto,sans-serif">
<span style="font-size:13px;color:#666">Namibia · NAM-09-01-IPV-MR_NID · Round 1 · 9-19 Nov 2026 · 14 regions · 36 districts</span><br/>
<span style="font-size:12px;color:#888">{text}</span></div>"""

def define():
    # ---------------- Overview
    T = "Overview"
    markdown(T, 0, 12, 10, BANNER.format(text="Live from HCM Elasticsearch via Trino (cache 60s). "
             "Targets: microplan (fIPV 4-59 months = 95% of U5; MR 9 months-<10 years). "
             "District shapes are approximate (OSM / geoBoundaries) until official shapefiles are supplied."))
    sync_strip(T, "Frontline workers", "Frontline workers")
    gauge(T, 2, 3, "Overview: MR coverage %", "hcm_coverage", M("100.0*SUM(doses)/SUM(target)", "MR coverage %"), MR)
    gauge(T, 2, 3, "Overview: fIPV coverage %", "hcm_coverage", M("100.0*SUM(doses)/SUM(target)", "fIPV coverage %"), IPV)
    big(T, 2, 2, "Overview: total doses administered", "hcm_coverage", M("SUM(doses)", "Doses"),
        "Doses administered (MR + fIPV)", ",d", height=36)
    big(T, 2, 2, "Overview: both vaccines 9-59m", "hcm_coadmin", M(PCT("SUM(both_9_59)", "SUM(children_9_59)"), "Both"),
        "Children 9-59 m who got both vaccines", ".1%", height=36)
    big(T, 2, 2, "Overview: progress vs plan", "hcm_coverage", M(PCT("SUM(doses)", "SUM(planned_to_date)"), "vs plan"),
        "Doses vs plan to date (day-based)", ".0%", height=36)
    big(T, 3, 2, "Overview: MR wastage", "hcm_wastage", M(PCT("SUM(doses_wasted)", "SUM(doses_opened)"), "MR wastage"),
        "MR wastage (plan 5%)", ".1%", MR)
    big(T, 3, 2, "Overview: fIPV wastage", "hcm_wastage", M(PCT("SUM(doses_wasted)", "SUM(doses_opened)"), "IPV wastage"),
        "fIPV wastage (plan 5%)", ".1%", IPV)
    big(T, 3, 2, "Overview: stores at risk", "hcm_stock_position",
        M("COUNT(DISTINCT CASE WHEN stock_status IN ('Stock-out risk','Insufficient for remaining days') THEN facility_code END)", "At risk"),
        "District stores short for remaining days", ",d", [F("product", "IN", ["MR", "IPV"])])
    big(T, 3, 2, "Overview: complaints resolved", "hcm_complaints_daily", M(PCT("SUM(resolved)", "SUM(complaints)"), "Resolved"),
        "Complaints resolved", ".0%")
    big(T, 3, 2, "Overview: downsync rate", "hcm_sync", M("AVG(CAST(synced AS double))", "Downsync"),
        "Vaccinators downsynced", ".0%", [F("user_group", "IN", ["Vaccinators downsynced"])])
    big(T, 3, 2, "Overview: GPS / record issues", "hcm_dq_district",
        M(PCT("SUM(missing_gps + low_accuracy + outside_district + duplicates)", "SUM(records)"), "DQ"),
        "Records with GPS / duplicate issues", ".1%")
    choropleth(T, 4, 6, "Overview map: MR coverage % by district", M("MAX(mr_coverage_pct)", "MR coverage %"))
    hexmap(T, 4, 6, "Overview map: vaccination events (clustered)", "hcm_map_delivery_tiles", "SUM(doses)", "Doses")
    bar(T, 5, 6, "Overview: coverage by region", "hcm_coverage", "region",
        [M(PCT("SUM(doses)", "SUM(target)"), "Coverage")], ["product_label"], fmt=".0%")
    line(T, 5, 6, "Overview: planned vs actual (cumulative % of target)", "hcm_planned_vs_actual",
         [M(PCT("SUM(actual_cum_doses)", "SUM(target)"), "Actual"), M(PCT("SUM(planned_cum_doses)", "SUM(target)"), "Planned")],
         ["product_label"], fmt=".0%")

    # ---------------- Coverage
    T = "Coverage"
    sync_strip(T, "Frontline workers", "Frontline workers")
    bar(T, 2, 12, "Coverage % by district and vaccine", "hcm_coverage", "district",
        [M(PCT("SUM(doses)", "SUM(target)"), "Coverage")], ["product_label"], fmt=".0%", height=55)
    choropleth(T, 3, 4, "Coverage map: MR coverage %", M("MAX(mr_coverage_pct)", "MR coverage %"), height=60)
    choropleth(T, 3, 4, "Coverage map: fIPV coverage %", M("MAX(ipv_coverage_pct)", "fIPV coverage %"), height=60)
    choropleth(T, 3, 4, "Coverage map: MR progress vs plan to date %", M("MAX(mr_vs_plan_pct)", "MR vs plan %"), height=60)
    hexmap(T, 4, 6, "Coverage map: vaccination events clustered (filter by vaccine / mode)",
           "hcm_map_delivery_tiles", "SUM(doses)", "Doses", grid=8000)
    heatmap(T, 4, 6, "Coverage map: households visited (house-to-house)", "hcm_map_registration_tiles",
            "SUM(households)", "Households")
    line(T, 5, 6, "Coverage: planned vs actual cumulative", "hcm_planned_vs_actual",
         [M(PCT("SUM(actual_cum_doses)", "SUM(target)"), "Actual"), M(PCT("SUM(planned_cum_doses)", "SUM(target)"), "Planned")],
         ["product_label"], fmt=".0%")
    bar(T, 5, 6, "Coverage: daily doses by delivery mode", "hcm_delivery_daily", "event_date",
        [M("SUM(doses)", "Doses")], ["delivery_mode"], stack=True, temporal=True)
    bar(T, 6, 4, "Coverage: doses by age group", "hcm_age", "age_group", [M("SUM(doses)", "Doses")], ["product_label"],
        sort_by_metric=False, x_axis_sort_asc=True)
    pie(T, 6, 4, "Coverage: doses by delivery mode", "hcm_delivery_daily", "delivery_mode", M("SUM(doses)", "Doses"),
        filters=[TIME_F()])
    bar(T, 6, 4, "Coverage: missed opportunities by reason", "hcm_delivery_daily", "reason", [M("SUM(records)", "Children")],
        ["product_label"], stack=True, filters=[F("status", "NOT IN", ["ADMINISTRATION_SUCCESS"]), TIME_F()])
    scatter(T, 7, 6, "Coverage map: missed / refused children (latest 10k events)", "hcm_points_missed",
            dimension="reason", radius=1200, tooltip=("district", "reason", "product_label"), filters=[TIME_F()])
    bar(T, 7, 6, "Coverage: children 9-59 m receiving both vaccines", "hcm_coadmin", "district",
        [M(PCT("SUM(both_9_59)", "SUM(children_9_59)"), "Both vaccines")], fmt=".0%", y_max=1)
    bar(T, 8, 6, "Coverage: registrations by gender", "hcm_registration_daily", "gender", [M("SUM(registrations)", "Children")],
        filters=[TIME_F()])
    bar(T, 8, 6, "Coverage: household visit outcome", "hcm_household_daily", "visit_outcome", [M("SUM(households)", "Households")],
        filters=[TIME_F()])
    table(T, 9, 12, "Coverage summary by district", "hcm_coverage", ["region", "district", "product_label"],
          [M("SUM(target)", "Target"), M("SUM(doses)", "Administered"), M(PCT("SUM(doses)", "SUM(target)"), "Coverage"),
           M(PCT("SUM(doses)", "SUM(planned_to_date)"), "vs plan to date"), M("SUM(target)-SUM(doses)", "Remaining"),
           M("SUM(attempts)-SUM(doses)", "Not administered")],
          formats={"Coverage": {"d3NumberFormat": ".1%"}, "vs plan to date": {"d3NumberFormat": ".0%"}},
          cond=[{"colorScheme": "#ACE1C4", "column": "vs plan to date", "operator": "≥", "targetValue": 0.9},
                {"colorScheme": "#FDE380", "column": "vs plan to date", "operator": "<", "targetValue": 0.9},
                {"colorScheme": "#EFA1AA", "column": "vs plan to date", "operator": "<", "targetValue": 0.7}],
          height=70, row_limit=200)

    # ---------------- Inventory
    T = "Inventory"
    sync_strip(T, "Warehouses", "Warehouses")
    dst = [F("level", "IN", [3])]
    big(T, 2, 3, "Inventory: MR vials in district stores", "hcm_stock_position", M("SUM(stock_in_hand)", "MR vials"),
        "MR vials in hand (district stores)", ",d", dst + MR)
    big(T, 2, 3, "Inventory: fIPV vials in district stores", "hcm_stock_position", M("SUM(stock_in_hand)", "IPV vials"),
        "fIPV vials in hand (district stores)", ",d", dst + IPV)
    big(T, 2, 3, "Inventory: receipt discrepancy", "hcm_stock_discrepancy", M("SUM(discrepancy)", "Units"),
        "Units dispatched but not received", ",d")
    big(T, 2, 3, "Inventory: AD syringes in district stores", "hcm_stock_position", M("SUM(stock_in_hand)", "ADS"),
        "AD syringes in hand (0.5 + 0.1 mL)", ",d", dst + [F("product", "IN", ["ADS_05", "ADS_01"])])
    bar(T, 3, 6, "Inventory: days of stock left by district", "hcm_stock_position", "district",
        [M("SUM(stock_in_hand)/NULLIF(SUM(daily_use),0)", "Days of stock")], ["product_label"],
        filters=dst + [F("product", "IN", ["MR", "IPV"])], fmt=",.1f", sort_by_metric=False, x_axis_sort_asc=True,
        x_axis_sort="Days of stock")
    bar(T, 3, 6, "Inventory: wastage % by district (plan 5%)", "hcm_wastage", "district",
        [M(PCT("SUM(doses_wasted)", "SUM(doses_opened)"), "Wastage")], ["product_label"], fmt=".1%")
    scatter(T, 4, 6, "Inventory map: stores by stock status", "hcm_stock_position", dimension="stock_status",
            radius=12000, filters=[F("product", "IN", ["MR"])], tooltip=("facility_name", "stock_status", "days_of_stock"))
    chart(T, 4, 6, 70, "Inventory map: stock movements (national > region > district)", "hcm_stock_arcs", "deck_arc",
          start_spatial={"type": "latlong", "latCol": "source_lat", "lonCol": "source_lon"},
          end_spatial={"type": "latlong", "latCol": "target_lat", "lonCol": "target_lon"},
          color_picker=ORANGE, target_color_picker=BLUE, stroke_width=2, mapbox_style=TILE, viewport=VIEWPORT,
          row_limit=5000, adhoc_filters=[F("product", "IN", ["MR"])], autozoom=False, js_columns=[], js_data_mutator="",
          js_tooltip="", js_onclick_href="", time_range="No filter", legend_position="tr")
    choropleth(T, 5, 6, "Inventory map: MR wastage % by district", M("MAX(mr_wastage_pct)", "MR wastage %"), scheme="oranges",
               legend=".1f", ds="hcm_map_inventory")
    choropleth(T, 5, 6, "Inventory map: MR days of stock left", M("MAX(mr_days_of_stock)", "MR days of stock"), legend=".1f", ds="hcm_map_inventory")
    chart(T, 6, 6, 60, "Inventory: stock flow (vials, MR)", "hcm_stock_flow", "sankey_v2", source="source", target="target",
          metric=M("SUM(quantity)", "Vials"), adhoc_filters=[F("product", "IN", ["MR"])], row_limit=10000,
          color_scheme="supersetColors")
    line(T, 6, 6, "Inventory: daily vials issued to teams vs returned", "hcm_stock_tx",
         [M("SUM(CASE WHEN tx_type='DISPATCHED' AND receiver_type='TEAM' THEN quantity END)", "Issued to teams"),
          M("SUM(CASE WHEN tx_type='RETURNED' AND sender_type='TEAM' THEN quantity END)", "Returned by teams")],
         ["product_label"], filters=[F("product", "IN", ["MR", "IPV"])])
    table(T, 7, 12, "Inventory: stock discrepancy report (dispatched vs received)", "hcm_stock_discrepancy",
          ["receiving_facility", "facility_type", "sender_name", "product_label", "waybill"],
          [M("SUM(sent)", "Sent"), M("SUM(received)", "Received"), M("SUM(discrepancy)", "Discrepancy")],
          order=M("SUM(discrepancy)", "Discrepancy"), filters=[FSQL("discrepancy <> 0")],
          cond=[{"colorScheme": "#EFA1AA", "column": "Discrepancy", "operator": ">", "targetValue": 0}], height=55)
    table(T, 8, 12, "Inventory: stock position by store", "hcm_stock_position",
          ["facility_name", "facility_type", "product_label", "stock_status"],
          [M("SUM(received)", "Received"), M("SUM(dispatched)", "Dispatched"), M("SUM(returned)", "Returned"),
           M("SUM(stock_in_hand)", "In hand"), M("SUM(daily_use)", "Daily use (3-day avg)"),
           M("SUM(stock_in_hand)/NULLIF(SUM(daily_use),0)", "Days of stock")],
          order=M("SUM(stock_in_hand)", "In hand"), formats={"Days of stock": {"d3NumberFormat": ",.1f"},
                                                              "Daily use (3-day avg)": {"d3NumberFormat": ",.0f"}},
          cond=[{"colorScheme": "#EFA1AA", "column": "Days of stock", "operator": "<", "targetValue": 3}],
          height=60, row_limit=500)

    # ---------------- Data quality
    T = "Data Quality"
    sync_strip(T, "Vaccinators downsynced", "Vaccinators downsynced")
    for name, col, label in (("missing GPS", "missing_gps", "Records without GPS"),
                             ("low accuracy", "low_accuracy", "GPS accuracy > 100 m"),
                             ("outside district", "outside_district", "GPS outside assigned district"),
                             ("duplicates", "duplicates", "Duplicate doses (same child)"),
                             ("incomplete", "incomplete", "Incomplete registrations"),
                             ("off hours", "off_hours", "Recorded 20:00-06:00")):
        big(T, 2, 2, f"DQ: {name}", "hcm_dq_district", M(f"SUM({col})", label), label, ",d")
    table(T, 3, 12, "Data quality summary by district", "hcm_dq_district", ["region", "district"],
          [M("SUM(records)", "Delivery records"), M(PCT("SUM(missing_gps)", "SUM(records)"), "No GPS"),
           M(PCT("SUM(low_accuracy)", "SUM(records)"), "Low accuracy"),
           M(PCT("SUM(outside_district)", "SUM(records)"), "Outside district"),
           M("SUM(duplicates)", "Duplicates"), M(PCT("SUM(incomplete)", "SUM(registrations)"), "Incomplete reg."),
           M("SUM(off_hours)", "Off-hours")],
          order=M(PCT("SUM(outside_district)", "SUM(records)"), "Outside district"),
          formats={k: {"d3NumberFormat": ".1%"} for k in ("No GPS", "Low accuracy", "Outside district", "Incomplete reg.")},
          height=60, row_limit=100)
    choropleth(T, 4, 6, "DQ map: % records with GPS / duplicate issues", M("MAX(gps_dq_issue_pct)", "Issue %"),
               scheme="oranges", legend=".1f", ds="hcm_map_quality")
    scatter(T, 4, 6, "DQ map: low-accuracy GPS points (> 100 m)", "hcm_points_gps_issues", radius=1500,
            tooltip=("district", "accuracy_m", "user_id"), filters=[TIME_F()])
    table(T, 5, 6, "DQ: users recording > 120 doses in a day", "hcm_dq_users", ["district", "user_id", "event_date"],
          [M("SUM(doses_recorded)", "Doses")], filters=[FSQL("doses_recorded > 120"), TIME_F()], height=55)
    table(T, 5, 6, "DQ: teams with < 20 doses in a day", "hcm_dq_teams", ["district", "team_id", "team_type", "event_date"],
          [M("SUM(doses_recorded)", "Doses")], filters=[FSQL("doses_recorded < 20"), TIME_F()], height=55)
    bar(T, 6, 6, "DQ: frontline sync rate by district", "hcm_sync", "district",
        [M("AVG(CAST(synced AS double))", "Sync rate")], fmt=".0%", filters=[F("user_group", "IN", ["Frontline workers"])],
        sort_by_metric=True, x_axis_sort_asc=True, y_max=1)
    bar(T, 6, 6, "DQ: downsync rate by district", "hcm_sync", "district",
        [M("AVG(CAST(synced AS double))", "Downsync rate")], fmt=".0%",
        filters=[F("user_group", "IN", ["Vaccinators downsynced"])], x_axis_sort_asc=True, y_max=1)

    # ---------------- Supervision
    T = "Supervision"
    sync_strip(T, "Supervisors", "Supervisors")
    for i, (lvl, by) in enumerate((("1 Team supervisors", "district"), ("2 District supervisors", "district"),
                                   ("3 Regional supervisors", "region"), ("4 National supervisors", "region"))):
        bar(T, 2 + i // 2, 6, f"Supervision: {lvl[2:]} checklist completion rate", "hcm_checklist_completion", by,
            [M(PCT("SUM(submitted)", "SUM(expected)"), "Completion rate")], fmt=".0%",
            filters=[F("supervisor_level", "IN", [lvl])], y_max=1.2)
    bar(T, 4, 6, "Supervision: checklist findings (% yes)", "hcm_checklist_findings", "question",
        [M(PCT("SUM(yes_count)", "SUM(submissions)"), "% yes")], fmt=".0%", horizontal=True, filters=[TIME_F()],
        sort_by_metric=True, x_axis_sort_asc=True, y_max=1)
    bar(T, 4, 6, "Supervision: checklists submitted per day", "hcm_checklist_daily", "event_date",
        [M("SUM(submissions)", "Checklists")], ["supervisor_role"], stack=True, temporal=True)
    scatter(T, 5, 6, "Supervision map: checklist locations", "hcm_points_checklists", dimension="supervisor_role",
            radius=2500, tooltip=("district", "checklist_name"), filters=[TIME_F()])
    choropleth(T, 5, 6, "Supervision map: checklist completion % by district", M("MAX(checklist_completion_pct)", "Completion %"),
               legend=".0f", ds="hcm_map_supervision")
    bar(T, 6, 12, "Supervision: frontline data sync rate by district", "hcm_sync", "district",
        [M("AVG(CAST(synced AS double))", "Sync rate")], fmt=".0%", filters=[F("user_group", "IN", ["Frontline workers"])],
        x_axis_sort_asc=True, y_max=1, height=45)

    # ---------------- Complaints
    T = "Complaints"
    big(T, 1, 3, "Complaints: total", "hcm_complaints_daily", M("SUM(complaints)", "Complaints"), "Total complaints", ",d",
        [TIME_F()], 18)
    big(T, 1, 3, "Complaints: resolved", "hcm_complaints_daily", M("SUM(resolved)", "Resolved"), "Resolved", ",d", [TIME_F()], 18)
    big(T, 1, 3, "Complaints: resolution rate", "hcm_complaints_daily", M(PCT("SUM(resolved)", "SUM(complaints)"), "Rate"),
        "Complaints resolved", ".0%", [TIME_F()], 18)
    big(T, 1, 3, "Complaints: avg resolution hours", "hcm_complaints_daily", M("SUM(resolution_hours)/NULLIF(SUM(resolved),0)", "Hours"),
        "Average hours to resolve", ",.1f", [TIME_F()], 18)
    bar(T, 2, 6, "Complaints by type and status", "hcm_complaints_daily", "complaint_type", [M("SUM(complaints)", "Complaints")],
        ["status_group"], stack=True, filters=[TIME_F()])
    bar(T, 2, 6, "Complaints per day", "hcm_complaints_daily", "event_date", [M("SUM(complaints)", "Complaints")],
        ["status_group"], stack=True, temporal=True)
    scatter(T, 3, 6, "Complaints map: complaint locations", "hcm_points_complaints", dimension="complaint_type",
            radius=3000, tooltip=("district", "complaint_type", "status"), filters=[TIME_F()])
    choropleth(T, 3, 6, "Complaints map: complaints per 10,000 MR doses", M("MAX(complaints_per_10k)", "Per 10k doses"),
               scheme="oranges", legend=".1f", ds="hcm_map_complaints")
    table(T, 4, 12, "Complaints summary by district", "hcm_complaints_daily", ["region", "district"],
          [M("SUM(complaints)", "Complaints"), M("SUM(resolved)", "Resolved"),
           M(PCT("SUM(resolved)", "SUM(complaints)"), "Resolution rate"),
           M("SUM(resolution_hours)/NULLIF(SUM(resolved),0)", "Avg hours")],
          formats={"Resolution rate": {"d3NumberFormat": ".0%"}, "Avg hours": {"d3NumberFormat": ",.1f"}},
          filters=[TIME_F()], height=55, row_limit=100)


TABS = ["Overview", "Coverage", "Inventory", "Data Quality", "Supervision", "Complaints"]


def build_charts(ds_ids):
    for c in CHARTS:
        if "markdown" in c:
            continue
        params = dict(c["params"], viz_type=c["viz"], datasource=f"{ds_ids[c['ds']]}__table")
        params.setdefault("adhoc_filters", [])
        res = api("POST", "/api/v1/chart/", json={
            "slice_name": CHART_PREFIX + c["name"], "viz_type": c["viz"], "datasource_id": ds_ids[c["ds"]],
            "datasource_type": "table", "params": json.dumps(params), "cache_timeout": 60})
        c["id"] = res["id"]
        c["uuid"] = api("GET", f"/api/v1/chart/{res['id']}")["result"].get("uuid") if False else None
    print(f"  {sum(1 for c in CHARTS if 'id' in c)} charts")


def position():
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["TABS-main"]},
           "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": DASH_TITLE}},
           "TABS-main": {"type": "TABS", "id": "TABS-main", "children": [], "parents": ["ROOT_ID"]}}
    tab_of = {}
    for t in TABS:
        tid = "TAB-" + re.sub(r"\W", "", t)
        pos["TABS-main"]["children"].append(tid)
        pos[tid] = {"type": "TAB", "id": tid, "children": [], "parents": ["ROOT_ID", "TABS-main"],
                    "meta": {"text": t, "defaultText": "Tab title", "placeholder": "Tab title"}}
        rows = {}
        for i, c in enumerate(x for x in CHARTS if x["tab"] == t):
            rid = f"ROW-{re.sub(chr(92) + 'W', '', t)}-{c['row']}"
            if rid not in rows:
                rows[rid] = {"type": "ROW", "id": rid, "children": [], "parents": ["ROOT_ID", "TABS-main", tid],
                             "meta": {"background": "BACKGROUND_TRANSPARENT"}}
                pos[tid]["children"].append(rid)
            parents = ["ROOT_ID", "TABS-main", tid, rid]
            if "markdown" in c:
                mid = f"MARKDOWN-{re.sub(chr(92) + 'W', '', t)}-{i}"
                pos[mid] = {"type": "MARKDOWN", "id": mid, "children": [], "parents": parents,
                            "meta": {"width": c["width"], "height": c["height"], "code": c["markdown"]}}
                rows[rid]["children"].append(mid)
            else:
                cid = f"CHART-{c['id']}"
                pos[cid] = {"type": "CHART", "id": cid, "children": [], "parents": parents,
                            "meta": {"chartId": c["id"], "width": c["width"], "height": c["height"],
                                     "sliceName": CHART_PREFIX + c["name"],
                                     "sliceNameOverride": c["name"]}}
                rows[rid]["children"].append(cid)
                tab_of[c["id"]] = tid
        pos.update(rows)
    return pos


def native_filters(ds_ids, ds_cols):
    charts = [c for c in CHARTS if "id" in c]

    def scope(pred):
        inscope = [c["id"] for c in charts if pred(c)]
        return {"rootPath": ["ROOT_ID"], "excluded": [c["id"] for c in charts if c["id"] not in inscope]}, inscope

    def has(col):
        return lambda c: col in ds_cols[c["ds"]]

    def select(fid, name, ds, col, parents=(), desc=""):
        sc, ins = scope(has(col))
        return {"id": fid, "name": name, "filterType": "filter_select", "type": "NATIVE_FILTER",
                "targets": [{"datasetId": ds_ids[ds], "column": {"name": col}}], "description": desc,
                "controlValues": {"enableEmptyFilter": False, "defaultToFirstItem": False, "multiSelect": True,
                                  "searchAllOptions": False, "inverseSelection": False, "sortAscending": True},
                "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
                "cascadeParentIds": list(parents), "scope": sc, "chartsInScope": ins, "tabsInScope": [],
                "adhoc_filters": [], "time_range": "No filter", "requiredFirst": False}

    timed = lambda c: any(f.get("operator") == "TEMPORAL_RANGE" for f in c["params"].get("adhoc_filters", [])) \
        or c["params"].get("x_axis") == "event_date"
    tsc, tins = scope(timed)
    return [
        select("NATIVE_FILTER-region", "Region", "hcm_coverage", "region"),
        select("NATIVE_FILTER-district", "District", "hcm_coverage", "district", ["NATIVE_FILTER-region"]),
        select("NATIVE_FILTER-product", "Vaccine", "hcm_coverage", "product", desc="MR or IPV (fIPV)"),
        select("NATIVE_FILTER-mode", "Delivery mode", "hcm_delivery_daily", "delivery_mode"),
        {"id": "NATIVE_FILTER-date", "name": "Campaign date", "filterType": "filter_time", "type": "NATIVE_FILTER",
         "targets": [{}], "controlValues": {}, "description": "Applies to daily charts; coverage and maps are cumulative.",
         "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}}, "cascadeParentIds": [],
         "scope": tsc, "chartsInScope": tins, "tabsInScope": []},
    ]


CSS = """
.dashboard-header .header-title, .editable-title input { font-weight: 700; }
.dashboard-component-tabs .ant-tabs-tab-active .ant-tabs-tab-btn { color: #F47738 !important; font-weight: 600; }
.dashboard-component-tabs .ant-tabs-ink-bar { background: #F47738 !important; height: 3px !important; }
.header-title { color: #0B4B66; }
.big_number .header-line { color: #0B4B66 !important; }
"""


def build_dashboard(ds_ids, ds_cols):
    pos = position()
    meta = {"native_filter_configuration": native_filters(ds_ids, ds_cols), "cross_filters_enabled": True,
            "refresh_frequency": 300, "color_scheme": "supersetColors", "label_colors": {},
            "shared_label_colors": [], "timed_refresh_immune_slices": [], "expanded_slices": {},
            "chart_configuration": {}, "global_chart_configuration": {"scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                                                                       "chartsInScope": [c["id"] for c in CHARTS if "id" in c]}}
    res = api("POST", "/api/v1/dashboard/", json={
        "dashboard_title": DASH_TITLE, "slug": SLUG, "published": True, "css": CSS,
        "position_json": json.dumps(pos), "json_metadata": json.dumps(meta)})
    did = res["id"]
    for c in CHARTS:
        if "id" in c:
            api("PUT", f"/api/v1/chart/{c['id']}", json={"dashboards": [did]})
    return did


def main():
    login()
    print("teardown"); teardown()
    for d in find("dataset", "table_name", "hcm_district_map"):
        api("DELETE", f"/api/v1/dataset/{d['id']}")
    db = ensure_db(); print("database", db)
    ds_ids, ds_cols = create_datasets(db)
    define()
    build_charts(ds_ids)
    did = build_dashboard(ds_ids, ds_cols)
    print(f"dashboard {did}: {BASE}/superset/dashboard/{SLUG}/")


if __name__ == "__main__":
    main()

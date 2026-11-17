"""Build the IPV + MR campaign dashboard in Superset via its REST API (idempotent).

Creates: Trino database connection -> virtual datasets (tools/datasets.py) -> charts
-> one dashboard with 4 tabs (Overview, Coverage, Inventory, Data Quality) and native filters.
Re-running replaces everything it created (matched by name prefix).

    tools/.venv/bin/python -I tools/build_superset.py
"""
import json
import re
import sys
import time
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datasets import DATASETS, CAMPAIGN_DAYS  # noqa: E402

BASE = "http://localhost:8088"
DB_NAME = "HCM Elasticsearch (Trino)"
DB_URI = "trino://admin@trino:8080/hcm"
DASH_TITLE = "IPV + MR Integrated Campaign - Namibia 2026"
SLUG = "hcm-ipv-mr-namibia"
CHART_PREFIX = "[IPV-MR] "
# Namibia only: no basemap. A transparent tile hides neighbouring countries; the
# region / district polygons draw the country. Swap for OSM tiles if context is wanted:
#   tile://https://tile.openstreetmap.org/{z}/{x}/{y}.png
BLANK_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII="
TILE = "tile://data:image/png;base64," + BLANK_PNG
VIEWPORT = {"latitude": -22.4, "longitude": 18.4, "zoom": 4.3, "bearing": 0, "pitch": 0}
ZAMBEZI = {"latitude": -17.85, "longitude": 24.35, "zoom": 7.2, "bearing": 0, "pitch": 0}
ORANGE = {"r": 244, "g": 119, "b": 56, "a": 1}
GREY = {"r": 120, "g": 120, "b": 120, "a": 1}
RED = "#D03B3B"
# Point colours match the emoji dots in the map legends (dashboard markdown strips inline styles).
C_ORANGE, C_BLUE, C_GREEN = {"r": 244, "g": 144, "b": 12, "a": 1}, {"r": 42, "g": 120, "b": 214, "a": 1}, {"r": 120, "g": 177, "b": 89, "a": 1}
C_PURPLE, C_RED, C_YELLOW = {"r": 170, "g": 142, "b": 214, "a": 1}, {"r": 221, "g": 46, "b": 68, "a": 1}, {"r": 253, "g": 203, "b": 88, "a": 1}
C_WHITE = {"r": 190, "g": 190, "b": 190, "a": 1}
DOT = {id(C_ORANGE): "🟠", id(C_BLUE): "🔵", id(C_GREEN): "🟢", id(C_PURPLE): "🟣", id(C_RED): "🔴", id(C_YELLOW): "🟡",
       id(C_WHITE): "⚪"}
FACILITY_TYPES = {"Health centre": C_ORANGE, "Clinic": C_BLUE, "Outreach point": C_GREEN, "School": C_PURPLE}
COVERAGE_STATUS = {"High coverage (90%+)": C_GREEN, "Mid coverage (50-90%)": C_YELLOW, "Low coverage (below 50%)": C_RED}
STATUS_COLOURS = {"Not enough vials for target": C_RED, "Enough vials for target": C_GREEN, "No stock data": C_WHITE}


def legend_html(title, colours, note=""):
    dots = "".join(f'{DOT[id(c)]} {k}<br/>' for k, c in colours.items())
    return (f'<div style="font-family:Inter,Roboto,sans-serif;font-size:13px;line-height:2;padding:8px">'
            f'<b>{title}</b><br/>{dots}<br/><span style="opacity:.7;font-size:12px;line-height:1.5">{note}</span></div>')


s = requests.Session()


def api(method, path, **kw):
    # Superset 6.1 rate-limits the API (50 requests/second): back off and retry on 429.
    for attempt in range(8):
        r = s.request(method, BASE + path, **kw)
        if r.status_code != 429:
            break
        time.sleep(0.5 * (attempt + 1))
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
    return r.json() if r.text else {}


def login():
    tok = api("POST", "/api/v1/security/login",
              json={"username": "admin", "password": "admin", "provider": "db", "refresh": True})["access_token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    s.headers["Referer"] = BASE


def find(resource, col, value, opr="eq"):
    q = json.dumps({"filters": [{"col": col, "opr": opr, "value": value}], "page_size": 100})
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
    for prefix in ("hcm_", "field_"):   # datasets of earlier builds (incl. ones since removed)
        for d in find("dataset", "table_name", prefix, "sw"):
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
        print(f"  dataset {name:22s} id={did} cols={len(cols[name])}")
    return ids, cols


def campaign_days_remaining():
    """Days left after the latest day with field data (for the days-of-stock reference line)."""
    from datasets import ds_campaign_day
    r = api("POST", "/api/v1/sqllab/execute/", json={"database_id": ensure_db(), "sql": ds_campaign_day(),
                                                     "schema": "default", "runAsync": False})
    day = r["data"][0]["campaign_day"]
    return day, CAMPAIGN_DAYS - day


def data_date_range():
    """First and last date with field data, as a Superset time range (end is exclusive)."""
    import datetime as dt
    sql = "SELECT min(CAST(event_date AS date)) AS d0, max(CAST(event_date AS date)) AS d1 FROM hcm.default.\"field-site-day-v1\""
    r = api("POST", "/api/v1/sqllab/execute/", json={"database_id": ensure_db(), "sql": sql, "schema": "default", "runAsync": False})
    d0, d1 = (dt.date.fromisoformat(str(r["data"][0][k])[:10]) for k in ("d0", "d1"))
    return d0, d1, f"{d0.isoformat()} : {(d1 + dt.timedelta(days=1)).isoformat()}"


DATE_RANGE = None   # set in main(): the campaign-date filter is preselected to the dates that have data


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


def LINE_AT(value, label, color=RED):
    """Horizontal reference line (formula annotation)."""
    return {"name": label, "annotationType": "FORMULA", "sourceType": "", "value": str(value), "show": True,
            "showLabel": True, "color": color, "width": 2, "style": "dashed", "opacity": "", "hideLine": False,
            "overrides": {}, "titleColumn": "", "descriptionColumns": [], "timeColumn": "", "intervalEndColumn": "",
            "showMarkers": False}


CHARTS = []  # (tab, row, width, height, name, dataset, viz, params); tab None = map layer used by a multi-layer map


def chart(tab, row, width, height, name, ds, viz, **p):
    CHARTS.append(dict(tab=tab, row=row, width=width, height=height, name=name, ds=ds, viz=viz, params=p))


def big(tab, row, width, name, ds, metric, title="", fmt="SMART_NUMBER", filters=(), height=20, note=""):
    """KPI card: `title` is the card heading on the dashboard, the number fills the card."""
    chart(tab, row, width, height, name, ds, "big_number_total", metric=metric, subheader=note, subtitle=note,
          y_axis_format=fmt, header_font_size=0.5, subheader_font_size=0.15, adhoc_filters=list(filters))
    CHARTS[-1]["title"] = title or name


def bar(tab, row, width, name, ds, x, metrics, groupby=(), height=50, fmt="SMART_NUMBER", stack=False,
        horizontal=False, filters=(), sort_by_metric=True, temporal=False, y_max=None, lines=(), values=True,
        y_min=0, **extra):
    p = dict(x_axis=x, metrics=metrics, groupby=list(groupby), adhoc_filters=list(filters), row_limit=10000,
             orientation="horizontal" if horizontal else "vertical", y_axis_format=fmt, show_legend=True,
             legendOrientation="top", legendType="scroll", rich_tooltip=True, show_value=values,
             stack="Stack" if stack else None, color_scheme="supersetColors", truncate_metric=True,
             x_axis_title_margin=15, y_axis_title_margin=15, y_axis_bounds=[y_min, y_max],
             xAxisLabelRotation=45 if not horizontal else 0, zoomable=False, annotation_layers=list(lines))
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


def pie(tab, row, width, name, ds, groupby, metric, height=50, filters=(), legend=True, label="value_percent"):
    """Simple pie: direct labels with value and %, no legend by default."""
    chart(tab, row, width, height, name, ds, "pie", groupby=[groupby], metric=metric, adhoc_filters=list(filters),
          donut=False, show_labels=True, label_type=label, labels_outside=True, label_line=True,
          show_legend=legend, legendOrientation="bottom", color_scheme="supersetColors", row_limit=100,
          outerRadius=58, number_format="SMART_NUMBER", sort_by_metric=True, show_total=False)


def table(tab, row, width, name, ds, groupby, metrics, height=60, order=None, filters=(), formats=None,
          cond=None, row_limit=1000, desc=True):
    chart(tab, row, width, height, name, ds, "table", query_mode="aggregate", groupby=groupby, metrics=metrics,
          adhoc_filters=list(filters), row_limit=row_limit,
          timeseries_limit_metric=order or metrics[0], order_desc=desc, server_pagination=False,
          include_search=True, page_length=10, show_cell_bars=False, color_pn=True, allow_rearrange_columns=True,
          column_config=formats or {}, conditional_formatting=cond or [])


def coverage_bars(tab, row, width, name, x, height=50):
    """Coverage % bars (MR and IPV side by side) with the absolute numbers on hover. Superset's bar chart can only
    show the plotted metric in its tooltip, so a mixed chart adds children vaccinated and target as tiny points on a
    second axis: they appear in the hover, not as bars."""
    cov = M("SUM(CASE WHEN measure = 'Vaccinated' THEN children END) / NULLIF(SUM(CASE WHEN measure = 'Target' THEN children END), 0)",
            "Coverage")
    chart(tab, row, width, height, name, "field_coverage_long", "mixed_timeseries", x_axis=x,
          metrics=[cov], groupby=["product_label"], adhoc_filters=[TIME_F()], seriesType="bar", show_value=True,
          only_total=False, y_axis_format=".0%", y_axis_bounds=[0, None], stack=False,
          metrics_b=[M("SUM(children)", "Children")], groupby_b=["product_label", "measure"],
          adhoc_filters_b=[TIME_F()], seriesTypeB="scatter", markerEnabledB=True, markerSizeB=1, show_valueB=False,
          yAxisIndex=0, yAxisIndexB=1, y_axis_format_secondary=",d", show_legend=True, legendOrientation="top",
          legendType="scroll", rich_tooltip=True, color_scheme="supersetColors",
          xAxisLabelRotation=45, row_limit=10000, row_limit_b=10000, zoomable=False, truncateYAxis=False,
          x_axis_sort_asc=True)


def handlebars(tab, row, width, name, ds, metrics, template, filters=(), height=20):
    chart(tab, row, width, height, name, ds, "handlebars", query_mode="aggregate", groupby=[], metrics=metrics,
          adhoc_filters=list(filters), row_limit=10, handlebarsTemplate=template, styleTemplate="")




# Same legend on every coverage map, red (low) > amber (mid) > green (high):
# <50 red, 50-70 orange, 70-80 amber, 80-90 light green, 90-100 green, 100+ dark green
COVERAGE_BREAKS = ["0", "50", "70", "80", "90", "100", "200"]


def choropleth(tab, row, width, name, ds, metric, height=60, legend=".0f", tooltip=("region",), viewport=VIEWPORT,
               scheme="schemeRdYlGn", breaks=COVERAGE_BREAKS):
    """Red-amber-green coverage scale with a legend. Areas with no uploaded data stay uncoloured."""
    chart(tab, row, width, height, name, ds, "deck_polygon",
          line_column="polygon", line_type="json", metric=metric, adhoc_filters=[],
          point_radius_fixed={"type": "fix", "value": 1000}, filled=True, stroked=True, extruded=False,
          fill_color_picker={"r": 255, "g": 255, "b": 255, "a": 0}, stroke_color_picker=GREY, line_width=1,
          line_width_unit="pixels", linear_color_scheme=scheme, num_buckets="5", break_points=breaks,
          legend_position="br", legend_format=legend, opacity=85, multiplier=1, reverse_long_lat=False,
          mapbox_style=TILE, viewport=viewport, autozoom=False, js_columns=[], js_data_mutator="",
          js_tooltip="", js_onclick_href="", tooltip_contents=list(tooltip), row_limit=1000,
          table_filter=False, time_range="No filter", granularity_sqla=None)


def scatter(tab, row, width, name, ds, dimension=None, height=60, radius=2500, color=ORANGE, filters=(), tooltip=(),
            viewport=ZAMBEZI, radius_metric=None):
    p = dict(spatial={"type": "latlong", "latCol": "latitude", "lonCol": "longitude"},
             point_radius_fixed={"type": "metric", "value": radius_metric} if radius_metric else {"type": "fix", "value": radius},
             point_unit="square_m", min_radius=4, max_radius=40,
             multiplier=1, color_picker=color, mapbox_style=TILE, viewport=viewport, row_limit=10000,
             adhoc_filters=list(filters), autozoom=False, js_columns=[], js_data_mutator="", js_tooltip="",
             js_onclick_href="", time_range="No filter", tooltip_contents=list(tooltip))
    if dimension:
        p.update(dimension=dimension, color_scheme="supersetColors", legend_position="tr", legend_format=None)
    chart(tab, row, width, height, name, ds, "deck_scatter", **p)


def multimap(tab, row, width, name, layers, height=60, viewport=ZAMBEZI, ds="field_sites"):
    """Several deck.gl layers on one map (layers are charts created with tab=None)."""
    chart(tab, row, width, height, name, ds, "deck_multi", deck_slice_names=layers, mapbox_style=TILE,
          viewport=viewport, adhoc_filters=[], autozoom=True, time_range="No filter")


def point_map(tab, row, width, name, ds, column, colours, tooltip, filters=(), legend_title="", note="",
              height=60, legend_width=3, radius_metric=None, radius=1800):
    """Namibia-only point map: district outlines + one point layer per category (fixed colour) + legend.
    deck.gl multi-layer maps cannot colour points by a column, so each category is its own layer."""
    if not any(c.get("name") == "Layer: district outlines" for c in CHARTS):
        choropleth(None, 0, 0, "Layer: district outlines", "field_district_map", M("MAX(CAST(NULL AS double))", "None"),
                   tooltip=("district",), breaks=[])
    layers = ["Layer: district outlines"]
    for cat, rgb in colours.items():
        lname = f"Layer: {name} - {cat}"
        scatter(None, 0, 0, lname, ds, radius=radius, color=rgb, filters=list(filters) + [F(column, "IN", [cat])],
                tooltip=tooltip, radius_metric=radius_metric)
        layers.append(lname)
    multimap(tab, row, width, name, layers, height=height)
    markdown(tab, row, legend_width, height, legend_html(legend_title, colours, note))


def zero_dose_aefi_cards(tab, row, width=6):
    """Two cards: zero-dose children and AEFI cases (both SYNTHETIC until the field data records them)."""
    big(tab, row, width, f"{tab}: zero-dose children", "field_child_status", M("SUM(zero_dose)", "Zero-dose"),
        "Zero-dose children vaccinated", ",d", [TIME_F()], note="no prior routine dose - synthetic until recorded")
    big(tab, row, width, f"{tab}: AEFI cases", "field_child_status", M("SUM(aefi)", "AEFI"),
        "AEFI cases", ",d", [TIME_F()], note="adverse events following immunization - synthetic until recorded")


def markdown(tab, row, width, height, text):
    CHARTS.append(dict(tab=tab, row=row, width=width, height=height, markdown=text))


# ------------------------------------------------------------------ dashboard definition
PCT = lambda num, den: f"CAST({num} AS double) / NULLIF({den}, 0)"
MR = [F("product", "IN", ["MR"])]
IPV = [F("product", "IN", ["IPV"])]
VACCINES = (("MR", MR), ("IPV", IPV))
COVERAGE = M(PCT("SUM(vaccinated)", "SUM(target)"), "Coverage of target")
# Wastage (owner's instructions): MR shows the reported figure, 0.1%; IPV is calculated from the field data
# and never shows below 0% (more children than doses in opened vials counts as 0%).
MR_WASTAGE_REPORTED = 0.001
WASTAGE = M(f"CASE WHEN MIN(product) = 'MR' AND MAX(product) = 'MR' THEN {MR_WASTAGE_REPORTED} "
            f"ELSE GREATEST(CAST(0 AS double), {PCT('SUM(doses_opened) - SUM(vaccinated)', 'SUM(doses_opened)')}) END", "Wastage")

BANNER = """<div style="padding:4px 2px;font-family:Inter,Roboto,sans-serif;line-height:1.5">
<span style="font-size:13px;opacity:.8">Namibia · NAM-09-01-IPV-MR_NID · Round 1 · 9-19 Nov 2026 (11 days)</span><br/>
<span style="font-size:12px;opacity:.7">{text}</span></div>"""


def define(days_remaining):
    # ---------------- Overview
    T = "Overview"
    for v, f in VACCINES:
        r = f"1{v}"
        big(T, r, 2, f"Overview: {v} children vaccinated", "field_site_day", M("SUM(vaccinated)", "Vaccinated"),
            f"{v}: children vaccinated", ",d", f)
        big(T, r, 2, f"Overview: {v} target", "field_site_day", M("SUM(target)", "Target"),
            f"{v}: target", ",d", f, note="reporting sites and days")
        big(T, r, 2, f"Overview: {v} coverage", "field_site_day", COVERAGE, f"{v}: coverage of target", ".1%", f)
        big(T, r, 2, f"Overview: {v} wastage", "field_site_day", WASTAGE, f"{v}: wastage (allowed 5%)", ".1%", f, note="reported figure" if v == "MR" else "")
        big(T, r, 2, f"Overview: {v} vials opened", "field_site_day", M("SUM(vials_opened)", "Vials opened"),
            f"{v}: vials opened", ",d", f)
        big(T, r, 2, f"Overview: {v} sites reporting", "field_site_day", M("COUNT(DISTINCT site_code)", "Sites"),
            f"{v}: sites reporting", ",d", f)
    zero_dose_aefi_cards(T, "1Z")
    for v, f in VACCINES:
        pie(T, 2, 6, f"Overview: {v} vaccinated vs remaining to target", "field_progress_pie", "slice",
            M("SUM(children)", "Children"), filters=f + [TIME_F()])
    coverage_bars(T, 3, 6, "Overview: coverage by region (MR and IPV)", "region")
    coverage_bars(T, 3, 6, "Overview: coverage by district (MR and IPV)", "district")
    for v in ("MR", "IPV"):
        col = f"{v.lower()}_coverage_pct"
        choropleth(T, 4, 6, f"Overview map: {v} coverage % by district", "field_district_map",
                   M(f"MAX({col})", f"{v} coverage %"), tooltip=("district",))
    point_map(T, 5, 9, "Overview map: health facilities by type", "field_sites", "facility_type", FACILITY_TYPES,
              ("site_name", "facility_type", "district"), legend_title="Facility type",
              note="Facility type comes from the site name in the field database (Health Centre / Clinic); other "
                   "sites are outreach points, and Masokotwani is a school. Homba Clinic and Nchichimani have no "
                   "coordinates and sit at their district centre.")
    for v, f in VACCINES:
        pie(T, 6, 6, f"Overview: gender distribution ({v}) - synthetic", "field_children", "gender", M("SUM(children)", "Children"),
            filters=f + [TIME_F()], legend=True)

    # ---------------- Coverage
    T = "Coverage"
    zero_dose_aefi_cards(T, 0)
    # Map 1: vaccination sites coloured by coverage (lower of MR and IPV). deck.gl multi-layer maps cannot size or
    # label points by a number, so the numbers (children, MR and IPV delivered, zero-dose) are in the hover tooltip.
    point_map(T, "0m", 4, "Coverage map: vaccination sites by coverage", "field_sites", "coverage_status", COVERAGE_STATUS,
              ("Site", "Children vaccinated", "MR delivered", "IPV delivered", "MR coverage %", "IPV coverage %",
               "Zero-dose children (synthetic)"),
              legend_title="Coverage", legend_width=2,
              note="Colour = the lower of MR and IPV coverage at the site. Hover a site for children vaccinated, "
                   "MR and IPV delivered and zero-dose children.")
    # Map 2: zero-dose children (synthetic) by district, with the numbers in the tooltip
    choropleth(T, "0m", 6, "Coverage map: zero-dose children by district (synthetic)", "field_district_map",
               M("MAX(zero_dose_children)", "Zero-dose children"), tooltip=("district", "zero_dose_children", "zero_dose_pct"),
               scheme="oranges", breaks=["0", "25", "50", "75", "100", "150"], viewport=ZAMBEZI)
    for v in ("MR", "IPV"):
        col = f"{v.lower()}_coverage_pct"
        choropleth(T, 1, 6, f"Coverage map: {v} coverage % by region", "field_region_map", M(f"MAX({col})", f"{v} coverage %"))
    coverage_bars(T, 2, 6, "Coverage by region (MR and IPV)", "region")
    coverage_bars(T, 2, 6, "Coverage by district (MR and IPV)", "district")
    for v, f in VACCINES:
        bar(T, 3, 6, f"Coverage: {v} children vaccinated by age group", "field_age", "age_group",
            [M("SUM(vaccinated)", "Children vaccinated")], filters=f + [TIME_F()], sort_by_metric=False,
            x_axis_sort="age_order", x_axis_sort_asc=True, xAxisLabelRotation=0)
    bar(T, 4, 12, "Coverage by site (MR and IPV)", "field_site_day", "site_name", [COVERAGE], ["product_label"], fmt=".0%",
        filters=[TIME_F()], values=False)
    # Mixed chart so the two series look different: actual = filled area, planned = line with dot markers;
    # Superset's line chart has no dashed-line option.
    chart(T, 5, 6, 50, "Coverage: planned (line with dots) vs actual (filled), cumulative", "field_site_day",
          "mixed_timeseries", x_axis="event_date", time_grain_sqla="P1D",
          metrics=[M("SUM(vaccinated)", "Actual (vaccinated)")], groupby=["product_label"], adhoc_filters=[TIME_F()],
          seriesType="line", area=True, opacity=0.25, markerEnabled=False, rolling_type="cumsum",
          metrics_b=[M("SUM(target)", "Planned (target)")], groupby_b=["product_label"], adhoc_filters_b=[TIME_F()],
          seriesTypeB="line", areaB=False, markerEnabledB=True, markerSizeB=9, rolling_type_b="cumsum",
          yAxisIndex=0, yAxisIndexB=0, show_legend=True, legendOrientation="top", rich_tooltip=True,
          x_axis_time_format="%d %b", y_axis_format="SMART_NUMBER", color_scheme="supersetColors",
          row_limit=10000, row_limit_b=10000, zoomable=False)
    bar(T, 5, 6, "Coverage: children vaccinated per day", "field_site_day", "event_date",
        [M("SUM(vaccinated)", "Children vaccinated")], ["product_label"], temporal=True)
    pie(T, 6, 6, "Coverage: children by vaccines received", "field_child_status", "vaccine_status",
        M("SUM(children)", "Children"), filters=[TIME_F()], legend=True, label="value_percent")
    bar(T, 6, 6, "Coverage: children vaccinated by district", "field_site_day", "district",
        [M("SUM(vaccinated)", "Children vaccinated")], ["product_label"], filters=[TIME_F()])
    table(T, 7, 12, "Coverage summary by site", "field_site_day", ["district", "site_name", "facility_type", "product_label"],
          [M("SUM(target)", "Target"), M("SUM(vaccinated)", "Children vaccinated"), COVERAGE,
           M("SUM(target) - SUM(vaccinated)", "Remaining to target")],
          formats={"Coverage of target": {"d3NumberFormat": ".1%"}},
          cond=[{"colorScheme": "#ACE1C4", "column": "Coverage of target", "operator": "≥", "targetValue": 0.9},
                {"colorScheme": "#FDE380", "column": "Coverage of target", "operator": "<", "targetValue": 0.9},
                {"colorScheme": "#EFA1AA", "column": "Coverage of target", "operator": "<", "targetValue": 0.5}],
          order=M("SUM(target)", "Target"), height=70, filters=[TIME_F()])

    # ---------------- Inventory
    T = "Inventory"
    big(T, 1, 3, "Inventory: stores and sites with a stock entry", "field_site_day",
        M("COUNT(DISTINCT CASE WHEN vials_received IS NOT NULL THEN site_code END)", "Sites"),
        "Stores and sites with at least one stock entry", ",d")
    for v, f in VACCINES:
        big(T, 1, 3, f"Inventory: {v} vials in hand, district store", "field_stock_days", M("SUM(vials_in_hand)", "Vials"),
            f"{v} vials in hand — district store", ",d", f, note="returned unopened on the latest day")
    big(T, 1, 3, "Inventory: campaign day", "field_campaign_day", M("MAX(campaign_day)", "Day"),
        f"Campaign day (of {CAMPAIGN_DAYS})", ",d")
    for v, f in VACCINES:
        r = f"2{v}"
        big(T, r, 2, f"Inventory: {v} vials received", "field_site_day", M("SUM(vials_received)", "Vials"),
            f"{v}: vials received", ",d", f + [TIME_F()])
        big(T, r, 2, f"Inventory: {v} additional vials received", "field_site_day", M("SUM(additional_vials_received)", "Vials"),
            f"{v}: additional vials received", ",d", f + [TIME_F()])
        big(T, r, 2, f"Inventory: {v} vials opened", "field_site_day", M("SUM(vials_opened)", "Vials"),
            f"{v}: vials opened", ",d", f + [TIME_F()])
        big(T, r, 2, f"Inventory: {v} vials returned unopened", "field_site_day", M("SUM(vials_returned_unopened)", "Vials"),
            f"{v}: vials returned unopened", ",d", f + [TIME_F()])
        big(T, r, 2, f"Inventory: {v} vials issued (net)", "field_site_day", M("SUM(vials_issued_net)", "Vials"),
            f"{v}: vials issued (net)", ",d", f + [TIME_F()])
        big(T, r, 2, f"Inventory: {v} wastage", "field_site_day", WASTAGE, f"{v}: wastage % (allowed 5%)", ".1%",
            f + [TIME_F()], note="reported figure" if v == "MR" else "")
    for v, f in VACCINES:
        handlebars(T, 3, 6, f"Inventory: {v} days of stock left", "field_stock_days",
                   [M("ROUND(SUM(vials_in_hand) / NULLIF(SUM(daily_vials_opened), 0), 1)", "dos"),
                    M("MAX(campaign_day)", "day"), M("MAX(campaign_days_total)", "total")],
                   '{{#each data}}<h2>' + v + ': {{#if dos}}{{dos}}{{else}}0{{/if}} days of stock · '
                   'Day {{day}} of {{total}}</h2><p>Vials in hand in the district store ÷ average daily vials '
                   'opened (last 3 days). The red line on the chart below marks the campaign days remaining.</p>'
                   '{{/each}}', f)
    bar(T, 4, 6, "Inventory: days of stock left by site", "field_stock_days", "site_name",
        [M("SUM(vials_in_hand) / NULLIF(SUM(daily_vials_opened), 0)", "Days of stock")], ["product_label"], fmt=",.1f",
        sort_by_metric=False, x_axis_sort="Days of stock", x_axis_sort_asc=True,
        lines=[LINE_AT(days_remaining, f"Campaign days remaining ({days_remaining})")], values=False)
    bar(T, 4, 6, "Inventory: wastage % by district (allowed 5%)", "field_site_day", "district", [WASTAGE],
        ["product_label"], fmt=".1%", filters=[TIME_F()], lines=[LINE_AT(0.05, "Allowed 5%")])
    bar(T, 5, 12, "Inventory: wastage % by site (allowed 5%)", "field_site_day", "site_name", [WASTAGE],
        ["product_label"], fmt=".1%", filters=[TIME_F()], lines=[LINE_AT(0.05, "Allowed 5%")], height=50, values=False)
    for v, f in VACCINES:
        bar(T, 6, 6, f"Inventory: {v} cumulative vials issued (net) vs vials needed, by site", "field_site_day", "site_name",
            [M("SUM(vials_issued_net)", "Vials issued (net)"), M("ROUND(SUM(vials_needed), 1)", "Vials needed")],
            filters=f + [TIME_F()], sort_by_metric=True, values=False)
    table(T, 7, 12, "Inventory: cumulative stock by facility (red = not enough vials for target)", "field_site_day",
          ["district", "site_name", "product_label"],
          [M("SUM(vials_issued_net)", "Vials issued (net)"), M("ROUND(SUM(vials_needed), 1)", "Vials needed"),
           M("ROUND(SUM(vials_issued_net) - SUM(vials_needed), 1)", "Vials short (-) or spare (+)"), M("SUM(target)", "Target")],
          order=M("ROUND(SUM(vials_issued_net) - SUM(vials_needed), 1)", "Vials short (-) or spare (+)"), desc=False,
          cond=[{"colorScheme": "#EFA1AA", "column": "Vials short (-) or spare (+)", "operator": "<", "targetValue": 0}],
          filters=[TIME_F()], height=60)
    chart(T, 8, 12, 72, "Inventory: stock flow in vials - national > regional > district store > site > opened / returned",
          "field_stock_flow", "sankey_v2", source="source", target="target", metric=M("SUM(vials)", "Vials"),
          adhoc_filters=[TIME_F()], row_limit=10000, color_scheme="supersetColors")
    for v in ("MR", "IPV"):
        point_map(T, f"9{v}", 9, f"Inventory map: sites by cumulative stock against need ({v})", "field_sites",
                  f"{v.lower()}_stock_status", STATUS_COLOURS,
                  ("Site", f"{v} status", f"{v} vials received (incl. additional)", f"{v} vials left over (returned unopened)",
                   f"{v} vials used (issued net)", f"{v} vials needed for target", f"{v} vials short (-) or spare (+)"),
                  legend_title=f"{v}: vials issued (net) vs needed",
                  note="Vials needed = target ÷ doses per vial × 1.05, summed over all campaign days with data.")
    table(T, 10, 12, "Inventory: stock by site and campaign day", "field_site_day",
          ["event_date", "district", "site_name", "product_label"],
          [M("SUM(vials_received)", "Vials received"), M("SUM(additional_vials_received)", "Additional vials received"),
           M("SUM(vials_opened)", "Vials opened"), M("SUM(vials_returned_unopened)", "Vials returned unopened"),
           M("SUM(vials_issued_net)", "Vials issued (net)"), M("SUM(vaccinated)", "Children vaccinated"), WASTAGE],
          formats={"Wastage": {"d3NumberFormat": ".1%"}, "event_date": {"d3TimeFormat": "%d %b"}},
          cond=[{"colorScheme": "#EFA1AA", "column": "Wastage", "operator": ">", "targetValue": 0.05}],
          order=M("SUM(vials_opened)", "Vials opened"), filters=[TIME_F()], height=70)

    # ---------------- Data quality
    T = "Data Quality"
    g = [F("user_group", "IN", ["Vaccinators downsynced"])]
    big(T, 0, 4, "DQ: vaccinators total", "field_sync", M("COUNT(*)", "Vaccinators"), "Vaccinators downsynced: total",
        ",d", g, note="synthetic until HCM is connected")
    big(T, 0, 4, "DQ: vaccinators downsynced", "field_sync", M("SUM(synced)", "Downsynced"),
        "Vaccinators downsynced at least once", ",d", g, note="synthetic until HCM is connected")
    big(T, 0, 4, "DQ: downsync rate", "field_sync", M("AVG(CAST(synced AS double))", "Rate"), "Downsync rate", ".1%", g,
        note="synthetic until HCM is connected")
    fl = [F("user_group", "IN", ["Frontline workers"])]
    big(T, 1, 4, "DQ: frontline workers total", "field_sync", M("COUNT(*)", "Workers"), "Frontline workers: total",
        ",d", fl, note="vaccinators and registrars - synthetic")
    big(T, 1, 4, "DQ: frontline workers synced", "field_sync", M("SUM(synced)", "Synced"),
        "Frontline workers synced at least once", ",d", fl, note="synthetic until HCM is connected")
    big(T, 1, 4, "DQ: frontline sync rate", "field_sync", M("AVG(CAST(synced AS double))", "Rate"), "Frontline sync rate",
        ".1%", fl, note="synthetic until HCM is connected")
    bar(T, "4b", 6, "DQ: frontline sync rate by district (synthetic)", "field_sync", "district",
        [M("AVG(CAST(synced AS double))", "Sync rate")], fmt=".0%", filters=[F("user_group", "IN", ["Frontline workers"])],
        sort_by_metric=True, x_axis_sort_asc=True, y_max=1)
    bar(T, "4b", 6, "DQ: downsync rate by district (synthetic)", "field_sync", "district",
        [M("AVG(CAST(synced AS double))", "Downsync rate")], fmt=".0%",
        filters=[F("user_group", "IN", ["Vaccinators downsynced"])], x_axis_sort_asc=True, y_max=1)
    markdown(T, 5, 12, 14, BANNER.format(text=(
        "Sync figures are synthetic: the field database has no app sync records, so each frontline user in the "
        "microplan (vaccinators and registrars) gets a stable synthetic status until HCM is connected. Shown only "
        "for districts that uploaded field data.")))


TABS = ["Overview", "Coverage", "Inventory", "Data Quality"]
# Supervision and Complaints are hidden for this release (review 16 Nov 2026); the
# earlier synthetic build of those tabs is in tools/legacy/.


def build_charts(ds_ids):
    by_name = {}
    for c in sorted((c for c in CHARTS if "markdown" not in c), key=lambda c: c["viz"] == "deck_multi"):
        params = dict(c["params"], viz_type=c["viz"], datasource=f"{ds_ids[c['ds']]}__table")
        params.setdefault("adhoc_filters", [])
        if "deck_slice_names" in params:
            params["deck_slices"] = [by_name[n] for n in params.pop("deck_slice_names")]
        res = api("POST", "/api/v1/chart/", json={
            "slice_name": CHART_PREFIX + c["name"], "viz_type": c["viz"], "datasource_id": ds_ids[c["ds"]],
            "datasource_type": "table", "params": json.dumps(params), "cache_timeout": 60})
        c["id"] = res["id"]
        by_name[c["name"]] = res["id"]
    print(f"  {sum(1 for c in CHARTS if 'id' in c and c['tab'])} charts on the dashboard "
          f"(+ {sum(1 for c in CHARTS if 'id' in c and not c['tab'])} map layers)")


def position():
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["TABS-main"]},
           "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER", "meta": {"text": DASH_TITLE}},
           "TABS-main": {"type": "TABS", "id": "TABS-main", "children": [], "parents": ["ROOT_ID"]}}
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
                                     "sliceNameOverride": c.get("title") or c["name"]}}
                rows[rid]["children"].append(cid)
        pos.update(rows)
    return pos


def native_filters(ds_ids, ds_cols):
    charts = [c for c in CHARTS if "id" in c and c["tab"]]

    def scope(pred):
        inscope = [c["id"] for c in charts if pred(c)]
        return {"rootPath": ["ROOT_ID"], "excluded": [c["id"] for c in charts if c["id"] not in inscope]}, inscope

    def has(col):
        return lambda c: col in ds_cols[c["ds"]]

    def select(fid, name, col, parents=(), desc="", ds="field_site_day"):
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
        select("NATIVE_FILTER-region", "Region", "region"),
        select("NATIVE_FILTER-district", "District", "district", ["NATIVE_FILTER-region"]),
        select("NATIVE_FILTER-site", "Site", "site_name", ["NATIVE_FILTER-district"]),
        select("NATIVE_FILTER-product", "Vaccine", "product",
               desc="MR + IPV when empty; pick MR or IPV to show one vaccine"),
        {"id": "NATIVE_FILTER-date", "name": "Campaign date", "filterType": "filter_time", "type": "NATIVE_FILTER",
         "targets": [{}], "controlValues": {"enableEmptyFilter": True},
         "description": f"Preselected to the dates with field data ({DATE_RANGE[0]:%d %b} - {DATE_RANGE[1]:%d %b %Y}). "
                        "Applies to daily charts and totals; maps are cumulative.",
         "defaultDataMask": {"extraFormData": {"time_range": DATE_RANGE[2]}, "filterState": {"value": DATE_RANGE[2]},
                             "ownState": {}}, "cascadeParentIds": [],
         "scope": tsc, "chartsInScope": tins, "tabsInScope": []},
    ]


CSS = """
.dashboard-header .header-title, .editable-title input { font-weight: 700; }
.dashboard-component-tabs .ant-tabs-tab-active .ant-tabs-tab-btn { color: #F47738 !important; font-weight: 600; }
.dashboard-component-tabs .ant-tabs-ink-bar { background: #F47738 !important; height: 3px !important; }
"""


def build_dashboard(ds_ids, ds_cols):
    pos = position()
    on_dash = [c["id"] for c in CHARTS if "id" in c and c["tab"]]
    meta = {"native_filter_configuration": native_filters(ds_ids, ds_cols), "cross_filters_enabled": True,
            "refresh_frequency": 300, "color_scheme": "supersetColors",
            "label_colors": {"MR": "#F47738", "IPV": "#2A78D6", "Vaccinated": "#0CA30C",
                             "Remaining to target": "#C9CED6", "Not recorded": "#9AA3AD",
                             "Male": "#2A78D6", "Female": "#E87BA4"},
            "shared_label_colors": [], "timed_refresh_immune_slices": [], "expanded_slices": {},
            "chart_configuration": {}, "global_chart_configuration": {"scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                                                                       "chartsInScope": on_dash}}
    res = api("POST", "/api/v1/dashboard/", json={
        "dashboard_title": DASH_TITLE, "slug": SLUG, "published": True, "css": CSS,
        "position_json": json.dumps(pos), "json_metadata": json.dumps(meta)})
    did = res["id"]
    for cid in on_dash:
        api("PUT", f"/api/v1/chart/{cid}", json={"dashboards": [did]})
    return did


def main():
    login()
    print("teardown"); teardown()
    db = ensure_db(); print("database", db)
    ds_ids, ds_cols = create_datasets(db)
    global DATE_RANGE
    DATE_RANGE = data_date_range()
    day, remaining = campaign_days_remaining()
    print(f"latest campaign day {day}, {remaining} days remaining")
    define(remaining)
    build_charts(ds_ids)
    did = build_dashboard(ds_ids, ds_cols)
    print(f"dashboard {did}: {BASE}/superset/dashboard/{SLUG}/")


if __name__ == "__main__":
    main()

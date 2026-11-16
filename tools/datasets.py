"""Superset virtual datasets on the field database (single source of truth).

Facts live in Elasticsearch (tools/load_field_data.py): field-site-day-v1 (one doc per
site x date x vaccine) and field-child-v1 (one doc per child). Dimensions live in the
`microplan` Postgres catalog (dim_site, dim_district, dim_product, ...). Trino joins them.

Every dataset exposes region, district, cluster and site_name where they apply (the
native filters are scoped by those column names) plus product and event_date.
Keep SQL comments out of the SQL strings: Superset wraps them in a subquery.

    tools/.venv/bin/python -I tools/datasets.py      # writes sql/datasets/*.sql for review
"""
from pathlib import Path

SITE_DAY = 'hcm.default."field-site-day-v1"'
CHILD = 'hcm.default."field-child-v1"'
SYNC = 'hcm.default."field-user-sync-v1"'
MP = "microplan.public"
CAMPAIGN_START = "DATE '2026-11-09'"
CAMPAIGN_DAYS = 11
WASTAGE_ALLOWED = 0.05

DIMS = "s.region, s.district, s.boundary_code, s.cluster, s.site_code, s.site_name, s.facility_type"


def site_day_base():
    return f"""
SELECT {DIMS}, s.latitude, s.longitude,
       f.vaccine AS product, f.vaccine AS product_label,
       CAST(f.event_date AS date) AS event_date, f.campaign_day, f.source_campaign_day,
       CAST(f.target AS double) AS target,
       CAST(f.total_vaccinated AS double) AS vaccinated,
       CAST(f.vials_received AS double) AS vials_received,
       CAST(f.additional_vials_received AS double) AS additional_vials_received,
       CAST(f.vials_opened AS double) AS vials_opened,
       CAST(f.vials_returned_unopened AS double) AS vials_returned_unopened,
       CAST(coalesce(f.vials_received, 0) + coalesce(f.additional_vials_received, 0) - coalesce(f.vials_returned_unopened, 0) AS double) AS vials_issued_net,
       CAST(p.doses_per_unit AS double) AS doses_per_vial,
       CAST(f.vials_opened * p.doses_per_unit AS double) AS doses_opened,
       f.target / CAST(p.doses_per_unit AS double) * (1 + p.planned_wastage_pct / 100.0) AS vials_needed,
       CAST(coalesce(f.vials_received, 0) + coalesce(f.additional_vials_received, 0) - coalesce(f.vials_opened, 0) - coalesce(f.vials_returned_unopened, 0) AS double) AS stock_unbalanced_vials,
       f.vaccinated_6_11m, f.vaccinated_14w_11m, f.vaccinated_12_59m, f.vaccinated_5_10y
FROM {SITE_DAY} f
JOIN {MP}.dim_site s ON s.site_code = f.site_code
JOIN {MP}.dim_product p ON p.product_code = f.vaccine"""


def ds_site_day():
    """One row per site x campaign date x vaccine: target, children vaccinated, vials (field database)."""
    return site_day_base()


def ds_progress_pie():
    """Vaccinated vs remaining to target, one row per site-day x vaccine x slice (Overview pie)."""
    return f"""
SELECT b.region, b.district, b.cluster, b.site_name, b.product, b.event_date, t.slice, t.slice_order, t.children
FROM ({site_day_base()}) b
CROSS JOIN UNNEST(ARRAY['Vaccinated', 'Remaining to target'], ARRAY[1, 2],
                  ARRAY[b.vaccinated, b.target - b.vaccinated]) AS t(slice, slice_order, children)"""


def ds_age():
    """Children vaccinated by age group; labels exactly as in the field database (differ by vaccine)."""
    return f"""
SELECT b.region, b.district, b.cluster, b.site_name, b.product, b.product_label, b.event_date,
       t.age_group, t.age_order, t.vaccinated
FROM ({site_day_base()}) b
CROSS JOIN UNNEST(ARRAY['6-11 months', '14 weeks-11 months', '12-59 months', '5-10 years'], ARRAY[1, 1, 2, 3],
                  ARRAY[b.vaccinated_6_11m, b.vaccinated_14w_11m, b.vaccinated_12_59m, b.vaccinated_5_10y])
  AS t(age_group, age_order, vaccinated)
WHERE t.vaccinated IS NOT NULL"""


def ds_children():
    """Child line list: one row per child x vaccine received. Gender is synthetic until the source records it."""
    return f"""
SELECT {DIMS}, v.product, v.product AS product_label, CAST(c.event_date AS date) AS event_date,
       c.age_group, CASE c.gender WHEN 'MALE' THEN 'Male' WHEN 'FEMALE' THEN 'Female' ELSE 'Not recorded' END AS gender,
       c.gender_synthetic, c.vaccine_status, 1 AS children
FROM {CHILD} c
JOIN {MP}.dim_site s ON s.site_code = c.site_code
CROSS JOIN UNNEST(ARRAY['MR', 'IPV'], ARRAY[c.mr, c.ipv]) AS v(product, received)
WHERE v.received = 1"""


def ds_child_status():
    """One row per child: which vaccines the child received (co-administration)."""
    return f"""
SELECT {DIMS}, CAST(c.event_date AS date) AS event_date, c.age_group, c.vaccine_status, 1 AS children
FROM {CHILD} c
JOIN {MP}.dim_site s ON s.site_code = c.site_code"""


def cov_by(key):
    return f"""
SELECT {key}, sum(CASE WHEN product = 'MR' THEN vaccinated END) / nullif(sum(CASE WHEN product = 'MR' THEN target END), 0) * 100 AS mr_coverage_pct,
       sum(CASE WHEN product = 'IPV' THEN vaccinated END) / nullif(sum(CASE WHEN product = 'IPV' THEN target END), 0) * 100 AS ipv_coverage_pct
FROM ({site_day_base()}) b GROUP BY {key}"""


def ds_region_map():
    """Region polygons (all of Namibia) with MR / IPV coverage for regions that uploaded data (NULL otherwise)."""
    return f"""
SELECT r.region, r.part_no, r.polygon, c.mr_coverage_pct, c.ipv_coverage_pct,
       CASE WHEN c.region IS NULL THEN 'No data uploaded' ELSE 'Uploading' END AS upload_status
FROM {MP}.dim_region_polygon r
LEFT JOIN ({cov_by('region')}) c ON c.region = r.region"""


def ds_district_map():
    """District polygons (approximate) with MR / IPV coverage for districts that uploaded data."""
    return f"""
SELECT d.region, d.district, d.boundary_code, d.part_no, d.polygon, c.mr_coverage_pct, c.ipv_coverage_pct
FROM {MP}.dim_district_polygon d
LEFT JOIN ({cov_by('boundary_code')}) c ON c.boundary_code = d.boundary_code"""


def ds_sites():
    """Vaccination sites with coordinates, facility type, coverage and cumulative stock against need per vaccine."""
    return f"""
WITH n AS (SELECT site_code,
       sum(CASE WHEN product = 'MR' THEN vials_issued_net END) - sum(CASE WHEN product = 'MR' THEN vials_needed END) AS mr_gap,
       sum(CASE WHEN product = 'IPV' THEN vials_issued_net END) - sum(CASE WHEN product = 'IPV' THEN vials_needed END) AS ipv_gap
       FROM ({site_day_base()}) b GROUP BY 1)
SELECT {DIMS}, s.latitude, s.longitude, s.coord_source, s.team_note,
       round(c.mr_coverage_pct, 1) AS mr_coverage_pct, round(c.ipv_coverage_pct, 1) AS ipv_coverage_pct,
       CASE WHEN n.mr_gap IS NULL THEN 'No stock data' WHEN n.mr_gap < 0 THEN 'Below vials needed' ELSE 'Enough vials issued' END AS mr_stock_status,
       CASE WHEN n.ipv_gap IS NULL THEN 'No stock data' WHEN n.ipv_gap < 0 THEN 'Below vials needed' ELSE 'Enough vials issued' END AS ipv_stock_status
FROM {MP}.dim_site s
LEFT JOIN ({cov_by('site_code')}) c ON c.site_code = s.site_code
LEFT JOIN n ON n.site_code = s.site_code"""


def ds_stock_flow():
    """Sankey links, in vials: National > Regional > District store > site > opened / returned unopened.
    Store layers are not in the field database: they are the sums of the site layer."""
    return f"""
SELECT b.region, b.district, b.cluster, b.site_name, b.product, b.event_date, l.source, l.target, l.vials
FROM ({site_day_base()}) b
CROSS JOIN UNNEST(
  ARRAY[b.product || ' · National store', b.product || ' · ' || b.region || ' regional store',
        b.product || ' · ' || b.district || ' district store',
        b.product || ' · ' || b.site_name, b.product || ' · ' || b.site_name, b.product || ' · ' || b.site_name],
  ARRAY[b.product || ' · ' || b.region || ' regional store', b.product || ' · ' || b.district || ' district store',
        b.product || ' · ' || b.site_name, b.product || ' · Vials opened', b.product || ' · Vials returned unopened',
        b.product || ' · Not accounted for'],
  ARRAY[b.vials_received + b.additional_vials_received, b.vials_received + b.additional_vials_received,
        b.vials_received + b.additional_vials_received, b.vials_opened, b.vials_returned_unopened,
        greatest(b.stock_unbalanced_vials, 0)]) AS l(source, target, vials)
WHERE l.vials > 0"""


def ds_stock_days():
    """Per site and vaccine: vials returned unopened on the latest day (now in the district store) and
    average daily vials opened over the last 3 campaign days with data. Days of stock = in hand / daily use."""
    return f"""
WITH b AS ({site_day_base()}),
 g AS (SELECT max(event_date) AS last_date FROM b),
 w AS (SELECT count(DISTINCT event_date) AS n FROM b, g WHERE b.event_date > date_add('day', -3, g.last_date))
SELECT b.region, b.district, b.cluster, b.site_name, b.product, b.product_label,
       sum(CASE WHEN b.event_date = g.last_date THEN b.vials_returned_unopened ELSE 0 END) AS vials_in_hand,
       sum(CASE WHEN b.event_date > date_add('day', -3, g.last_date) THEN b.vials_opened ELSE 0 END) / CAST(max(w.n) AS double) AS daily_vials_opened,
       date_diff('day', {CAMPAIGN_START}, max(g.last_date)) + 1 AS campaign_day,
       {CAMPAIGN_DAYS} AS campaign_days_total,
       {CAMPAIGN_DAYS} - (date_diff('day', {CAMPAIGN_START}, max(g.last_date)) + 1) AS campaign_days_remaining
FROM b CROSS JOIN g CROSS JOIN w
GROUP BY 1, 2, 3, 4, 5, 6"""


def ds_campaign_day():
    """Latest campaign day with field data, and the campaign length (9-19 Nov 2026 = 11 days)."""
    return f"""
SELECT date_diff('day', {CAMPAIGN_START}, max(CAST(event_date AS date))) + 1 AS campaign_day,
       {CAMPAIGN_DAYS} AS campaign_days_total, max(CAST(event_date AS date)) AS last_date
FROM {SITE_DAY}"""


def ds_dq():
    """Data-quality checks per site x date x vaccine: stock balance, line list vs aggregate, targets, vials, day labels."""
    return f"""
WITH b AS ({site_day_base()}),
 l AS (SELECT site_code, CAST(event_date AS date) AS event_date, sum(mr) AS mr, sum(ipv) AS ipv FROM {CHILD} GROUP BY 1, 2),
 cs AS (SELECT site_code, CAST(event_date AS date) AS event_date, max(source_campaign_day) AS child_day FROM {CHILD} GROUP BY 1, 2)
SELECT b.region, b.district, b.cluster, b.site_code, b.site_name, b.facility_type, b.latitude, b.longitude,
       b.product, b.product_label, b.event_date, b.campaign_day, b.source_campaign_day,
       b.vaccinated, b.target, b.doses_opened, b.stock_unbalanced_vials,
       CAST(coalesce(CASE b.product WHEN 'MR' THEN l.mr ELSE l.ipv END, 0) AS double) AS children_listed,
       CASE WHEN b.stock_unbalanced_vials <> 0 THEN 1 ELSE 0 END AS stock_unbalanced,
       CASE WHEN b.vials_received IS NULL THEN 1 ELSE 0 END AS stock_missing,
       CASE WHEN coalesce(CASE b.product WHEN 'MR' THEN l.mr ELSE l.ipv END, 0) <> b.vaccinated THEN 1 ELSE 0 END AS list_vs_aggregate_mismatch,
       CASE WHEN b.vaccinated > b.target THEN 1 ELSE 0 END AS above_target,
       CASE WHEN b.vaccinated > b.doses_opened THEN 1 ELSE 0 END AS more_children_than_doses,
       CASE WHEN b.source_campaign_day <> b.campaign_day OR cs.child_day <> b.campaign_day THEN 1 ELSE 0 END AS day_label_mismatch,
       CASE WHEN s.coord_source LIKE 'Approximate%' THEN 1 ELSE 0 END AS approximate_location,
       CASE WHEN b.stock_unbalanced_vials <> 0 THEN 'Stock not balanced'
            WHEN b.vaccinated > b.doses_opened THEN 'More children than doses'
            WHEN coalesce(CASE b.product WHEN 'MR' THEN l.mr ELSE l.ipv END, 0) <> b.vaccinated THEN 'Line list differs'
            ELSE 'No issue' END AS dq_status
FROM b
JOIN {MP}.dim_site s ON s.site_code = b.site_code
LEFT JOIN l ON l.site_code = b.site_code AND l.event_date = b.event_date
LEFT JOIN cs ON cs.site_code = b.site_code AND cs.event_date = b.event_date"""


def ds_reporting():
    """Reporting completeness: every site x vaccine x campaign date from the first to the latest date with data."""
    return f"""
WITH b AS ({site_day_base()}),
 d AS (SELECT DISTINCT event_date FROM b),
 v AS (SELECT DISTINCT product FROM b)
SELECT s.region, s.district, s.cluster, s.site_code, s.site_name, s.facility_type, v.product, d.event_date,
       CASE WHEN b.site_code IS NULL THEN 0 ELSE 1 END AS reported, 1 AS expected
FROM {MP}.dim_site s CROSS JOIN d CROSS JOIN v
LEFT JOIN b ON b.site_code = s.site_code AND b.event_date = d.event_date AND b.product = v.product"""


def ds_sync():
    """App sync per frontline user (SYNTHETIC until HCM is connected), for districts that uploaded field data:
    'Frontline workers' = vaccinators and registrars who synced at least once; 'Vaccinators downsynced'."""
    return f"""
SELECT u.region, u.district, 'Frontline workers' AS user_group, u.user_id AS entity_id, y.synced, y.synthetic
FROM {SYNC} y JOIN {MP}.dim_user u ON u.user_id = y.user_id
WHERE u.district IN (SELECT DISTINCT district FROM {MP}.dim_site)
UNION ALL
SELECT u.region, u.district, 'Vaccinators downsynced', u.user_id, y.downsynced, y.synthetic
FROM {SYNC} y JOIN {MP}.dim_user u ON u.user_id = y.user_id
WHERE y.role_group = 'VACCINATOR' AND u.district IN (SELECT DISTINCT district FROM {MP}.dim_site)"""


DATASETS = {
    # name: (function, temporal column or None)
    "field_site_day": (ds_site_day, "event_date"),
    "field_progress_pie": (ds_progress_pie, "event_date"),
    "field_age": (ds_age, "event_date"),
    "field_children": (ds_children, "event_date"),
    "field_child_status": (ds_child_status, "event_date"),
    "field_region_map": (ds_region_map, None),
    "field_district_map": (ds_district_map, None),
    "field_sites": (ds_sites, None),
    "field_stock_flow": (ds_stock_flow, "event_date"),
    "field_stock_days": (ds_stock_days, None),
    "field_campaign_day": (ds_campaign_day, None),
    "field_dq": (ds_dq, "event_date"),
    "field_reporting": (ds_reporting, "event_date"),
    "field_sync": (ds_sync, None),
}

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "sql/datasets"
    out.mkdir(parents=True, exist_ok=True)
    for name, (fn, _) in DATASETS.items():
        (out / f"{name}.sql").write_text(fn().strip() + "\n")
    print(f"wrote {len(DATASETS)} files to {out}")

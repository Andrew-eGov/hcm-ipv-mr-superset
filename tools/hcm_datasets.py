"""Superset virtual datasets (Trino SQL) for the HCM IPV+MR dashboard.

Design
- Aggregations are pushed down to Elasticsearch through Trino's
  `raw_query` table function (ES composite / terms / cardinality aggs),
  so every chart is live against ES and answers in well under a second.
  Plain Trino scans of the HCM indexes are avoided (17s+ per 600k docs).
- Results are joined in Trino with microplan reference tables in Postgres
  (targets, users, facilities, district shapes).
- Every dataset exposes the same filter columns where they apply:
  region, district, boundary_code, product, delivery_mode, event_date.

If the real HCM ES index or field names differ, edit IDX / F below only.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IDX = {
    "task": "project-task-index-v1",
    "individual": "individual-index-v1",
    "household": "household-index-v1",
    "stock": "stock-index-v1",
    "checklist": "service-task-v1",
    "complaint": "pgr-services-index-v1",
    "downsync": "downsync-index-v1",
}
CAMPAIGN_START = "2026-11-09"
CAMPAIGN_DAYS = 11
MP = "microplan.public"


def F(name):
    return f"Data.{name}"


def raw(index, body):
    s = json.dumps(body, separators=(",", ":"))
    assert "'" not in s
    return f"TABLE(hcm.system.raw_query('default', '{index}', '{s}'))"


def composite(index, sources, aggs=None, query=None):
    """CTE body yielding one json row `x` per composite bucket."""
    srcs = []
    for name, spec in sources:
        srcs.append({name: spec})
    body = {"size": 0, "aggs": {"c": {"composite": {"size": 65000, "sources": srcs}}}}
    if aggs:
        body["aggs"]["c"]["aggs"] = aggs
    if query:
        body["query"] = query
    return (f"SELECT x FROM {raw(index, body)} "
            f"CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x)")


def terms(field, missing=False):
    spec = {"terms": {"field": F(field)}}
    if missing:
        spec["terms"]["missing_bucket"] = True
    return spec


DAY = {"date_histogram": {"field": F("eventTime"), "calendar_interval": "day", "format": "yyyy-MM-dd"}}
SUCCESS = {"term": {F("administrationStatus"): "ADMINISTRATION_SUCCESS"}}


def k(key, typ=None):
    e = f"json_extract_scalar(x, '$.key.{key}')"
    return f"CAST({e} AS {typ})" if typ else e


def v(path, typ="double"):
    return f"CAST(json_extract_scalar(x, '$.{path}') AS {typ})"


PRODUCT_LABEL = "CASE {c} WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE {c} END"
MODE_LABEL = ("CASE {c} WHEN 'FIXED_POST' THEN 'Fixed post' WHEN 'HOUSE_TO_HOUSE' THEN 'House to house' "
              "WHEN 'TRANSIT_POST' THEN 'Transit post' ELSE {c} END")
DAYS_ELAPSED = (f"(SELECT greatest(1, least({CAMPAIGN_DAYS}, date_diff('day', DATE '{CAMPAIGN_START}', "
                f"CAST(substr(json_extract_scalar(result, '$.aggregations.m.value_as_string'), 1, 10) AS date)) + 1)) "
                f"FROM {raw(IDX['task'], {'size': 0, 'aggs': {'m': {'max': {'field': F('eventTime')}}}})})")


# ------------------------------------------------------------------ datasets
def ds_delivery_daily():
    return f"""
WITH b AS ({composite(IDX['task'], [("day", DAY), ("code", terms("boundaryHierarchyCode.district")),
                                     ("product", terms("productCode")), ("status", terms("administrationStatus")),
                                     ("reason", terms("reasonNotAdministered", True)), ("mode", terms("deliveryMode"))],
                      {"doses": {"sum": {"field": F("quantity")}}})})
SELECT CAST({k('day')} AS date) AS event_date, d.region, d.district, d.boundary_code,
       {k('product')} AS product, {PRODUCT_LABEL.format(c=k('product'))} AS product_label,
       {k('status')} AS status, coalesce({k('reason')}, 'ADMINISTERED') AS reason,
       {MODE_LABEL.format(c=k('mode'))} AS delivery_mode,
       {v('doc_count', 'bigint')} AS records, {v('doses.value')} AS doses
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def coverage_cte():
    return f"""cov AS (
  SELECT {k('code')} AS boundary_code, {k('product')} AS product,
         {v('doses.value')} AS doses, {v('doc_count', 'bigint')} AS attempts
  FROM ({composite(IDX['task'], [("code", terms("boundaryHierarchyCode.district")), ("product", terms("productCode"))],
                   {"doses": {"sum": {"field": F("quantity")}}})})
)"""


def ds_coverage():
    return f"""
WITH {coverage_cte()},
de AS (SELECT {DAYS_ELAPSED} AS days_elapsed)
SELECT d.region, d.district, d.boundary_code, p.product,
       {PRODUCT_LABEL.format(c='p.product')} AS product_label,
       coalesce(c.doses, 0) AS doses, coalesce(c.attempts, 0) AS attempts,
       CASE p.product WHEN 'MR' THEN d.mr_target ELSE d.ipv_target END AS target,
       CASE p.product WHEN 'MR' THEN d.mr_target ELSE d.ipv_target END * de.days_elapsed / {CAMPAIGN_DAYS} AS planned_to_date,
       de.days_elapsed, d.u5_population, d.teams_total, d.centroid_lat, d.centroid_lon
FROM {MP}.dim_district d
CROSS JOIN (VALUES 'MR', 'IPV') AS p(product)
CROSS JOIN de
LEFT JOIN cov c ON c.boundary_code = d.boundary_code AND c.product = p.product
"""


def ds_coadmin():
    q = {"bool": {"filter": [SUCCESS, {"range": {F("ageInMonths"): {"gte": 9, "lte": 59}}}]}}
    return f"""
WITH b AS ({composite(IDX['task'], [("code", terms("boundaryHierarchyCode.district"))],
                      {"children": {"cardinality": {"field": F("individualId"), "precision_threshold": 40000}},
                       "mr": {"filter": {"term": {F("productCode"): "MR"}}},
                       "ipv": {"filter": {"term": {F("productCode"): "IPV"}}}}, q)})
SELECT d.region, d.district, d.boundary_code,
       {v('children.value', 'bigint')} AS children_9_59,
       {v('mr.doc_count', 'bigint')} AS mr_9_59, {v('ipv.doc_count', 'bigint')} AS ipv_9_59,
       greatest(0, least({v('mr.doc_count', 'bigint')}, {v('ipv.doc_count', 'bigint')},
                {v('mr.doc_count', 'bigint')} + {v('ipv.doc_count', 'bigint')} - {v('children.value', 'bigint')})) AS both_9_59,
       d.ipv_target * 51.0 / 56 AS target_9_59
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def ds_age():
    return f"""
WITH b AS ({composite(IDX['task'], [("code", terms("boundaryHierarchyCode.district")), ("product", terms("productCode")),
                                     ("age", {"histogram": {"field": F("ageInMonths"), "interval": 1}}),
                                     ("gender", terms("gender", True))], None, SUCCESS)})
SELECT d.region, d.district, d.boundary_code, {k('product')} AS product,
       {PRODUCT_LABEL.format(c=k('product'))} AS product_label,
       {k('age', 'double')} AS age_months,
       CASE WHEN {k('age', 'double')} < 9 THEN '1. 4-8 months (fIPV only)'
            WHEN {k('age', 'double')} < 60 THEN '2. 9-59 months (MR + fIPV)'
            ELSE '3. 5-9 years (MR only)' END AS age_group,
       CAST(floor({k('age', 'double')} / 12) AS integer) AS age_years,
       coalesce({k('gender')}, 'NOT RECORDED') AS gender, {v('doc_count', 'bigint')} AS doses
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def ds_registration_daily():
    return f"""
WITH b AS ({composite(IDX['individual'], [("day", DAY), ("code", terms("boundaryHierarchyCode.district")),
                                           ("mode", terms("deliveryMode")), ("gender", terms("gender", True)),
                                           ("mr", terms("eligibleMR")), ("ipv", terms("eligibleIPV"))])})
SELECT CAST({k('day')} AS date) AS event_date, d.region, d.district, d.boundary_code,
       {MODE_LABEL.format(c=k('mode'))} AS delivery_mode, coalesce({k('gender')}, 'NOT RECORDED') AS gender,
       {k('mr')} = 'true' AS eligible_mr, {k('ipv')} = 'true' AS eligible_ipv,
       {v('doc_count', 'bigint')} AS registrations
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def ds_household_daily():
    return f"""
WITH b AS ({composite(IDX['household'], [("day", DAY), ("code", terms("boundaryHierarchyCode.district")),
                                          ("outcome", terms("visitOutcome"))],
                      {"members": {"sum": {"field": F("memberCount")}}})})
SELECT CAST({k('day')} AS date) AS event_date, d.region, d.district, d.boundary_code,
       'House to house' AS delivery_mode, {k('outcome')} AS visit_outcome,
       {v('doc_count', 'bigint')} AS households, {v('members.value')} AS members
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def user_terms(index):
    body = {"size": 0, "aggs": {"u": {"terms": {"field": F("createdBy"), "size": 20000}}}}
    return (f"SELECT json_extract_scalar(x, '$.key') AS user_id FROM {raw(index, body)} "
            f"CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x)")


def ds_sync():
    frontline = ",".join([IDX["task"], IDX["individual"], IDX["household"]])
    stores = {"size": 0, "aggs": {"u": {"terms": {"field": F("facilityId"), "size": 5000}}}}
    return f"""
WITH fl AS ({user_terms(frontline)}),
sv AS ({user_terms(IDX['checklist'])}),
ds AS ({user_terms(IDX['downsync'])}),
st AS (SELECT json_extract_scalar(x, '$.key') AS facility_code FROM {raw(IDX['stock'], stores)}
       CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x))
SELECT u.region, u.district, 'Frontline workers' AS user_group, u.user_id AS entity_id,
       CASE WHEN fl.user_id IS NOT NULL THEN 1 ELSE 0 END AS synced
FROM {MP}.dim_user u LEFT JOIN fl ON fl.user_id = u.user_id WHERE u.role_group IN ('VACCINATOR', 'REGISTRAR')
UNION ALL
SELECT u.region, u.district, 'Supervisors', u.user_id, CASE WHEN sv.user_id IS NOT NULL THEN 1 ELSE 0 END
FROM {MP}.dim_user u LEFT JOIN sv ON sv.user_id = u.user_id
WHERE u.role_group IN ('TEAM_SUPERVISOR', 'DISTRICT_SUPERVISOR', 'PROVINCIAL_SUPERVISOR', 'NATIONAL_SUPERVISOR')
UNION ALL
SELECT u.region, u.district, 'Vaccinators downsynced', u.user_id, CASE WHEN ds.user_id IS NOT NULL THEN 1 ELSE 0 END
FROM {MP}.dim_user u LEFT JOIN ds ON ds.user_id = u.user_id WHERE u.role_group = 'VACCINATOR'
UNION ALL
SELECT f.region, f.district, 'Warehouses', f.facility_code, CASE WHEN st.facility_code IS NOT NULL THEN 1 ELSE 0 END
FROM {MP}.dim_facility f LEFT JOIN st ON st.facility_code = f.facility_code
"""


def stock_cte():
    return f"""tx AS (
  SELECT CAST({k('day')} AS date) AS event_date, {k('fac')} AS facility_code, {k('product')} AS product,
         {k('type')} AS tx_type, {k('sid')} AS sender_id, {k('sname')} AS sender_name, {k('stype')} AS sender_type,
         {k('rid')} AS receiver_id, {k('rname')} AS receiver_name, {k('rtype')} AS receiver_type,
         {v('qty.value')} AS quantity
  FROM ({composite(IDX['stock'], [("day", DAY), ("fac", terms("facilityId")), ("product", terms("productCode")),
                                   ("type", terms("transactionType")), ("sid", terms("senderId")),
                                   ("sname", terms("senderName")), ("stype", terms("senderType")),
                                   ("rid", terms("receiverId")), ("rname", terms("receiverName")),
                                   ("rtype", terms("receiverType"))],
                   {"qty": {"sum": {"field": F("quantity")}}})})
)"""


def ds_stock_tx():
    return f"""
WITH {stock_cte()}
SELECT tx.event_date, f.region, f.district, f.boundary_code, f.facility_code, f.facility_name,
       f.facility_type, tx.product, pr.product_name AS product_label, pr.unit, tx.tx_type,
       tx.sender_name, tx.sender_type, tx.receiver_name, tx.receiver_type,
       tx.quantity, tx.quantity * pr.doses_per_unit AS doses
FROM tx JOIN {MP}.dim_facility f ON f.facility_code = tx.facility_code
JOIN {MP}.dim_product pr ON pr.product_code = tx.product
"""


def ds_stock_position():
    return f"""
WITH {stock_cte()},
de AS (SELECT {DAYS_ELAPSED} AS days_elapsed),
pos AS (
  SELECT facility_code, product,
    sum(CASE WHEN tx_type = 'RECEIVED' THEN quantity ELSE 0 END) AS received,
    sum(CASE WHEN tx_type = 'DISPATCHED' THEN quantity ELSE 0 END) AS dispatched,
    sum(CASE WHEN tx_type = 'RETURNED' THEN quantity ELSE 0 END) AS returned,
    sum(CASE WHEN tx_type = 'LOSS' THEN quantity ELSE 0 END) AS lost,
    sum(CASE WHEN tx_type = 'DISPATCHED' AND receiver_type = 'TEAM' THEN quantity
             WHEN tx_type = 'RETURNED' AND sender_type = 'TEAM' THEN -quantity ELSE 0 END) AS net_to_teams,
    sum(CASE WHEN tx_type = 'DISPATCHED' AND receiver_type = 'TEAM'
              AND event_date >= (SELECT max(event_date) FROM tx) - INTERVAL '2' DAY THEN quantity
             WHEN tx_type = 'RETURNED' AND sender_type = 'TEAM'
              AND event_date >= (SELECT max(event_date) FROM tx) - INTERVAL '2' DAY THEN -quantity ELSE 0 END) / 3.0 AS daily_use
  FROM tx GROUP BY 1, 2
)
SELECT f.region, f.district, f.boundary_code, f.facility_code, f.facility_name, f.facility_type, f.level,
       f.latitude, f.longitude, f.capacity, p.product, pr.product_name AS product_label, pr.unit,
       p.received, p.dispatched, p.returned, p.lost, p.net_to_teams, p.daily_use,
       p.received + p.returned - p.dispatched - p.lost AS stock_in_hand,
       (p.received + p.returned - p.dispatched - p.lost) * pr.doses_per_unit AS stock_in_hand_doses,
       CASE WHEN p.daily_use > 0 THEN (p.received + p.returned - p.dispatched - p.lost) / p.daily_use END AS days_of_stock,
       greatest(0, {CAMPAIGN_DAYS} - de.days_elapsed) AS days_remaining,
       CASE WHEN f.level < 3 THEN 'Intermediate store'
            WHEN p.daily_use = 0 THEN 'No consumption'
            WHEN (p.received + p.returned - p.dispatched - p.lost) / p.daily_use < least(2, greatest(0, {CAMPAIGN_DAYS} - de.days_elapsed)) THEN 'Stock-out risk'
            WHEN (p.received + p.returned - p.dispatched - p.lost) / p.daily_use < greatest(0, {CAMPAIGN_DAYS} - de.days_elapsed) THEN 'Insufficient for remaining days'
            ELSE 'Sufficient' END AS stock_status
FROM pos p JOIN {MP}.dim_facility f ON f.facility_code = p.facility_code
JOIN {MP}.dim_product pr ON pr.product_code = p.product
CROSS JOIN de
"""


def ds_wastage():
    return f"""
WITH {stock_cte()}, {coverage_cte()},
issued AS (
  SELECT f.boundary_code, tx.product,
    sum(CASE WHEN tx_type = 'DISPATCHED' AND receiver_type = 'TEAM' THEN quantity
             WHEN tx_type = 'RETURNED' AND sender_type = 'TEAM' THEN -quantity ELSE 0 END) AS vials_used
  FROM tx JOIN {MP}.dim_facility f ON f.facility_code = tx.facility_code
  WHERE tx.product IN ('MR', 'IPV') GROUP BY 1, 2
)
SELECT d.region, d.district, d.boundary_code, i.product, {PRODUCT_LABEL.format(c='i.product')} AS product_label,
       i.vials_used, i.vials_used * pr.doses_per_unit AS doses_opened, coalesce(c.doses, 0) AS doses_administered,
       i.vials_used * pr.doses_per_unit - coalesce(c.doses, 0) AS doses_wasted,
       pr.planned_wastage_pct
FROM issued i JOIN {MP}.dim_district d ON d.boundary_code = i.boundary_code
JOIN {MP}.dim_product pr ON pr.product_code = i.product
LEFT JOIN cov c ON c.boundary_code = i.boundary_code AND c.product = i.product
"""


def ds_stock_discrepancy():
    return f"""
WITH b AS ({composite(IDX['stock'], [("wb", terms("waybillNumber")), ("product", terms("productCode")),
                                      ("type", terms("transactionType")), ("sname", terms("senderName")),
                                      ("rid", terms("receiverId")), ("rname", terms("receiverName"))],
                      {"qty": {"sum": {"field": F("quantity")}}})}),
w AS (
  SELECT {k('wb')} AS waybill, {k('product')} AS product, max({k('sname')}) AS sender_name,
         max({k('rname')}) AS receiver_name, max({k('rid')}) AS receiver_id,
         sum(CASE WHEN {k('type')} = 'DISPATCHED' THEN {v('qty.value')} ELSE 0 END) AS sent,
         sum(CASE WHEN {k('type')} = 'RECEIVED' THEN {v('qty.value')} ELSE 0 END) AS received
  FROM b GROUP BY 1, 2
)
SELECT f.region, f.district, w.waybill, w.product, pr.product_name AS product_label, w.sender_name,
       w.receiver_name AS receiving_facility, f.facility_type, w.sent, w.received, w.sent - w.received AS discrepancy
FROM w JOIN {MP}.dim_facility f ON f.facility_code = w.receiver_id
JOIN {MP}.dim_product pr ON pr.product_code = w.product
"""


def ds_stock_flow():
    return f"""
WITH {stock_cte()}
SELECT tx.product, pr.product_name AS product_label,
       CASE WHEN s.level = 1 THEN '1 National store' WHEN s.level = 2 THEN '2 ' || s.region || ' (region)'
            ELSE '3 ' || s.district || ' (district)' END AS source,
       CASE WHEN tx.receiver_type = 'TEAM' THEN '4 Vaccination teams'
            WHEN r.level = 2 THEN '2 ' || r.region || ' (region)' ELSE '3 ' || r.district || ' (district)' END AS target,
       coalesce(r.region, s.region) AS region, coalesce(r.district, s.district) AS district,
       tx.quantity, tx.quantity * pr.doses_per_unit AS doses
FROM tx JOIN {MP}.dim_facility s ON s.facility_code = tx.sender_id
LEFT JOIN {MP}.dim_facility r ON r.facility_code = tx.receiver_id
JOIN {MP}.dim_product pr ON pr.product_code = tx.product
WHERE tx.tx_type = 'DISPATCHED'
"""


def ds_stock_arcs():
    return f"""
WITH {stock_cte()}
SELECT tx.product, pr.product_name AS product_label, s.facility_name AS source_name, r.facility_name AS target_name,
       s.latitude AS source_lat, s.longitude AS source_lon, r.latitude AS target_lat, r.longitude AS target_lon,
       r.region, r.district, tx.quantity
FROM tx JOIN {MP}.dim_facility s ON s.facility_code = tx.sender_id
JOIN {MP}.dim_facility r ON r.facility_code = tx.receiver_id
JOIN {MP}.dim_product pr ON pr.product_code = tx.product
WHERE tx.tx_type = 'DISPATCHED'
"""


QS = ["qColdChainOk", "qVvmOk", "qOpenVialLabelled", "qCorrectSyringe", "qSafetyBoxUsed", "qAgeScreening",
      "qFingerMarking", "qTallyMatchesApp", "qTeamComplete", "qSocialMobilisation"]
Q_LABEL = {"qColdChainOk": "Vaccine carrier with conditioned ice packs", "qVvmOk": "VVM usable (stage 1-2)",
           "qOpenVialLabelled": "Opened vials labelled with time", "qCorrectSyringe": "Correct AD syringe per vaccine",
           "qSafetyBoxUsed": "Safety box used correctly", "qAgeScreening": "Age screening done correctly",
           "qFingerMarking": "Finger marking done", "qTallyMatchesApp": "Tally sheet matches app",
           "qTeamComplete": "Team complete and on time", "qSocialMobilisation": "Community informed (social mobilisation)"}


def ds_checklist_daily():
    aggs = {q: {"sum": {"field": F(q)}} for q in QS}
    aggs["answered"] = {"sum": {"field": F("answeredQuestions")}}
    aggs["total"] = {"sum": {"field": F("totalQuestions")}}
    return f"""
WITH b AS ({composite(IDX['checklist'], [("day", DAY), ("code", terms("boundaryHierarchyCode.district")),
                                          ("role", terms("supervisorRole")), ("name", terms("checklistName"))], aggs)})
SELECT CAST({k('day')} AS date) AS event_date, d.region, d.district, d.boundary_code,
       {k('role')} AS supervisor_role, {k('name')} AS checklist_name, {v('doc_count', 'bigint')} AS submissions,
       {v('answered.value')} AS answered_questions, {v('total.value')} AS total_questions,
       {", ".join(f"{v(q + '.value')} AS {q.lower()}" for q in QS)}
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def ds_checklist_findings():
    unions = " UNION ALL ".join(
        f"SELECT event_date, region, district, boundary_code, supervisor_role, '{Q_LABEL[q]}' AS question, "
        f"{q.lower()} AS yes_count, submissions FROM base" for q in QS)
    return f"WITH base AS ({ds_checklist_daily()})\n{unions}"


def ds_checklist_completion():
    """Submitted vs expected (team sup x2/day, district/regional/national sup x1/day)."""
    users_by = lambda idx: (f"SELECT json_extract_scalar(x, '$.key') AS user_id, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS n "
                            f"FROM {raw(idx, {'size': 0, 'aggs': {'u': {'terms': {'field': F('createdBy'), 'size': 20000}}}})} "
                            f"CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x)")
    return f"""
WITH s AS ({users_by(IDX['checklist'])}),
de AS (SELECT {DAYS_ELAPSED} AS days_elapsed)
SELECT u.region, u.district, u.user_id,
       CASE u.role_group WHEN 'TEAM_SUPERVISOR' THEN '1 Team supervisors' WHEN 'DISTRICT_SUPERVISOR' THEN '2 District supervisors'
            WHEN 'PROVINCIAL_SUPERVISOR' THEN '3 Regional supervisors' ELSE '4 National supervisors' END AS supervisor_level,
       coalesce(s.n, 0) AS submitted,
       (CASE u.role_group WHEN 'TEAM_SUPERVISOR' THEN 2 ELSE 1 END) * de.days_elapsed AS expected
FROM {MP}.dim_user u LEFT JOIN s ON s.user_id = u.user_id CROSS JOIN de
WHERE u.role_group IN ('TEAM_SUPERVISOR', 'DISTRICT_SUPERVISOR', 'PROVINCIAL_SUPERVISOR', 'NATIONAL_SUPERVISOR')
"""


def ds_complaints_daily():
    return f"""
WITH b AS ({composite(IDX['complaint'], [("day", DAY), ("code", terms("boundaryHierarchyCode.district")),
                                          ("type", terms("complaintType")), ("status", terms("applicationStatus")),
                                          ("source", terms("source"))],
                      {"hours": {"sum": {"field": F("resolutionHours")}}})})
SELECT CAST({k('day')} AS date) AS event_date, d.region, d.district, d.boundary_code,
       {k('type')} AS complaint_type, {k('status')} AS status,
       CASE WHEN {k('status')} = 'RESOLVED' THEN 'Resolved' WHEN {k('status')} = 'REJECTED' THEN 'Rejected' ELSE 'Open' END AS status_group,
       {k('source')} AS source, {v('doc_count', 'bigint')} AS complaints,
       CASE WHEN {k('status')} = 'RESOLVED' THEN {v('doc_count', 'bigint')} ELSE 0 END AS resolved,
       {v('hours.value')} AS resolution_hours
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def district_shapes(tol=0.0):
    from shapely.geometry import shape, mapping
    out = {}
    for f in json.load(open(ROOT / "data/districts.geojson"))["features"]:
        g = shape(f["geometry"]).buffer(0.01)  # small tolerance for GPS noise at borders
        g = g.simplify(0.02)
        geom = mapping(g)
        out[f["properties"]["boundary_code"]] = json.loads(json.dumps(geom, default=list).replace("(", "[").replace(")", "]"))
    return out


def ds_dq_district():
    shapes = district_shapes()
    outside = {"filters": {"filters": {
        code: {"bool": {"filter": [{"term": {F("boundaryHierarchyCode.district"): code}},
                                   {"exists": {"field": F("geoPoint")}}],
                        "must_not": [{"geo_shape": {F("geoPoint"): {"shape": geom, "relation": "intersects"}}}]}}
        for code, geom in shapes.items()}}}
    task_aggs = {
        "missing_gps": {"missing": {"field": F("latitude")}},
        "low_acc": {"filter": {"range": {F("locationAccuracy"): {"gt": 100}}}},
        "off_hours": {"filter": {"script": {"script": {"lang": "painless", "source":
                      "def h = doc[params.f].value.getHour(); return h < 6 || h >= 20;", "params": {"f": F("eventTime")}}}}},
        "dups_mr": {"filter": {"bool": {"filter": [SUCCESS, {"term": {F("productCode"): "MR"}}]}},
                    "aggs": {"t": {"terms": {"field": F("individualId"), "min_doc_count": 2, "size": 5000}}}},
        "dups_ipv": {"filter": {"bool": {"filter": [SUCCESS, {"term": {F("productCode"): "IPV"}}]}},
                     "aggs": {"t": {"terms": {"field": F("individualId"), "min_doc_count": 2, "size": 5000}}}},
    }
    ind_aggs = {"no_gender": {"missing": {"field": F("gender")}}, "no_dob": {"missing": {"field": F("dateOfBirth")}}}
    out_body = {"size": 0, "aggs": {"o": outside}}
    return f"""
WITH t AS ({composite(IDX['task'], [("code", terms("boundaryHierarchyCode.district"))], task_aggs)}),
i AS ({composite(IDX['individual'], [("code", terms("boundaryHierarchyCode.district"))], ind_aggs)}),
o AS (SELECT result FROM {raw(IDX['task'], out_body)}),
tt AS (SELECT {k('code')} AS code, {v('doc_count', 'bigint')} AS records, {v('missing_gps.doc_count', 'bigint')} AS missing_gps,
              {v('low_acc.doc_count', 'bigint')} AS low_accuracy, {v('off_hours.doc_count', 'bigint')} AS off_hours,
              json_array_length(json_extract(x, '$.dups_mr.t.buckets')) + json_array_length(json_extract(x, '$.dups_ipv.t.buckets')) AS duplicates
       FROM t),
ii AS (SELECT {k('code')} AS code, {v('doc_count', 'bigint')} AS registrations,
              {v('no_gender.doc_count', 'bigint')} + {v('no_dob.doc_count', 'bigint')} AS incomplete FROM i)
SELECT d.region, d.district, d.boundary_code, tt.records, tt.missing_gps, tt.low_accuracy, tt.off_hours, tt.duplicates,
       CAST(json_extract_scalar(o.result, '$.aggregations.o.buckets.' || d.boundary_code || '.doc_count') AS bigint) AS outside_district,
       ii.registrations, ii.incomplete
FROM {MP}.dim_district d JOIN tt ON tt.code = d.boundary_code LEFT JOIN ii ON ii.code = d.boundary_code
JOIN o ON o.result IS NOT NULL
"""


def ds_dq_users():
    return f"""
WITH b AS ({composite(IDX['task'], [("user", terms("createdBy")), ("day", DAY)], None, SUCCESS)})
SELECT u.region, u.district, {k('user')} AS user_id, u.role_group, CAST({k('day')} AS date) AS event_date,
       {v('doc_count', 'bigint')} AS doses_recorded
FROM b JOIN {MP}.dim_user u ON u.user_id = {k('user')}
"""


def ds_dq_teams():
    return f"""
WITH b AS ({composite(IDX['task'], [("team", terms("teamId")), ("day", DAY), ("code", terms("boundaryHierarchyCode.district")),
                                     ("type", terms("teamType"))], None, SUCCESS)})
SELECT d.region, d.district, d.boundary_code, {k('team')} AS team_id, {k('type')} AS team_type,
       CAST({k('day')} AS date) AS event_date, {v('doc_count', 'bigint')} AS doses_recorded
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def tiles(index, sources, query=None, precision=12, extra=None):
    aggs = {"c": {"geo_centroid": {"field": F("geoPoint")}}}
    aggs.update(extra or {})
    return composite(index, sources + [("tile", {"geotile_grid": {"field": F("geoPoint"), "precision": precision}})],
                     aggs, query)


def ds_map_delivery_tiles():
    return f"""
WITH b AS ({tiles(IDX['task'], [("code", terms("boundaryHierarchyCode.district")), ("product", terms("productCode")),
                                 ("mode", terms("deliveryMode"))], SUCCESS)})
SELECT d.region, d.district, d.boundary_code, {k('product')} AS product,
       {PRODUCT_LABEL.format(c=k('product'))} AS product_label, {MODE_LABEL.format(c=k('mode'))} AS delivery_mode,
       {v('c.location.lat')} AS latitude, {v('c.location.lon')} AS longitude, {v('doc_count', 'bigint')} AS doses
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def ds_map_registration_tiles():
    return f"""
WITH b AS ({tiles(IDX['household'], [("code", terms("boundaryHierarchyCode.district")), ("outcome", terms("visitOutcome"))],
                  extra={"m": {"sum": {"field": F("memberCount")}}})})
SELECT d.region, d.district, d.boundary_code, 'House to house' AS delivery_mode, {k('outcome')} AS visit_outcome,
       {v('c.location.lat')} AS latitude, {v('c.location.lon')} AS longitude,
       {v('doc_count', 'bigint')} AS households, {v('m.value')} AS members
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {k('code')}
"""


def hits(index, query, fields, size=10000):
    body = {"size": size, "_source": [F(f) for f in fields], "query": query,
            "sort": [{F("createdTime"): "desc"}]}
    return (f"SELECT json_extract(h, '$._source.Data') AS x FROM {raw(index, body)} "
            f"CROSS JOIN UNNEST(CAST(json_extract(result, '$.hits.hits') AS array(json))) AS t(h)")


def s(path, typ=None):
    e = f"json_extract_scalar(x, '$.{path}')"
    return f"CAST({e} AS {typ})" if typ else e


def ds_points_missed():
    q = {"bool": {"must_not": [SUCCESS], "filter": [{"exists": {"field": F("latitude")}}]}}
    return f"""
WITH b AS ({hits(IDX['task'], q, ["latitude", "longitude", "productCode", "reasonNotAdministered", "deliveryMode",
                                  "boundaryHierarchyCode", "eventTime", "teamId"])})
SELECT d.region, d.district, d.boundary_code, {s('productCode')} AS product,
       {PRODUCT_LABEL.format(c=s('productCode'))} AS product_label, {s('reasonNotAdministered')} AS reason,
       {MODE_LABEL.format(c=s('deliveryMode'))} AS delivery_mode, {s('teamId')} AS team_id,
       CAST(substr({s('eventTime')}, 1, 10) AS date) AS event_date,
       {s('latitude', 'double')} AS latitude, {s('longitude', 'double')} AS longitude
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {s('boundaryHierarchyCode.district')}
"""


def ds_points_gps_issues():
    q = {"range": {F("locationAccuracy"): {"gt": 100}}}
    return f"""
WITH b AS ({hits(IDX['task'], q, ["latitude", "longitude", "locationAccuracy", "createdBy", "boundaryHierarchyCode",
                                  "eventTime", "productCode"])})
SELECT d.region, d.district, d.boundary_code, {s('productCode')} AS product, {s('createdBy')} AS user_id,
       CAST(substr({s('eventTime')}, 1, 10) AS date) AS event_date,
       {s('locationAccuracy', 'double')} AS accuracy_m,
       {s('latitude', 'double')} AS latitude, {s('longitude', 'double')} AS longitude
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {s('boundaryHierarchyCode.district')}
"""


def ds_points_checklists():
    return f"""
WITH b AS ({hits(IDX['checklist'], {"exists": {"field": F("latitude")}},
                 ["latitude", "longitude", "supervisorRole", "checklistName", "boundaryHierarchyCode", "eventTime",
                  "answeredQuestions", "totalQuestions"])})
SELECT d.region, d.district, d.boundary_code, {s('supervisorRole')} AS supervisor_role, {s('checklistName')} AS checklist_name,
       CAST(substr({s('eventTime')}, 1, 10) AS date) AS event_date,
       {s('latitude', 'double')} AS latitude, {s('longitude', 'double')} AS longitude
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {s('boundaryHierarchyCode.district')}
"""


def ds_points_complaints():
    return f"""
WITH b AS ({hits(IDX['complaint'], {"exists": {"field": F("latitude")}},
                 ["latitude", "longitude", "complaintType", "applicationStatus", "boundaryHierarchyCode", "eventTime"])})
SELECT d.region, d.district, d.boundary_code, {s('complaintType')} AS complaint_type, {s('applicationStatus')} AS status,
       CAST(substr({s('eventTime')}, 1, 10) AS date) AS event_date,
       {s('latitude', 'double')} AS latitude, {s('longitude', 'double')} AS longitude
FROM b JOIN {MP}.dim_district d ON d.boundary_code = {s('boundaryHierarchyCode.district')}
"""


POLY = f"""FROM {MP}.dim_district_polygon p JOIN {MP}.dim_district d ON d.boundary_code = p.boundary_code"""
POLY_COLS = "p.region, p.district, p.boundary_code, p.polygon"


def ds_map_coverage():
    """Choropleth: coverage per district polygon part."""
    return f"""
WITH {coverage_cte()},
de AS (SELECT {DAYS_ELAPSED} AS days_elapsed)
SELECT {POLY_COLS},
       100.0 * coalesce(mr.doses, 0) / d.mr_target AS mr_coverage_pct,
       100.0 * coalesce(ip.doses, 0) / d.ipv_target AS ipv_coverage_pct,
       coalesce(mr.doses, 0) AS mr_doses, coalesce(ip.doses, 0) AS ipv_doses, d.mr_target, d.ipv_target,
       100.0 * coalesce(mr.doses, 0) / (d.mr_target * de.days_elapsed / {CAMPAIGN_DAYS}) AS mr_vs_plan_pct
{POLY} CROSS JOIN de
LEFT JOIN cov mr ON mr.boundary_code = p.boundary_code AND mr.product = 'MR'
LEFT JOIN cov ip ON ip.boundary_code = p.boundary_code AND ip.product = 'IPV'
"""


def ds_map_inventory():
    """Choropleth: wastage and days of stock per district."""
    return f"""
WITH wst AS (SELECT boundary_code, product, 100.0 * sum(doses_wasted) / nullif(sum(doses_opened), 0) AS pct FROM ({ds_wastage()}) GROUP BY 1, 2),
stk AS (SELECT boundary_code, product, days_of_stock FROM ({ds_stock_position()}) WHERE level = 3)
SELECT {POLY_COLS}, wm.pct AS mr_wastage_pct, wi.pct AS ipv_wastage_pct,
       km.days_of_stock AS mr_days_of_stock, ki.days_of_stock AS ipv_days_of_stock
{POLY}
LEFT JOIN wst wm ON wm.boundary_code = p.boundary_code AND wm.product = 'MR'
LEFT JOIN wst wi ON wi.boundary_code = p.boundary_code AND wi.product = 'IPV'
LEFT JOIN stk km ON km.boundary_code = p.boundary_code AND km.product = 'MR'
LEFT JOIN stk ki ON ki.boundary_code = p.boundary_code AND ki.product = 'IPV'
"""


def ds_map_quality():
    """Choropleth: GPS / duplicate issue rate and sync rates per district."""
    return f"""
WITH dq AS (SELECT boundary_code, 100.0 * (missing_gps + low_accuracy + outside_district + duplicates) / nullif(records, 0) AS pct FROM ({ds_dq_district()})),
sync AS (SELECT district, user_group, avg(synced) * 100 AS rate FROM ({ds_sync()}) GROUP BY 1, 2)
SELECT {POLY_COLS}, dq.pct AS gps_dq_issue_pct, sf.rate AS frontline_sync_pct, sd.rate AS downsync_pct
{POLY}
LEFT JOIN dq ON dq.boundary_code = p.boundary_code
LEFT JOIN sync sf ON sf.district = p.district AND sf.user_group = 'Frontline workers'
LEFT JOIN sync sd ON sd.district = p.district AND sd.user_group = 'Vaccinators downsynced'
"""


def ds_map_supervision():
    """Choropleth: supervisor checklist completion per district."""
    return f"""
WITH chk AS (SELECT district, 100.0 * sum(submitted) / nullif(sum(expected), 0) AS pct FROM ({ds_checklist_completion()}) WHERE district IS NOT NULL GROUP BY 1)
SELECT {POLY_COLS}, chk.pct AS checklist_completion_pct
{POLY} LEFT JOIN chk ON chk.district = p.district
"""


def ds_map_complaints():
    """Choropleth: complaints per 10k MR doses per district."""
    return f"""
WITH {coverage_cte()},
cmp AS (SELECT boundary_code, sum(complaints) AS n FROM ({ds_complaints_daily()}) GROUP BY 1)
SELECT {POLY_COLS}, coalesce(cmp.n, 0) AS complaints,
       10000.0 * coalesce(cmp.n, 0) / nullif(coalesce(mr.doses, 0), 0) AS complaints_per_10k
{POLY}
LEFT JOIN cov mr ON mr.boundary_code = p.boundary_code AND mr.product = 'MR'
LEFT JOIN cmp ON cmp.boundary_code = p.boundary_code
"""


def ds_planned_vs_actual():
    return f"""
WITH daily AS (
  SELECT event_date, boundary_code, product, sum(doses) AS doses FROM ({ds_delivery_daily()}) GROUP BY 1, 2, 3
),
grid AS (
  SELECT c.campaign_date AS event_date, c.day_no, c.planned_cum_pct, d.boundary_code, d.region, d.district, p.product,
         CASE p.product WHEN 'MR' THEN d.mr_target ELSE d.ipv_target END AS target
  FROM {MP}.dim_campaign_day c CROSS JOIN {MP}.dim_district d CROSS JOIN (VALUES 'MR', 'IPV') AS p(product)
),
mx AS (SELECT max(event_date) AS last_day FROM daily)
SELECT g.event_date, g.day_no, g.region, g.district, g.boundary_code, g.product,
       {PRODUCT_LABEL.format(c='g.product')} AS product_label, g.target,
       g.target * g.planned_cum_pct / 100 AS planned_cum_doses,
       CASE WHEN g.event_date <= mx.last_day THEN
         sum(coalesce(dl.doses, 0)) OVER (PARTITION BY g.boundary_code, g.product ORDER BY g.event_date) END AS actual_cum_doses
FROM grid g CROSS JOIN mx
LEFT JOIN daily dl ON dl.event_date = g.event_date AND dl.boundary_code = g.boundary_code AND dl.product = g.product
"""


DATASETS = {
    # name: (builder, main datetime column)
    "hcm_delivery_daily": (ds_delivery_daily, "event_date"),
    "hcm_coverage": (ds_coverage, None),
    "hcm_coadmin": (ds_coadmin, None),
    "hcm_age": (ds_age, None),
    "hcm_registration_daily": (ds_registration_daily, "event_date"),
    "hcm_household_daily": (ds_household_daily, "event_date"),
    "hcm_sync": (ds_sync, None),
    "hcm_stock_tx": (ds_stock_tx, "event_date"),
    "hcm_stock_position": (ds_stock_position, None),
    "hcm_wastage": (ds_wastage, None),
    "hcm_stock_discrepancy": (ds_stock_discrepancy, None),
    "hcm_stock_flow": (ds_stock_flow, None),
    "hcm_stock_arcs": (ds_stock_arcs, None),
    "hcm_checklist_daily": (ds_checklist_daily, "event_date"),
    "hcm_checklist_findings": (ds_checklist_findings, "event_date"),
    "hcm_checklist_completion": (ds_checklist_completion, None),
    "hcm_complaints_daily": (ds_complaints_daily, "event_date"),
    "hcm_dq_district": (ds_dq_district, None),
    "hcm_dq_users": (ds_dq_users, "event_date"),
    "hcm_dq_teams": (ds_dq_teams, "event_date"),
    "hcm_map_delivery_tiles": (ds_map_delivery_tiles, None),
    "hcm_map_registration_tiles": (ds_map_registration_tiles, None),
    "hcm_points_missed": (ds_points_missed, "event_date"),
    "hcm_points_gps_issues": (ds_points_gps_issues, "event_date"),
    "hcm_points_checklists": (ds_points_checklists, "event_date"),
    "hcm_points_complaints": (ds_points_complaints, "event_date"),
    "hcm_map_coverage": (ds_map_coverage, None),
    "hcm_map_inventory": (ds_map_inventory, None),
    "hcm_map_quality": (ds_map_quality, None),
    "hcm_map_supervision": (ds_map_supervision, None),
    "hcm_map_complaints": (ds_map_complaints, None),
    "hcm_planned_vs_actual": (ds_planned_vs_actual, "event_date"),
}


if __name__ == "__main__":
    out = ROOT / "sql/datasets"
    out.mkdir(parents=True, exist_ok=True)
    for name, (fn, _) in DATASETS.items():
        (out / f"{name}.sql").write_text(fn().strip() + "\n")
    print(f"wrote {len(DATASETS)} dataset SQL files to {out}")

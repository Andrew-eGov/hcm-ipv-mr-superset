WITH wst AS (SELECT boundary_code, product, 100.0 * sum(doses_wasted) / nullif(sum(doses_opened), 0) AS pct FROM (
WITH tx AS (
  SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, json_extract_scalar(x, '$.key.fac') AS facility_code, json_extract_scalar(x, '$.key.product') AS product,
         json_extract_scalar(x, '$.key.type') AS tx_type, json_extract_scalar(x, '$.key.sid') AS sender_id, json_extract_scalar(x, '$.key.sname') AS sender_name, json_extract_scalar(x, '$.key.stype') AS sender_type,
         json_extract_scalar(x, '$.key.rid') AS receiver_id, json_extract_scalar(x, '$.key.rname') AS receiver_name, json_extract_scalar(x, '$.key.rtype') AS receiver_type,
         CAST(json_extract_scalar(x, '$.qty.value') AS double) AS quantity
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"fac":{"terms":{"field":"Data.facilityId"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"type":{"terms":{"field":"Data.transactionType"}}},{"sid":{"terms":{"field":"Data.senderId"}}},{"sname":{"terms":{"field":"Data.senderName"}}},{"stype":{"terms":{"field":"Data.senderType"}}},{"rid":{"terms":{"field":"Data.receiverId"}}},{"rname":{"terms":{"field":"Data.receiverName"}}},{"rtype":{"terms":{"field":"Data.receiverType"}}}]},"aggs":{"qty":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
), cov AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, json_extract_scalar(x, '$.key.product') AS product,
         CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS attempts
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
issued AS (
  SELECT f.boundary_code, tx.product,
    sum(CASE WHEN tx_type = 'DISPATCHED' AND receiver_type = 'TEAM' THEN quantity
             WHEN tx_type = 'RETURNED' AND sender_type = 'TEAM' THEN -quantity ELSE 0 END) AS vials_used
  FROM tx JOIN microplan.public.dim_facility f ON f.facility_code = tx.facility_code
  WHERE tx.product IN ('MR', 'IPV') GROUP BY 1, 2
)
SELECT d.region, d.district, d.boundary_code, i.product, CASE i.product WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE i.product END AS product_label,
       i.vials_used, i.vials_used * pr.doses_per_unit AS doses_opened, coalesce(c.doses, 0) AS doses_administered,
       i.vials_used * pr.doses_per_unit - coalesce(c.doses, 0) AS doses_wasted,
       pr.planned_wastage_pct
FROM issued i JOIN microplan.public.dim_district d ON d.boundary_code = i.boundary_code
JOIN microplan.public.dim_product pr ON pr.product_code = i.product
LEFT JOIN cov c ON c.boundary_code = i.boundary_code AND c.product = i.product
) GROUP BY 1, 2),
stk AS (SELECT boundary_code, product, days_of_stock FROM (
WITH tx AS (
  SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, json_extract_scalar(x, '$.key.fac') AS facility_code, json_extract_scalar(x, '$.key.product') AS product,
         json_extract_scalar(x, '$.key.type') AS tx_type, json_extract_scalar(x, '$.key.sid') AS sender_id, json_extract_scalar(x, '$.key.sname') AS sender_name, json_extract_scalar(x, '$.key.stype') AS sender_type,
         json_extract_scalar(x, '$.key.rid') AS receiver_id, json_extract_scalar(x, '$.key.rname') AS receiver_name, json_extract_scalar(x, '$.key.rtype') AS receiver_type,
         CAST(json_extract_scalar(x, '$.qty.value') AS double) AS quantity
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"fac":{"terms":{"field":"Data.facilityId"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"type":{"terms":{"field":"Data.transactionType"}}},{"sid":{"terms":{"field":"Data.senderId"}}},{"sname":{"terms":{"field":"Data.senderName"}}},{"stype":{"terms":{"field":"Data.senderType"}}},{"rid":{"terms":{"field":"Data.receiverId"}}},{"rname":{"terms":{"field":"Data.receiverName"}}},{"rtype":{"terms":{"field":"Data.receiverType"}}}]},"aggs":{"qty":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
de AS (SELECT (SELECT greatest(1, least(11, date_diff('day', DATE '2026-11-09', CAST(substr(json_extract_scalar(result, '$.aggregations.m.value_as_string'), 1, 10) AS date)) + 1)) FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"m":{"max":{"field":"Data.eventTime"}}}}'))) AS days_elapsed),
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
       greatest(0, 11 - de.days_elapsed) AS days_remaining,
       CASE WHEN f.level < 3 THEN 'Intermediate store'
            WHEN p.daily_use = 0 THEN 'No consumption'
            WHEN (p.received + p.returned - p.dispatched - p.lost) / p.daily_use < least(2, greatest(0, 11 - de.days_elapsed)) THEN 'Stock-out risk'
            WHEN (p.received + p.returned - p.dispatched - p.lost) / p.daily_use < greatest(0, 11 - de.days_elapsed) THEN 'Insufficient for remaining days'
            ELSE 'Sufficient' END AS stock_status
FROM pos p JOIN microplan.public.dim_facility f ON f.facility_code = p.facility_code
JOIN microplan.public.dim_product pr ON pr.product_code = p.product
CROSS JOIN de
) WHERE level = 3)
SELECT p.region, p.district, p.boundary_code, p.polygon, wm.pct AS mr_wastage_pct, wi.pct AS ipv_wastage_pct,
       km.days_of_stock AS mr_days_of_stock, ki.days_of_stock AS ipv_days_of_stock
FROM microplan.public.dim_district_polygon p JOIN microplan.public.dim_district d ON d.boundary_code = p.boundary_code
LEFT JOIN wst wm ON wm.boundary_code = p.boundary_code AND wm.product = 'MR'
LEFT JOIN wst wi ON wi.boundary_code = p.boundary_code AND wi.product = 'IPV'
LEFT JOIN stk km ON km.boundary_code = p.boundary_code AND km.product = 'MR'
LEFT JOIN stk ki ON ki.boundary_code = p.boundary_code AND ki.product = 'IPV'

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

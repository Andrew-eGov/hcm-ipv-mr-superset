WITH daily AS (
  SELECT event_date, boundary_code, product, sum(doses) AS doses FROM (
WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"status":{"terms":{"field":"Data.administrationStatus"}}},{"reason":{"terms":{"field":"Data.reasonNotAdministered","missing_bucket":true}}},{"mode":{"terms":{"field":"Data.deliveryMode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, d.region, d.district, d.boundary_code,
       json_extract_scalar(x, '$.key.product') AS product, CASE json_extract_scalar(x, '$.key.product') WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE json_extract_scalar(x, '$.key.product') END AS product_label,
       json_extract_scalar(x, '$.key.status') AS status, coalesce(json_extract_scalar(x, '$.key.reason'), 'ADMINISTERED') AS reason,
       CASE json_extract_scalar(x, '$.key.mode') WHEN 'FIXED_POST' THEN 'Fixed post' WHEN 'HOUSE_TO_HOUSE' THEN 'House to house' WHEN 'TRANSIT_POST' THEN 'Transit post' ELSE json_extract_scalar(x, '$.key.mode') END AS delivery_mode,
       CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS records, CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')
) GROUP BY 1, 2, 3
),
grid AS (
  SELECT c.campaign_date AS event_date, c.day_no, c.planned_cum_pct, d.boundary_code, d.region, d.district, p.product,
         CASE p.product WHEN 'MR' THEN d.mr_target ELSE d.ipv_target END AS target
  FROM microplan.public.dim_campaign_day c CROSS JOIN microplan.public.dim_district d CROSS JOIN (VALUES 'MR', 'IPV') AS p(product)
),
mx AS (SELECT max(event_date) AS last_day FROM daily)
SELECT g.event_date, g.day_no, g.region, g.district, g.boundary_code, g.product,
       CASE g.product WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE g.product END AS product_label, g.target,
       g.target * g.planned_cum_pct / 100 AS planned_cum_doses,
       CASE WHEN g.event_date <= mx.last_day THEN
         sum(coalesce(dl.doses, 0)) OVER (PARTITION BY g.boundary_code, g.product ORDER BY g.event_date) END AS actual_cum_doses
FROM grid g CROSS JOIN mx
LEFT JOIN daily dl ON dl.event_date = g.event_date AND dl.boundary_code = g.boundary_code AND dl.product = g.product

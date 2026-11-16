WITH cov AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, json_extract_scalar(x, '$.key.product') AS product,
         CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS attempts
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
de AS (SELECT (SELECT greatest(1, least(11, date_diff('day', DATE '2026-11-09', CAST(substr(json_extract_scalar(result, '$.aggregations.m.value_as_string'), 1, 10) AS date)) + 1)) FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"m":{"max":{"field":"Data.eventTime"}}}}'))) AS days_elapsed)
SELECT d.region, d.district, d.boundary_code, p.product,
       CASE p.product WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE p.product END AS product_label,
       coalesce(c.doses, 0) AS doses, coalesce(c.attempts, 0) AS attempts,
       CASE p.product WHEN 'MR' THEN d.mr_target ELSE d.ipv_target END AS target,
       CASE p.product WHEN 'MR' THEN d.mr_target ELSE d.ipv_target END * de.days_elapsed / 11 AS planned_to_date,
       de.days_elapsed, d.u5_population, d.teams_total, d.centroid_lat, d.centroid_lon
FROM microplan.public.dim_district d
CROSS JOIN (VALUES 'MR', 'IPV') AS p(product)
CROSS JOIN de
LEFT JOIN cov c ON c.boundary_code = d.boundary_code AND c.product = p.product

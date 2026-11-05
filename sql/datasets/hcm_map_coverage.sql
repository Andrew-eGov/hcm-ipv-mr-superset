WITH cov AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, json_extract_scalar(x, '$.key.product') AS product,
         CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS attempts
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
de AS (SELECT (SELECT greatest(1, least(11, date_diff('day', DATE '2026-11-09', CAST(substr(json_extract_scalar(result, '$.aggregations.m.value_as_string'), 1, 10) AS date)) + 1)) FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"m":{"max":{"field":"Data.eventTime"}}}}'))) AS days_elapsed)
SELECT p.region, p.district, p.boundary_code, p.polygon,
       100.0 * coalesce(mr.doses, 0) / d.mr_target AS mr_coverage_pct,
       100.0 * coalesce(ip.doses, 0) / d.ipv_target AS ipv_coverage_pct,
       coalesce(mr.doses, 0) AS mr_doses, coalesce(ip.doses, 0) AS ipv_doses, d.mr_target, d.ipv_target,
       100.0 * coalesce(mr.doses, 0) / (d.mr_target * de.days_elapsed / 11) AS mr_vs_plan_pct
FROM microplan.public.dim_district_polygon p JOIN microplan.public.dim_district d ON d.boundary_code = p.boundary_code CROSS JOIN de
LEFT JOIN cov mr ON mr.boundary_code = p.boundary_code AND mr.product = 'MR'
LEFT JOIN cov ip ON ip.boundary_code = p.boundary_code AND ip.product = 'IPV'

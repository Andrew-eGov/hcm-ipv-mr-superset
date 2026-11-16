WITH cov AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, json_extract_scalar(x, '$.key.product') AS product,
         CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS attempts
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
cmp AS (SELECT boundary_code, sum(complaints) AS n FROM (
WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'pgr-services-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"type":{"terms":{"field":"Data.complaintType"}}},{"status":{"terms":{"field":"Data.applicationStatus"}}},{"source":{"terms":{"field":"Data.source"}}}]},"aggs":{"hours":{"sum":{"field":"Data.resolutionHours"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, d.region, d.district, d.boundary_code,
       json_extract_scalar(x, '$.key.type') AS complaint_type, json_extract_scalar(x, '$.key.status') AS status,
       CASE WHEN json_extract_scalar(x, '$.key.status') = 'RESOLVED' THEN 'Resolved' WHEN json_extract_scalar(x, '$.key.status') = 'REJECTED' THEN 'Rejected' ELSE 'Open' END AS status_group,
       json_extract_scalar(x, '$.key.source') AS source, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS complaints,
       CASE WHEN json_extract_scalar(x, '$.key.status') = 'RESOLVED' THEN CAST(json_extract_scalar(x, '$.doc_count') AS bigint) ELSE 0 END AS resolved,
       CAST(json_extract_scalar(x, '$.hours.value') AS double) AS resolution_hours
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')
) GROUP BY 1)
SELECT p.region, p.district, p.boundary_code, p.polygon, coalesce(cmp.n, 0) AS complaints,
       10000.0 * coalesce(cmp.n, 0) / nullif(coalesce(mr.doses, 0), 0) AS complaints_per_10k
FROM microplan.public.dim_district_polygon p JOIN microplan.public.dim_district d ON d.boundary_code = p.boundary_code
LEFT JOIN cov mr ON mr.boundary_code = p.boundary_code AND mr.product = 'MR'
LEFT JOIN cmp ON cmp.boundary_code = p.boundary_code

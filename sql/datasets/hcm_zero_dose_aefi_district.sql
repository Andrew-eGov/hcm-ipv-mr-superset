WITH cov AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, json_extract_scalar(x, '$.key.product') AS product,
         CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS attempts
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
zd AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, CAST(json_extract_scalar(x, '$.kids.value') AS bigint) AS children, CAST(json_extract_scalar(x, '$.z.kids.value') AS bigint) AS zd_children
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}}]},"aggs":{"kids":{"cardinality":{"field":"Data.individualId","precision_threshold":40000}},"z":{"filter":{"term":{"Data.zeroDose":true}},"aggs":{"kids":{"cardinality":{"field":"Data.individualId","precision_threshold":40000}}}}}}},"query":{"term":{"Data.administrationStatus":"ADMINISTRATION_SUCCESS"}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
ae AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS aefi, CAST(json_extract_scalar(x, '$.s.doc_count') AS bigint) AS aefi_serious
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'aefi-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}}]},"aggs":{"s":{"filter":{"term":{"Data.severity":"SERIOUS"}}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
dz AS (SELECT boundary_code, sum(doses) AS doses FROM cov GROUP BY 1)
SELECT d.region, d.district, d.boundary_code, coalesce(zd.children, 0) AS children, coalesce(zd.zd_children, 0) AS zd_children,
       coalesce(dz.doses, 0) AS doses, coalesce(ae.aefi, 0) AS aefi, coalesce(ae.aefi_serious, 0) AS aefi_serious
FROM microplan.public.dim_district d
LEFT JOIN zd ON zd.boundary_code = d.boundary_code
LEFT JOIN ae ON ae.boundary_code = d.boundary_code
LEFT JOIN dz ON dz.boundary_code = d.boundary_code

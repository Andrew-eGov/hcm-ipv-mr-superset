WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}}]},"aggs":{"children":{"cardinality":{"field":"Data.individualId","precision_threshold":40000}},"mr":{"filter":{"term":{"Data.productCode":"MR"}}},"ipv":{"filter":{"term":{"Data.productCode":"IPV"}}}}}},"query":{"bool":{"filter":[{"term":{"Data.administrationStatus":"ADMINISTRATION_SUCCESS"}},{"range":{"Data.ageInMonths":{"gte":9,"lte":59}}}]}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT d.region, d.district, d.boundary_code,
       CAST(json_extract_scalar(x, '$.children.value') AS bigint) AS children_9_59,
       CAST(json_extract_scalar(x, '$.mr.doc_count') AS bigint) AS mr_9_59, CAST(json_extract_scalar(x, '$.ipv.doc_count') AS bigint) AS ipv_9_59,
       greatest(0, least(CAST(json_extract_scalar(x, '$.mr.doc_count') AS bigint), CAST(json_extract_scalar(x, '$.ipv.doc_count') AS bigint),
                CAST(json_extract_scalar(x, '$.mr.doc_count') AS bigint) + CAST(json_extract_scalar(x, '$.ipv.doc_count') AS bigint) - CAST(json_extract_scalar(x, '$.children.value') AS bigint))) AS both_9_59,
       d.ipv_target * 51.0 / 56 AS target_9_59
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')

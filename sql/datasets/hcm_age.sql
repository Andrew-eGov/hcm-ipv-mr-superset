WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"age":{"histogram":{"field":"Data.ageInMonths","interval":1}}},{"gender":{"terms":{"field":"Data.gender","missing_bucket":true}}}]}}},"query":{"term":{"Data.administrationStatus":"ADMINISTRATION_SUCCESS"}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT d.region, d.district, d.boundary_code, json_extract_scalar(x, '$.key.product') AS product,
       CASE json_extract_scalar(x, '$.key.product') WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE json_extract_scalar(x, '$.key.product') END AS product_label,
       CAST(json_extract_scalar(x, '$.key.age') AS double) AS age_months,
       CASE WHEN CAST(json_extract_scalar(x, '$.key.age') AS double) < 9 THEN '1. 4-8 months (fIPV only)'
            WHEN CAST(json_extract_scalar(x, '$.key.age') AS double) < 60 THEN '2. 9-59 months (MR + fIPV)'
            ELSE '3. 5-9 years (MR only)' END AS age_group,
       CAST(floor(CAST(json_extract_scalar(x, '$.key.age') AS double) / 12) AS integer) AS age_years,
       coalesce(json_extract_scalar(x, '$.key.gender'), 'NOT RECORDED') AS gender, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS doses
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')

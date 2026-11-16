WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'aefi-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"sev":{"terms":{"field":"Data.severity"}}},{"sym":{"terms":{"field":"Data.symptom"}}},{"out":{"terms":{"field":"Data.outcome"}}},{"inv":{"terms":{"field":"Data.investigationStatus"}}}]}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, d.region, d.district, d.boundary_code,
       json_extract_scalar(x, '$.key.product') AS product,
       CASE json_extract_scalar(x, '$.key.product') WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE 'MR + fIPV (not attributable)' END AS suspected_vaccine,
       CASE json_extract_scalar(x, '$.key.sev') WHEN 'SERIOUS' THEN 'Serious' ELSE 'Non-serious' END AS severity, lower(replace(json_extract_scalar(x, '$.key.sym'), '_', ' ')) AS symptom,
       lower(json_extract_scalar(x, '$.key.out')) AS outcome, lower(replace(json_extract_scalar(x, '$.key.inv'), '_', ' ')) AS investigation,
       CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS cases,
       CASE WHEN json_extract_scalar(x, '$.key.sev') = 'SERIOUS' THEN CAST(json_extract_scalar(x, '$.doc_count') AS bigint) ELSE 0 END AS serious_cases
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')

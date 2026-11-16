WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'household-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"outcome":{"terms":{"field":"Data.visitOutcome"}}}]},"aggs":{"members":{"sum":{"field":"Data.memberCount"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, d.region, d.district, d.boundary_code,
       'House to house' AS delivery_mode, json_extract_scalar(x, '$.key.outcome') AS visit_outcome,
       CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS households, CAST(json_extract_scalar(x, '$.members.value') AS double) AS members
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')

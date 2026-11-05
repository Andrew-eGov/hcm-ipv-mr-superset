WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'pgr-services-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"type":{"terms":{"field":"Data.complaintType"}}},{"status":{"terms":{"field":"Data.applicationStatus"}}},{"source":{"terms":{"field":"Data.source"}}}]},"aggs":{"hours":{"sum":{"field":"Data.resolutionHours"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, d.region, d.district, d.boundary_code,
       json_extract_scalar(x, '$.key.type') AS complaint_type, json_extract_scalar(x, '$.key.status') AS status,
       CASE WHEN json_extract_scalar(x, '$.key.status') = 'RESOLVED' THEN 'Resolved' WHEN json_extract_scalar(x, '$.key.status') = 'REJECTED' THEN 'Rejected' ELSE 'Open' END AS status_group,
       json_extract_scalar(x, '$.key.source') AS source, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS complaints,
       CASE WHEN json_extract_scalar(x, '$.key.status') = 'RESOLVED' THEN CAST(json_extract_scalar(x, '$.doc_count') AS bigint) ELSE 0 END AS resolved,
       CAST(json_extract_scalar(x, '$.hours.value') AS double) AS resolution_hours
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.key.code')

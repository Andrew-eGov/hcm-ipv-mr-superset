WITH b AS (SELECT json_extract(h, '$._source.Data') AS x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":10000,"_source":["Data.latitude","Data.longitude","Data.locationAccuracy","Data.createdBy","Data.boundaryHierarchyCode","Data.eventTime","Data.productCode"],"query":{"range":{"Data.locationAccuracy":{"gt":100}}},"sort":[{"Data.createdTime":"desc"}]}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.hits.hits') AS array(json))) AS t(h))
SELECT d.region, d.district, d.boundary_code, json_extract_scalar(x, '$.productCode') AS product, json_extract_scalar(x, '$.createdBy') AS user_id,
       CAST(substr(json_extract_scalar(x, '$.eventTime'), 1, 10) AS date) AS event_date,
       CAST(json_extract_scalar(x, '$.locationAccuracy') AS double) AS accuracy_m,
       CAST(json_extract_scalar(x, '$.latitude') AS double) AS latitude, CAST(json_extract_scalar(x, '$.longitude') AS double) AS longitude
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.boundaryHierarchyCode.district')

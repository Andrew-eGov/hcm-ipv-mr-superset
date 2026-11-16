WITH b AS (SELECT json_extract(h, '$._source.Data') AS x FROM TABLE(hcm.system.raw_query('default', 'pgr-services-index-v1', '{"size":10000,"_source":["Data.latitude","Data.longitude","Data.complaintType","Data.applicationStatus","Data.boundaryHierarchyCode","Data.eventTime"],"query":{"exists":{"field":"Data.latitude"}},"sort":[{"Data.createdTime":"desc"}]}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.hits.hits') AS array(json))) AS t(h))
SELECT d.region, d.district, d.boundary_code, json_extract_scalar(x, '$.complaintType') AS complaint_type, json_extract_scalar(x, '$.applicationStatus') AS status,
       CAST(substr(json_extract_scalar(x, '$.eventTime'), 1, 10) AS date) AS event_date,
       CAST(json_extract_scalar(x, '$.latitude') AS double) AS latitude, CAST(json_extract_scalar(x, '$.longitude') AS double) AS longitude
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.boundaryHierarchyCode.district')

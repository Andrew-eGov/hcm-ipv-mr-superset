WITH b AS (SELECT json_extract(h, '$._source.Data') AS x FROM TABLE(hcm.system.raw_query('default', 'aefi-index-v1', '{"size":10000,"_source":["Data.latitude","Data.longitude","Data.severity","Data.symptom","Data.productCode","Data.outcome","Data.boundaryHierarchyCode","Data.eventTime"],"query":{"exists":{"field":"Data.latitude"}},"sort":[{"Data.createdTime":"desc"}]}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.hits.hits') AS array(json))) AS t(h))
SELECT d.region, d.district, d.boundary_code, json_extract_scalar(x, '$.productCode') AS product,
       CASE json_extract_scalar(x, '$.severity') WHEN 'SERIOUS' THEN 'Serious' ELSE 'Non-serious' END AS severity, lower(replace(json_extract_scalar(x, '$.symptom'), '_', ' ')) AS symptom,
       lower(json_extract_scalar(x, '$.outcome')) AS outcome, CAST(substr(json_extract_scalar(x, '$.eventTime'), 1, 10) AS date) AS event_date,
       CAST(json_extract_scalar(x, '$.latitude') AS double) AS latitude, CAST(json_extract_scalar(x, '$.longitude') AS double) AS longitude
FROM b JOIN microplan.public.dim_district d ON d.boundary_code = json_extract_scalar(x, '$.boundaryHierarchyCode.district')

WITH fl AS (SELECT json_extract_scalar(x, '$.key') AS user_id FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1,individual-index-v1,household-index-v1', '{"size":0,"aggs":{"u":{"terms":{"field":"Data.createdBy","size":20000}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x)),
sv AS (SELECT json_extract_scalar(x, '$.key') AS user_id FROM TABLE(hcm.system.raw_query('default', 'service-task-v1', '{"size":0,"aggs":{"u":{"terms":{"field":"Data.createdBy","size":20000}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x)),
ds AS (SELECT json_extract_scalar(x, '$.key') AS user_id FROM TABLE(hcm.system.raw_query('default', 'downsync-index-v1', '{"size":0,"aggs":{"u":{"terms":{"field":"Data.createdBy","size":20000}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x)),
st AS (SELECT json_extract_scalar(x, '$.key') AS facility_code FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"u":{"terms":{"field":"Data.facilityId","size":5000}}}}'))
       CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x))
SELECT u.region, u.district, 'Frontline workers' AS user_group, u.user_id AS entity_id,
       CASE WHEN fl.user_id IS NOT NULL THEN 1 ELSE 0 END AS synced
FROM microplan.public.dim_user u LEFT JOIN fl ON fl.user_id = u.user_id WHERE u.role_group IN ('VACCINATOR', 'REGISTRAR')
UNION ALL
SELECT u.region, u.district, 'Supervisors', u.user_id, CASE WHEN sv.user_id IS NOT NULL THEN 1 ELSE 0 END
FROM microplan.public.dim_user u LEFT JOIN sv ON sv.user_id = u.user_id
WHERE u.role_group IN ('TEAM_SUPERVISOR', 'DISTRICT_SUPERVISOR', 'PROVINCIAL_SUPERVISOR', 'NATIONAL_SUPERVISOR')
UNION ALL
SELECT u.region, u.district, 'Vaccinators downsynced', u.user_id, CASE WHEN ds.user_id IS NOT NULL THEN 1 ELSE 0 END
FROM microplan.public.dim_user u LEFT JOIN ds ON ds.user_id = u.user_id WHERE u.role_group = 'VACCINATOR'
UNION ALL
SELECT f.region, f.district, 'Warehouses', f.facility_code, CASE WHEN st.facility_code IS NOT NULL THEN 1 ELSE 0 END
FROM microplan.public.dim_facility f LEFT JOIN st ON st.facility_code = f.facility_code

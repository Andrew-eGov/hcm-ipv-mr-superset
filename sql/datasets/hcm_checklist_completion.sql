WITH s AS (SELECT json_extract_scalar(x, '$.key') AS user_id, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS n FROM TABLE(hcm.system.raw_query('default', 'service-task-v1', '{"size":0,"aggs":{"u":{"terms":{"field":"Data.createdBy","size":20000}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.u.buckets') AS array(json))) AS t(x)),
de AS (SELECT (SELECT greatest(1, least(11, date_diff('day', DATE '2026-11-09', CAST(substr(json_extract_scalar(result, '$.aggregations.m.value_as_string'), 1, 10) AS date)) + 1)) FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"m":{"max":{"field":"Data.eventTime"}}}}'))) AS days_elapsed)
SELECT u.region, u.district, u.user_id,
       CASE u.role_group WHEN 'TEAM_SUPERVISOR' THEN '1 Team supervisors' WHEN 'DISTRICT_SUPERVISOR' THEN '2 District supervisors'
            WHEN 'PROVINCIAL_SUPERVISOR' THEN '3 Regional supervisors' ELSE '4 National supervisors' END AS supervisor_level,
       coalesce(s.n, 0) AS submitted,
       (CASE u.role_group WHEN 'TEAM_SUPERVISOR' THEN 2 ELSE 1 END) * de.days_elapsed AS expected
FROM microplan.public.dim_user u LEFT JOIN s ON s.user_id = u.user_id CROSS JOIN de
WHERE u.role_group IN ('TEAM_SUPERVISOR', 'DISTRICT_SUPERVISOR', 'PROVINCIAL_SUPERVISOR', 'NATIONAL_SUPERVISOR')

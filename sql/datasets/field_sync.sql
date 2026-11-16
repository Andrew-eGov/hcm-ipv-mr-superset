SELECT u.region, y.district, 'Frontline workers' AS user_group, u.user_id AS entity_id, y.synced, y.synthetic
FROM hcm.default."field-user-sync-v1" y JOIN microplan.public.dim_user u ON u.user_id = y.user_id
WHERE y.district IN (SELECT DISTINCT district FROM microplan.public.dim_site)
UNION ALL
SELECT u.region, y.district, 'Vaccinators downsynced', u.user_id, y.downsynced, y.synthetic
FROM hcm.default."field-user-sync-v1" y JOIN microplan.public.dim_user u ON u.user_id = y.user_id
WHERE y.role_group = 'VACCINATOR' AND y.district IN (SELECT DISTINCT district FROM microplan.public.dim_site)

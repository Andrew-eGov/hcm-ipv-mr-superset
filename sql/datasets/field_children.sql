SELECT s.region, s.district, s.boundary_code, s.cluster, s.site_code, s.site_name, s.facility_type, v.product, v.product AS product_label, CAST(c.event_date AS date) AS event_date,
       c.age_group, coalesce(nullif(c.gender, ''), 'Not recorded') AS gender, c.vaccine_status, 1 AS children
FROM hcm.default."field-child-v1" c
JOIN microplan.public.dim_site s ON s.site_code = c.site_code
CROSS JOIN UNNEST(ARRAY['MR', 'IPV'], ARRAY[c.mr, c.ipv]) AS v(product, received)
WHERE v.received = 1

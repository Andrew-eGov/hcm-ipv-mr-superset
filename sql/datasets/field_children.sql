SELECT s.region, s.district, s.boundary_code, s.cluster, s.site_code, s.site_name, s.facility_type, v.product, v.product AS product_label, CAST(c.event_date AS date) AS event_date,
       c.age_group, CASE c.gender WHEN 'MALE' THEN 'Male' WHEN 'FEMALE' THEN 'Female' ELSE 'Not recorded' END AS gender,
       c.gender_synthetic, c.vaccine_status, 1 AS children
FROM hcm.default."field-child-v1" c
JOIN microplan.public.dim_site s ON s.site_code = c.site_code
CROSS JOIN UNNEST(ARRAY['MR', 'IPV'], ARRAY[c.mr, c.ipv]) AS v(product, received)
WHERE v.received = 1

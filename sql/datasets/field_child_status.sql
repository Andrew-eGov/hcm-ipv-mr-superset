SELECT s.region, s.district, s.cluster, s.boundary_code, s.site_code, s.site_name, s.facility_type, s.data_scope, CAST(c.event_date AS date) AS event_date, c.age_group, c.vaccine_status, 1 AS children,
       c.zero_dose, c.zero_dose_synthetic, c.aefi, c.aefi_synthetic
FROM hcm.default."field-child-v1" c
JOIN microplan.public.dim_site s ON s.site_code = c.site_code

SELECT * FROM (
SELECT s.region, s.district, s.cluster, s.boundary_code, s.site_code, s.site_name, s.facility_type, s.data_scope, s.latitude, s.longitude,
       f.vaccine AS product, f.vaccine AS product_label,
       CAST(f.event_date AS date) AS event_date, f.campaign_day, f.source_campaign_day,
       CAST(f.target AS double) AS target,
       CAST(f.total_vaccinated AS double) AS vaccinated,
       CAST(f.vials_received AS double) AS vials_received,
       CAST(f.additional_vials_received AS double) AS additional_vials_received,
       CAST(f.vials_opened AS double) AS vials_opened,
       CAST(f.vials_returned_unopened AS double) AS vials_returned_unopened,
       CASE WHEN f.vials_received IS NOT NULL THEN CAST(coalesce(f.vials_received, 0) + coalesce(f.additional_vials_received, 0) - coalesce(f.vials_returned_unopened, 0) AS double) END AS vials_issued_net,
       CAST(p.doses_per_unit AS double) AS doses_per_vial,
       CAST(f.vials_opened * p.doses_per_unit AS double) AS doses_opened,
       CASE WHEN f.vials_received IS NOT NULL THEN f.target / CAST(p.doses_per_unit AS double) * (1 + p.planned_wastage_pct / 100.0) END AS vials_needed,
       CASE WHEN f.vials_received IS NOT NULL THEN CAST(coalesce(f.vials_received, 0) + coalesce(f.additional_vials_received, 0) - coalesce(f.vials_opened, 0) - coalesce(f.vials_returned_unopened, 0) AS double) END AS stock_unbalanced_vials,
       f.vaccinated_6_11m, f.vaccinated_14w_11m, f.vaccinated_12_59m, f.vaccinated_5_10y
FROM hcm.default."field-site-day-v1" f
JOIN microplan.public.dim_site s ON s.site_code = f.site_code
JOIN microplan.public.dim_product p ON p.product_code = f.vaccine) x WHERE x.data_scope = 'full'

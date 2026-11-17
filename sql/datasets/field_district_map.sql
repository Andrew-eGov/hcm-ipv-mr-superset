SELECT d.region, d.district, d.boundary_code, d.part_no, d.polygon, c.mr_coverage_pct, c.ipv_coverage_pct,
       z.zero_dose_children, round(z.zero_dose_pct, 1) AS zero_dose_pct
FROM microplan.public.dim_district_polygon d
LEFT JOIN (
SELECT boundary_code, sum(CASE WHEN product = 'MR' THEN vaccinated END) AS mr_vaccinated,
       sum(CASE WHEN product = 'IPV' THEN vaccinated END) AS ipv_vaccinated,
       sum(CASE WHEN product = 'MR' THEN vaccinated END) / nullif(sum(CASE WHEN product = 'MR' THEN target END), 0) * 100 AS mr_coverage_pct,
       sum(CASE WHEN product = 'IPV' THEN vaccinated END) / nullif(sum(CASE WHEN product = 'IPV' THEN target END), 0) * 100 AS ipv_coverage_pct
FROM (
SELECT s.region, s.district, s.boundary_code, s.site_code, s.site_name, s.facility_type, s.latitude, s.longitude,
       f.vaccine AS product, f.vaccine AS product_label,
       CAST(f.event_date AS date) AS event_date, f.campaign_day, f.source_campaign_day,
       CAST(f.target AS double) AS target,
       CAST(f.total_vaccinated AS double) AS vaccinated,
       CAST(f.vials_received AS double) AS vials_received,
       CAST(f.additional_vials_received AS double) AS additional_vials_received,
       CAST(f.vials_opened AS double) AS vials_opened,
       CAST(f.vials_returned_unopened AS double) AS vials_returned_unopened,
       CAST(coalesce(f.vials_received, 0) + coalesce(f.additional_vials_received, 0) - coalesce(f.vials_returned_unopened, 0) AS double) AS vials_issued_net,
       CAST(p.doses_per_unit AS double) AS doses_per_vial,
       CAST(f.vials_opened * p.doses_per_unit AS double) AS doses_opened,
       f.target / CAST(p.doses_per_unit AS double) * (1 + p.planned_wastage_pct / 100.0) AS vials_needed,
       CAST(coalesce(f.vials_received, 0) + coalesce(f.additional_vials_received, 0) - coalesce(f.vials_opened, 0) - coalesce(f.vials_returned_unopened, 0) AS double) AS stock_unbalanced_vials,
       f.vaccinated_6_11m, f.vaccinated_14w_11m, f.vaccinated_12_59m, f.vaccinated_5_10y
FROM hcm.default."field-site-day-v1" f
JOIN microplan.public.dim_site s ON s.site_code = f.site_code
JOIN microplan.public.dim_product p ON p.product_code = f.vaccine) b GROUP BY boundary_code) c ON c.boundary_code = d.boundary_code
LEFT JOIN (
SELECT s.boundary_code AS k, count(*) AS children, sum(c.zero_dose) AS zero_dose_children,
       100.0 * sum(c.zero_dose) / count(*) AS zero_dose_pct
FROM hcm.default."field-child-v1" c JOIN microplan.public.dim_site s ON s.site_code = c.site_code GROUP BY 1) z ON z.k = d.boundary_code

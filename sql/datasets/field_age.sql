SELECT b.region, b.district, b.cluster, b.site_name, b.product, b.product_label, b.event_date,
       t.age_group, t.age_order, t.vaccinated
FROM (
SELECT s.region, s.district, s.boundary_code, s.cluster, s.site_code, s.site_name, s.facility_type, s.latitude, s.longitude,
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
JOIN microplan.public.dim_product p ON p.product_code = f.vaccine) b
CROSS JOIN UNNEST(ARRAY['6-11 months', '14 weeks-11 months', '12-59 months', '5-10 years'], ARRAY[1, 1, 2, 3],
                  ARRAY[b.vaccinated_6_11m, b.vaccinated_14w_11m, b.vaccinated_12_59m, b.vaccinated_5_10y])
  AS t(age_group, age_order, vaccinated)
WHERE t.vaccinated IS NOT NULL

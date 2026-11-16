WITH b AS (
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
JOIN microplan.public.dim_product p ON p.product_code = f.vaccine),
 l AS (SELECT site_code, CAST(event_date AS date) AS event_date, sum(mr) AS mr, sum(ipv) AS ipv FROM hcm.default."field-child-v1" GROUP BY 1, 2),
 cs AS (SELECT site_code, CAST(event_date AS date) AS event_date, max(source_campaign_day) AS child_day FROM hcm.default."field-child-v1" GROUP BY 1, 2)
SELECT b.region, b.district, b.cluster, b.site_code, b.site_name, b.facility_type, b.latitude, b.longitude,
       b.product, b.product_label, b.event_date, b.campaign_day, b.source_campaign_day,
       b.vaccinated, b.target, b.doses_opened, b.stock_unbalanced_vials,
       CAST(coalesce(CASE b.product WHEN 'MR' THEN l.mr ELSE l.ipv END, 0) AS double) AS children_listed,
       CASE WHEN b.stock_unbalanced_vials <> 0 THEN 1 ELSE 0 END AS stock_unbalanced,
       CASE WHEN b.vials_received IS NULL THEN 1 ELSE 0 END AS stock_missing,
       CASE WHEN coalesce(CASE b.product WHEN 'MR' THEN l.mr ELSE l.ipv END, 0) <> b.vaccinated THEN 1 ELSE 0 END AS list_vs_aggregate_mismatch,
       CASE WHEN b.vaccinated > b.target THEN 1 ELSE 0 END AS above_target,
       CASE WHEN b.vaccinated > b.doses_opened THEN 1 ELSE 0 END AS more_children_than_doses,
       CASE WHEN b.source_campaign_day <> b.campaign_day OR cs.child_day <> b.campaign_day THEN 1 ELSE 0 END AS day_label_mismatch,
       CASE WHEN s.coord_source LIKE 'Approximate%' THEN 1 ELSE 0 END AS approximate_location,
       CASE WHEN b.stock_unbalanced_vials <> 0 THEN 'Stock not balanced'
            WHEN b.vaccinated > b.doses_opened THEN 'More children than doses'
            WHEN coalesce(CASE b.product WHEN 'MR' THEN l.mr ELSE l.ipv END, 0) <> b.vaccinated THEN 'Line list differs'
            ELSE 'No issue' END AS dq_status
FROM b
JOIN microplan.public.dim_site s ON s.site_code = b.site_code
LEFT JOIN l ON l.site_code = b.site_code AND l.event_date = b.event_date
LEFT JOIN cs ON cs.site_code = b.site_code AND cs.event_date = b.event_date

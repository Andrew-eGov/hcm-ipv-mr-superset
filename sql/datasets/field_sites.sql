WITH n AS (SELECT site_code,
       sum(CASE WHEN product = 'MR' THEN vials_received + additional_vials_received END) AS mr_received,
       sum(CASE WHEN product = 'MR' THEN vials_returned_unopened END) AS mr_returned,
       sum(CASE WHEN product = 'MR' THEN vials_issued_net END) AS mr_issued,
       sum(CASE WHEN product = 'MR' THEN vials_needed END) AS mr_needed,
       sum(CASE WHEN product = 'IPV' THEN vials_received + additional_vials_received END) AS ipv_received,
       sum(CASE WHEN product = 'IPV' THEN vials_returned_unopened END) AS ipv_returned,
       sum(CASE WHEN product = 'IPV' THEN vials_issued_net END) AS ipv_issued,
       sum(CASE WHEN product = 'IPV' THEN vials_needed END) AS ipv_needed
       FROM (
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
JOIN microplan.public.dim_product p ON p.product_code = f.vaccine) b GROUP BY 1)
SELECT s.region, s.district, s.cluster, s.boundary_code, s.site_code, s.site_name, s.facility_type, s.data_scope, s.site_name AS "Facility", s.cluster AS "Cluster name", s.district AS "District name", s.latitude, s.longitude, s.coord_source, s.team_note,
       z.children AS "Children vaccinated", c.mr_vaccinated AS "MR delivered", c.ipv_vaccinated AS "IPV delivered",
       z.zero_dose_children AS "Zero-dose children", z.zero_dose_children AS zero_dose_children,
       CASE WHEN c.mr_coverage_pct IS NULL THEN 'No data'
            WHEN least(c.mr_coverage_pct, coalesce(c.ipv_coverage_pct, c.mr_coverage_pct)) < 50 THEN 'Low coverage (below 50%)'
            WHEN least(c.mr_coverage_pct, coalesce(c.ipv_coverage_pct, c.mr_coverage_pct)) < 90 THEN 'Mid coverage (50-90%)'
            ELSE 'High coverage (90%+)' END AS coverage_status,
       round(c.mr_coverage_pct, 0) AS "MR coverage %", round(c.ipv_coverage_pct, 0) AS "IPV coverage %",
       round(c.mr_coverage_pct, 1) AS mr_coverage_pct, round(c.ipv_coverage_pct, 1) AS ipv_coverage_pct,
       CASE WHEN n.mr_issued IS NULL THEN 'No stock data' WHEN n.mr_issued < n.mr_needed THEN 'Not enough vials for target' ELSE 'Enough vials for target' END AS mr_stock_status,
       CASE WHEN n.mr_issued IS NULL THEN 'No stock data' WHEN n.mr_issued < n.mr_needed THEN 'Not enough vials for target' ELSE 'Enough vials for target' END AS "MR status",
       n.mr_received AS "MR vials received (incl. additional)", n.mr_returned AS "MR vials left over (returned unopened)",
       n.mr_issued AS "MR vials used (issued net)", round(n.mr_needed, 1) AS "MR vials needed for target",
       round(n.mr_issued - n.mr_needed, 1) AS "MR vials short (-) or spare (+)",
       CASE WHEN n.ipv_issued IS NULL THEN 'No stock data' WHEN n.ipv_issued < n.ipv_needed THEN 'Not enough vials for target' ELSE 'Enough vials for target' END AS ipv_stock_status,
       CASE WHEN n.ipv_issued IS NULL THEN 'No stock data' WHEN n.ipv_issued < n.ipv_needed THEN 'Not enough vials for target' ELSE 'Enough vials for target' END AS "IPV status",
       n.ipv_received AS "IPV vials received (incl. additional)", n.ipv_returned AS "IPV vials left over (returned unopened)",
       n.ipv_issued AS "IPV vials used (issued net)", round(n.ipv_needed, 1) AS "IPV vials needed for target",
       round(n.ipv_issued - n.ipv_needed, 1) AS "IPV vials short (-) or spare (+)"
FROM microplan.public.dim_site s
LEFT JOIN (
SELECT site_code, sum(CASE WHEN product = 'MR' THEN vaccinated END) AS mr_vaccinated,
       sum(CASE WHEN product = 'IPV' THEN vaccinated END) AS ipv_vaccinated,
       sum(CASE WHEN product = 'MR' THEN vaccinated END) / nullif(sum(CASE WHEN product = 'MR' THEN target END), 0) * 100 AS mr_coverage_pct,
       sum(CASE WHEN product = 'IPV' THEN vaccinated END) / nullif(sum(CASE WHEN product = 'IPV' THEN target END), 0) * 100 AS ipv_coverage_pct
FROM (
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
JOIN microplan.public.dim_product p ON p.product_code = f.vaccine) b GROUP BY site_code) c ON c.site_code = s.site_code
LEFT JOIN n ON n.site_code = s.site_code
LEFT JOIN (
SELECT s.site_code AS k, count(*) AS children, sum(c.zero_dose) AS zero_dose_children,
       100.0 * sum(c.zero_dose) / count(*) AS zero_dose_pct
FROM hcm.default."field-child-v1" c JOIN microplan.public.dim_site s ON s.site_code = c.site_code GROUP BY 1) z ON z.k = s.site_code

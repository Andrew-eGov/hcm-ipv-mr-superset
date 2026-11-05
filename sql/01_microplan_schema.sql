-- Microplan reference data (rebuilt on every load)
DROP TABLE IF EXISTS dim_district, dim_district_polygon, dim_region, dim_facility,
                     dim_user, dim_product, dim_campaign_day CASCADE;

CREATE TABLE dim_district (
  boundary_code text PRIMARY KEY, country text, region text, district text,
  u5_population double precision, ipv_target double precision, mr_target double precision,
  ipv_doses_required double precision, mr_doses_required double precision,
  teams_total double precision, teams_fixed double precision, teams_temp_fixed double precision, teams_mobile double precision,
  hr_total double precision, seat_lat double precision, seat_lon double precision,
  centroid_lat double precision, centroid_lon double precision, geojson text
);
CREATE TABLE dim_district_polygon (
  boundary_code text, region text, district text, part_no int, polygon text
);
CREATE TABLE dim_region (
  region text PRIMARY KEY, u5_population double precision, ipv_target double precision, mr_target double precision, geojson text
);
CREATE TABLE dim_facility (
  facility_code text PRIMARY KEY, facility_name text, facility_type text, level int,
  boundary_code text, region text, district text, capacity double precision,
  latitude double precision, longitude double precision
);
CREATE TABLE dim_user (
  user_id text PRIMARY KEY, roles text, role_group text, boundary_code text,
  region text, district text, employment_type text
);
CREATE TABLE dim_product (
  product_code text PRIMARY KEY, product_name text, kind text, unit text,
  doses_per_unit int, min_age_months int, max_age_months int, planned_wastage_pct double precision
);
CREATE TABLE dim_campaign_day (
  campaign_date date PRIMARY KEY, day_no int, planned_cum_pct double precision
);

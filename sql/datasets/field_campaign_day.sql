SELECT date_diff('day', DATE '2026-11-09', max(CAST(event_date AS date))) + 1 AS campaign_day,
       11 AS campaign_days_total, max(CAST(event_date AS date)) AS last_date
FROM hcm.default."field-site-day-v1"

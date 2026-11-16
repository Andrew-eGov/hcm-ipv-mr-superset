WITH tx AS (
  SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, json_extract_scalar(x, '$.key.fac') AS facility_code, json_extract_scalar(x, '$.key.product') AS product,
         json_extract_scalar(x, '$.key.type') AS tx_type, json_extract_scalar(x, '$.key.sid') AS sender_id, json_extract_scalar(x, '$.key.sname') AS sender_name, json_extract_scalar(x, '$.key.stype') AS sender_type,
         json_extract_scalar(x, '$.key.rid') AS receiver_id, json_extract_scalar(x, '$.key.rname') AS receiver_name, json_extract_scalar(x, '$.key.rtype') AS receiver_type,
         CAST(json_extract_scalar(x, '$.qty.value') AS double) AS quantity
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"fac":{"terms":{"field":"Data.facilityId"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"type":{"terms":{"field":"Data.transactionType"}}},{"sid":{"terms":{"field":"Data.senderId"}}},{"sname":{"terms":{"field":"Data.senderName"}}},{"stype":{"terms":{"field":"Data.senderType"}}},{"rid":{"terms":{"field":"Data.receiverId"}}},{"rname":{"terms":{"field":"Data.receiverName"}}},{"rtype":{"terms":{"field":"Data.receiverType"}}}]},"aggs":{"qty":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
), cov AS (
  SELECT json_extract_scalar(x, '$.key.code') AS boundary_code, json_extract_scalar(x, '$.key.product') AS product,
         CAST(json_extract_scalar(x, '$.doses.value') AS double) AS doses, CAST(json_extract_scalar(x, '$.doc_count') AS bigint) AS attempts
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'project-task-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"code":{"terms":{"field":"Data.boundaryHierarchyCode.district"}}},{"product":{"terms":{"field":"Data.productCode"}}}]},"aggs":{"doses":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
),
issued AS (
  SELECT f.boundary_code, tx.product,
    sum(CASE WHEN tx_type = 'DISPATCHED' AND receiver_type = 'TEAM' THEN quantity
             WHEN tx_type = 'RETURNED' AND sender_type = 'TEAM' THEN -quantity ELSE 0 END) AS vials_used
  FROM tx JOIN microplan.public.dim_facility f ON f.facility_code = tx.facility_code
  WHERE tx.product IN ('MR', 'IPV') GROUP BY 1, 2
)
SELECT d.region, d.district, d.boundary_code, i.product, CASE i.product WHEN 'MR' THEN 'Measles-Rubella (MR)' WHEN 'IPV' THEN 'fIPV' ELSE i.product END AS product_label,
       i.vials_used, i.vials_used * pr.doses_per_unit AS doses_opened, coalesce(c.doses, 0) AS doses_administered,
       i.vials_used * pr.doses_per_unit - coalesce(c.doses, 0) AS doses_wasted,
       pr.planned_wastage_pct
FROM issued i JOIN microplan.public.dim_district d ON d.boundary_code = i.boundary_code
JOIN microplan.public.dim_product pr ON pr.product_code = i.product
LEFT JOIN cov c ON c.boundary_code = i.boundary_code AND c.product = i.product

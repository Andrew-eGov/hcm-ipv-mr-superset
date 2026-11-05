WITH tx AS (
  SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, json_extract_scalar(x, '$.key.fac') AS facility_code, json_extract_scalar(x, '$.key.product') AS product,
         json_extract_scalar(x, '$.key.type') AS tx_type, json_extract_scalar(x, '$.key.sid') AS sender_id, json_extract_scalar(x, '$.key.sname') AS sender_name, json_extract_scalar(x, '$.key.stype') AS sender_type,
         json_extract_scalar(x, '$.key.rid') AS receiver_id, json_extract_scalar(x, '$.key.rname') AS receiver_name, json_extract_scalar(x, '$.key.rtype') AS receiver_type,
         CAST(json_extract_scalar(x, '$.qty.value') AS double) AS quantity
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"fac":{"terms":{"field":"Data.facilityId"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"type":{"terms":{"field":"Data.transactionType"}}},{"sid":{"terms":{"field":"Data.senderId"}}},{"sname":{"terms":{"field":"Data.senderName"}}},{"stype":{"terms":{"field":"Data.senderType"}}},{"rid":{"terms":{"field":"Data.receiverId"}}},{"rname":{"terms":{"field":"Data.receiverName"}}},{"rtype":{"terms":{"field":"Data.receiverType"}}}]},"aggs":{"qty":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
)
SELECT tx.product, pr.product_name AS product_label,
       CASE WHEN s.level = 1 THEN '1 National store' WHEN s.level = 2 THEN '2 ' || s.region || ' (region)'
            ELSE '3 ' || s.district || ' (district)' END AS source,
       CASE WHEN tx.receiver_type = 'TEAM' THEN '4 Vaccination teams'
            WHEN r.level = 2 THEN '2 ' || r.region || ' (region)' ELSE '3 ' || r.district || ' (district)' END AS target,
       coalesce(r.region, s.region) AS region, coalesce(r.district, s.district) AS district,
       tx.quantity, tx.quantity * pr.doses_per_unit AS doses
FROM tx JOIN microplan.public.dim_facility s ON s.facility_code = tx.sender_id
LEFT JOIN microplan.public.dim_facility r ON r.facility_code = tx.receiver_id
JOIN microplan.public.dim_product pr ON pr.product_code = tx.product
WHERE tx.tx_type = 'DISPATCHED'

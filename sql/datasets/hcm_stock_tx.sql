WITH tx AS (
  SELECT CAST(json_extract_scalar(x, '$.key.day') AS date) AS event_date, json_extract_scalar(x, '$.key.fac') AS facility_code, json_extract_scalar(x, '$.key.product') AS product,
         json_extract_scalar(x, '$.key.type') AS tx_type, json_extract_scalar(x, '$.key.sid') AS sender_id, json_extract_scalar(x, '$.key.sname') AS sender_name, json_extract_scalar(x, '$.key.stype') AS sender_type,
         json_extract_scalar(x, '$.key.rid') AS receiver_id, json_extract_scalar(x, '$.key.rname') AS receiver_name, json_extract_scalar(x, '$.key.rtype') AS receiver_type,
         CAST(json_extract_scalar(x, '$.qty.value') AS double) AS quantity
  FROM (SELECT x FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"day":{"date_histogram":{"field":"Data.eventTime","calendar_interval":"day","format":"yyyy-MM-dd"}}},{"fac":{"terms":{"field":"Data.facilityId"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"type":{"terms":{"field":"Data.transactionType"}}},{"sid":{"terms":{"field":"Data.senderId"}}},{"sname":{"terms":{"field":"Data.senderName"}}},{"stype":{"terms":{"field":"Data.senderType"}}},{"rid":{"terms":{"field":"Data.receiverId"}}},{"rname":{"terms":{"field":"Data.receiverName"}}},{"rtype":{"terms":{"field":"Data.receiverType"}}}]},"aggs":{"qty":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x))
)
SELECT tx.event_date, f.region, f.district, f.boundary_code, f.facility_code, f.facility_name,
       f.facility_type, tx.product, pr.product_name AS product_label, pr.unit, tx.tx_type,
       tx.sender_name, tx.sender_type, tx.receiver_name, tx.receiver_type,
       tx.quantity, tx.quantity * pr.doses_per_unit AS doses
FROM tx JOIN microplan.public.dim_facility f ON f.facility_code = tx.facility_code
JOIN microplan.public.dim_product pr ON pr.product_code = tx.product

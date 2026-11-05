WITH b AS (SELECT x FROM TABLE(hcm.system.raw_query('default', 'stock-index-v1', '{"size":0,"aggs":{"c":{"composite":{"size":65000,"sources":[{"wb":{"terms":{"field":"Data.waybillNumber"}}},{"product":{"terms":{"field":"Data.productCode"}}},{"type":{"terms":{"field":"Data.transactionType"}}},{"sname":{"terms":{"field":"Data.senderName"}}},{"rid":{"terms":{"field":"Data.receiverId"}}},{"rname":{"terms":{"field":"Data.receiverName"}}}]},"aggs":{"qty":{"sum":{"field":"Data.quantity"}}}}}}')) CROSS JOIN UNNEST(CAST(json_extract(result, '$.aggregations.c.buckets') AS array(json))) AS t(x)),
w AS (
  SELECT json_extract_scalar(x, '$.key.wb') AS waybill, json_extract_scalar(x, '$.key.product') AS product, max(json_extract_scalar(x, '$.key.sname')) AS sender_name,
         max(json_extract_scalar(x, '$.key.rname')) AS receiver_name, max(json_extract_scalar(x, '$.key.rid')) AS receiver_id,
         sum(CASE WHEN json_extract_scalar(x, '$.key.type') = 'DISPATCHED' THEN CAST(json_extract_scalar(x, '$.qty.value') AS double) ELSE 0 END) AS sent,
         sum(CASE WHEN json_extract_scalar(x, '$.key.type') = 'RECEIVED' THEN CAST(json_extract_scalar(x, '$.qty.value') AS double) ELSE 0 END) AS received
  FROM b GROUP BY 1, 2
)
SELECT f.region, f.district, w.waybill, w.product, pr.product_name AS product_label, w.sender_name,
       w.receiver_name AS receiving_facility, f.facility_type, w.sent, w.received, w.sent - w.received AS discrepancy
FROM w JOIN microplan.public.dim_facility f ON f.facility_code = w.receiver_id
JOIN microplan.public.dim_product pr ON pr.product_code = w.product

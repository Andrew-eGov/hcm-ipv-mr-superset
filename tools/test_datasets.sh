#!/bin/bash
# Run each dataset SQL through Trino: prints rows, seconds, or the error.
cd "$(dirname "$0")/.."
for f in ${@:-sql/datasets/*.sql}; do
  n=$(basename $f .sql)
  docker compose cp "$f" trino:/tmp/ds.sql >/dev/null 2>&1
  printf 'SELECT count(*) FROM (\n%s\n);\n' "$(cat $f)" > /tmp/ds_count.sql
  docker compose cp /tmp/ds_count.sql trino:/tmp/ds_count.sql >/dev/null 2>&1
  s=$(date +%s.%N 2>/dev/null || python3 -c 'import time;print(time.time())')
  out=$(docker compose exec -T trino trino --file /tmp/ds_count.sql 2>&1 | tail -1)
  e=$(python3 -c "import time;print(round(time.time()-$s,1))")
  printf '%-28s %8s  %ss\n' "$n" "${out:0:140}" "$e"
done

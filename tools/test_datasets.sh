#!/usr/bin/env bash
# Run every dataset in sql/datasets through Trino and print row count + time.
cd "$(dirname "$0")/.." || exit 1
for f in sql/datasets/*.sql; do
  start=$(date +%s.%N 2>/dev/null || date +%s)
  out=$(docker compose exec -T trino trino --output-format CSV --execute "SELECT count(*) FROM ($(cat "$f")) t" 2>&1 | tail -1)
  printf '%-28s %s\n' "$(basename "$f" .sql)" "$out"
done

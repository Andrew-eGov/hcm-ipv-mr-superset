#!/usr/bin/env bash
# One-command local setup for the HCM IPV + MR dashboard.
#
#   ./setup.sh                        # full stack, loads the Zambezi field database into Elasticsearch
#   ./setup.sh --no-field-data        # skip the workbook (real HCM ES configured in trino/catalog/hcm.properties)
#   MICROPLAN_XLSX=/path/to/microplan.xlsx FIELD_XLSX=/path/to/field-database.xlsx ./setup.sh
#
# Needs: Docker (VM with >= 8 GB RAM), Python 3.9+, curl. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

FIELD=1
[[ "${1:-}" == "--no-field-data" ]] && FIELD=0
export MICROPLAN_XLSX="${MICROPLAN_XLSX:-$(cd .. && pwd)/Copy of Namibia_IPV_MR_Microplan.xlsx}"
export FIELD_XLSX="${FIELD_XLSX:-$(cd .. && pwd)/Zambezi_region_MR_IPV_child_and_stock_database_VAA_updated.xlsx}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

step "Checking prerequisites"
command -v docker >/dev/null || fail "Docker is not installed (https://docs.docker.com/get-docker/)"
docker info >/dev/null 2>&1 || fail "Docker is not running - start Docker Desktop and re-run"
command -v python3 >/dev/null || fail "python3 is not installed"
[[ -f "$MICROPLAN_XLSX" ]] || fail "Microplan workbook not found at: $MICROPLAN_XLSX
  Ask the project owner for it (it is not in git - it contains the user list),
  then put it next to this folder or run: MICROPLAN_XLSX=/path/to/file.xlsx ./setup.sh"
(( ! FIELD )) || [[ -f "$FIELD_XLSX" ]] || fail "Field database workbook not found at: $FIELD_XLSX
  Ask the project owner for it (it is not in git - it is field data),
  then put it next to this folder or run: FIELD_XLSX=/path/to/file.xlsx ./setup.sh"
mem=$(docker info --format '{{.MemTotal}}')
(( mem > 7000000000 )) || echo "WARNING: Docker has $((mem / 1000000000)) GB RAM; 8 GB is recommended (Docker Desktop > Settings > Resources)."

step "Creating .env (Superset secret key)"
if [[ -f .env ]]; then
  echo "  .env exists - kept"
elif docker volume inspect "$(basename "$PWD")_pgdata" >/dev/null 2>&1; then
  # Existing install: its metadata is encrypted with the old default key - a new key would stop Superset starting.
  echo "SUPERSET_SECRET_KEY=change-me-hcm-namibia-local-only" > .env
  echo "  existing install found - kept its current key. To rotate it later, see 'superset re-encrypt-secrets'."
else
  echo "SUPERSET_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" > .env
  echo "  wrote .env with a new random key"
fi

step "Python tools (tools/.venv)"
[[ -d tools/.venv ]] || python3 -m venv tools/.venv
tools/.venv/bin/pip -q install --disable-pip-version-check -r tools/requirements.txt

step "Starting containers (first run downloads ~3 GB of images)"
docker compose up -d --build

step "Waiting for Trino and Superset"
for i in $(seq 1 90); do
  docker compose exec -T trino trino --execute 'select 1' >/dev/null 2>&1 && break
  sleep 4; [[ $i == 90 ]] && fail "Trino did not start - check: docker compose logs trino"
done
for i in $(seq 1 90); do
  curl -sf localhost:8088/health >/dev/null && break
  sleep 4; [[ $i == 90 ]] && fail "Superset did not start - check: docker compose logs superset"
done

step "District shapes + microplan -> Postgres"
tools/.venv/bin/python -I tools/build_boundaries.py
tools/.venv/bin/python -I tools/load_microplan.py

if (( FIELD )); then
  step "Field database (Zambezi child and stock workbook) -> Elasticsearch, sites -> Postgres"
  tools/.venv/bin/python -I tools/load_field_data.py
  # Coverage-only regional child databases (Oshana, Khomas), when present next to the repo
  regional=()
  for r in Oshana Khomas; do f="$(cd .. && pwd)/${r}_region_MR_IPV_child_database.xlsx"; [[ -f "$f" ]] && regional+=("$f"); done
  if (( ${#regional[@]} )); then
    step "Regional child databases (coverage only) -> Elasticsearch"
    tools/.venv/bin/python -I tools/load_regional.py --load "${regional[@]}" | tail -1
  fi
  # Manually reported records (data/manual_records.csv), coverage only
  tools/.venv/bin/python -I tools/load_manual.py
else
  step "Sites -> Postgres"
  tools/.venv/bin/python -I tools/load_field_data.py --sites-only
fi

step "Datasets, charts and dashboard -> Superset"
tools/.venv/bin/python -I tools/datasets.py
tools/.venv/bin/python -I tools/build_superset.py 2>&1 | grep -v -i warn | tail -2

printf '\n\033[1;32mDone.\033[0m Open http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/  (login admin / admin - change it before sharing the server)\n'

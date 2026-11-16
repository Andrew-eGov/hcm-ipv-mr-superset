#!/usr/bin/env bash
# One-command local setup for the HCM IPV + MR dashboard.
#
#   ./setup.sh                        # full stack with synthetic data
#   ./setup.sh --no-mock              # skip mock data (real HCM ES configured in trino/catalog/hcm.properties)
#   MICROPLAN_XLSX=/path/to/microplan.xlsx ./setup.sh
#
# Needs: Docker (VM with >= 8 GB RAM), Python 3.9+, curl. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

MOCK=1
[[ "${1:-}" == "--no-mock" ]] && MOCK=0
export MICROPLAN_XLSX="${MICROPLAN_XLSX:-$(cd .. && pwd)/Copy of Namibia_IPV_MR_Microplan.xlsx}"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

step "Checking prerequisites"
command -v docker >/dev/null || fail "Docker is not installed (https://docs.docker.com/get-docker/)"
docker info >/dev/null 2>&1 || fail "Docker is not running - start Docker Desktop and re-run"
command -v python3 >/dev/null || fail "python3 is not installed"
[[ -f "$MICROPLAN_XLSX" ]] || fail "Microplan workbook not found at: $MICROPLAN_XLSX
  Ask the project owner for it (it is not in git - it contains the user list),
  then put it next to this folder or run: MICROPLAN_XLSX=/path/to/file.xlsx ./setup.sh"
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

if (( MOCK )); then
  step "Synthetic HCM data -> Elasticsearch (~2 min)"
  tools/.venv/bin/python -I tools/generate_mock.py 2>/dev/null | tail -9
fi

step "Datasets, charts and dashboard -> Superset"
tools/.venv/bin/python -I tools/hcm_datasets.py
tools/.venv/bin/python -I tools/build_superset.py 2>&1 | grep -v -i warn | tail -2

printf '\n\033[1;32mDone.\033[0m Open http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/  (login admin / admin - change it before sharing the server)\n'

# HCM IPV + MR Campaign Dashboard (Superset)

This is a live Superset 6.1 dashboard for the Namibia integrated campaign, `NAM-09-01-IPV-MR_NID` (single round, 9–19 Nov 2026, delivering measles-rubella (MR) and fractional IPV (fIPV)).

**Open:** http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/ (local login `admin` / `admin`)

**Static review snapshot:** https://hcm-ipv-mr-review.vercel.app. This is a standalone page (`static/`) with the same tabs, filters and maps. Its data is a frozen export of the mock data, so it is not live. To refresh it, run `tools/export_static.py`, then `npx vercel deploy --prod` from `static/`.

## Architecture

```
HCM Elasticsearch ──► Trino (elasticsearch connector, raw_query) ──┐
  project-task / individual / household /                          ├─► Superset 6.1 (28+ virtual datasets, 91 charts)
  stock / service-task / pgr / downsync                            │      60 s cache, 5 min auto-refresh
Postgres "microplan" ──► Trino (postgresql connector) ─────────────┘
  targets, users (roles only), stores, district shapes
```

* **Real time with no ETL.** Each chart's aggregation runs inside Elasticsearch: Trino's `raw_query` passes ES composite, terms, cardinality and geotile aggregations straight through. A plain Trino scan of 600k documents takes about 17 s; the pushed-down aggregation takes about 0.2 s.
* **Joins happen in Trino.** ES results are joined to the microplan tables (targets, users, stores, polygons) at query time.
* **Every tab has a map:**
  * district choropleths (deck.gl Polygon)
  * clustered event layers (deck.gl Screen Grid over ES geotile centroids), which re-aggregate at every zoom level
  * point layers for missed children, GPS issues, checklists and complaints
  * store status and stock-movement arcs

## Tabs

| Tab | Contents |
|---|---|
| Overview | Frontline sync strip; MR and fIPV coverage gauges; doses administered; % of children 9–59 m who got both vaccines; % vs plan; wastage; stores at risk; complaints; downsync; data-quality rate; coverage map; event clusters; coverage by region; planned vs actual |
| Coverage | Coverage by district and vaccine; 3 choropleths (MR, fIPV, vs plan); event clusters; household heatmap; planned vs actual; daily doses by delivery mode; age groups; delivery-mode split; missed opportunities by reason and on a map; co-administration by district; gender; household outcomes; summary table |
| Inventory | Warehouse sync strip; vials and syringes in hand; receipt discrepancy; days of stock; wastage vs 5%; store status map; stock-flow arcs; wastage and days-of-stock choropleths; Sankey flow; issued vs returned; discrepancy report; stock position table |
| Data Quality | Downsync strip; 6 data-quality counters (no GPS, accuracy > 100 m, outside the assigned district, duplicates, incomplete records, off-hours); district table; data-quality choropleth; low-accuracy point map; users with more than 120 doses a day; teams with fewer than 20 doses a day; sync and downsync rates by district |
| Supervision | Supervisor sync strip; checklist completion at team, district, regional and national level; checklist findings; daily submissions; checklist location map; completion choropleth; frontline sync by district |
| Complaints | Totals; resolution rate and hours; complaints by type and status; daily trend; location map; complaints per 10k doses by district; district table |

**Filters:** Region → District (cascading), Vaccine, Delivery mode (fixed post / house to house / transit post) and Campaign date. Each filter is scoped only to the charts whose dataset has that column. Coverage figures and maps are cumulative to date, so the date filter applies only to the daily charts.

## Files

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Elasticsearch 8.19, Postgres 16, Redis, Trino 484, Superset 6.1 |
| `trino/catalog/hcm.properties` | **Point this at the real HCM ES cluster** (host, port, auth) |
| `tools/build_boundaries.py` | Builds approximate district polygons (see Assumptions) → `data/districts.geojson` |
| `tools/load_microplan.py` | Loads the microplan `.xlsx` and shapes into Postgres |
| `tools/generate_mock.py` | Mock HCM documents (days 1–6), including deliberate data-quality noise |
| `tools/hcm_datasets.py` | All dataset SQL. **Index and field names are defined in one place** (`IDX`, `F`) |
| `tools/build_superset.py` | Idempotent build of the database connection, datasets, charts and dashboard through the REST API |
| `tools/test_datasets.sh` | Runs every dataset through Trino and reports row counts and timing |

## Rebuild from scratch

Requires Docker (8 GB RAM for the VM) and Python 3.9 or later. The microplan workbook is **not in this repo**, because it contains the user list. Put it next to the repo folder, or set `MICROPLAN_XLSX=/path/to/microplan.xlsx`.

```bash
cp .env.example .env                                   # set SUPERSET_SECRET_KEY
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/requirements.txt
docker compose up -d --build
tools/.venv/bin/python -I tools/build_boundaries.py
tools/.venv/bin/python -I tools/load_microplan.py
tools/.venv/bin/python -I tools/generate_mock.py      # skip when connected to real HCM ES
tools/.venv/bin/python -I tools/build_superset.py
```

## Going live on real HCM data (plugging in Elasticsearch)

1. Edit `trino/catalog/hcm.properties`: set the host and port, and uncomment the TLS and auth lines if the cluster is secured. Keep real credentials out of git: edit the file locally and don't commit it, or use `${ENV:VAR}` substitution. Then run `docker compose restart trino`.
   To check the connection:
   `docker compose exec trino trino --execute "SHOW TABLES FROM hcm.default"`
   The real HCM indexes should be listed.
2. Compare the real index and field names with `IDX` and `F(...)` in `tools/hcm_datasets.py`. Fields the mock assumes:
   * `Data.productCode`, `administrationStatus`, `reasonNotAdministered`, `deliveryMode`, `teamId`, `teamType`
   * `individualId`, `householdId`, `ageInMonths`
   * `geoPoint`, `latitude`, `longitude`, `locationAccuracy`
   * `boundaryHierarchyCode.district`, `eventTime`, `createdBy`
   * For stock: `transactionType`, `senderId`, `receiverId`, `waybillNumber`, `quantity`
3. Run `tools/hcm_datasets.py` to regenerate `sql/datasets/*.sql`, then `tools/test_datasets.sh`. Every dataset should return rows in a few seconds.
4. Re-run `tools/build_superset.py`. Skip `generate_mock.py`, and remove the bundled `elasticsearch` service if you don't need it.

## Assumptions to confirm

* **District shapes are approximate.** Namibia's 36 health districts have no public shapefile. Each region (geoBoundaries / Natural Earth ADM1) is split into Voronoi cells around the district seat towns, which were geocoded with OSM Nominatim. Kavango East/West and the Andara strip are derived the same way. Replace `data/districts.geojson` with official shapes when available.
* **Eligibility (WHO):** fIPV 4–59 months and MR 9 months to under 10 years, matching the microplan targets (95% of U5 and U10). Planned wastage is 5% for both vaccines, per your instruction. The microplan sheet itself uses 10% for MR doses.
* **Vial sizes:** MR 10 doses, fIPV 25 fractional doses (5-dose vial at 0.1 mL). Both are set in the `dim_product` table.
* **Team types map to delivery modes:** fixed health-facility team → Fixed post, mobile/outreach → House to house, temporary fixed → Transit post.
* **Store locations and warehouse users are mocked.** Stores are placed at the district seat towns. Warehouse sync is measured as stores with at least one transaction, because the user list has no warehouse managers.
* **Map base tiles use OpenStreetMap,** which is fine for a pilot. For production, use a tile provider (MapTiler, Stadia or Mapbox) and change `TILE` in `build_superset.py`.
* **Row-level security** is not configured yet (open by design for now).

## Data credits

* Region boundaries: [geoBoundaries](https://www.geoboundaries.org) NAM ADM1 (CC BY 4.0, Natural Earth source)
* District seat towns geocoded with [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org) (© OpenStreetMap contributors, ODbL)
* All HCM records in Elasticsearch are **synthetic** (`tools/generate_mock.py`)

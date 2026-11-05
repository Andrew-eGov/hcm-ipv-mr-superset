# CLAUDE.md: HCM IPV + MR campaign dashboard

Superset 6.1 dashboard for the DIGIT HCM **Namibia IPV + MR integrated campaign** (`NAM-09-01-IPV-MR_NID`). It has a single round, 9–19 Nov 2026, delivering measles-rubella (MR) and fractional IPV (fIPV), and covers 14 regions and 36 health districts. Setup, rebuild commands and the go-live steps are in `README.md`. This file holds what the code doesn't tell you: why it's built this way, the traps, and where the work stopped.

## Where the work stands

- **Done:** the live stack (Superset → Trino → Elasticsearch + Postgres) with 6 tabs, 91 charts, maps on every tab and native filters. It runs on **synthetic** HCM data covering days 1–6.
- **Done:** the static review site at https://hcm-ipv-mr-review.vercel.app (`static/`) with Share and Download buttons. It shows a frozen snapshot, not live data.
- **Done:** `docs/HCM_Elastic_Plug-in_Sheet.xlsx`, the KPI-by-KPI mapping workbook used to connect the real HCM Elasticsearch.
- **Next:**
  1. Fill the plug-in workbook against the real HCM ES.
  2. Apply its mappings to `tools/hcm_datasets.py`.
  3. Load real ids into the microplan tables.
  4. Rebuild and spot-check against HCM reports.
- **Not started (deferred by the product owner):** row-level security per region or district, AEFI tracking, production hosting (an 8 GB VM with HTTPS).

## How the pieces fit

- `tools/hcm_datasets.py` is the **single source of truth** for every Superset dataset. Real index names go in `IDX`, field paths in `F()`, and value codes inline. Change mappings there, never in Superset's UI, because `tools/build_superset.py` deletes and recreates every dataset, chart and the dashboard on each run.
- Aggregations run **inside Elasticsearch**: Trino's `raw_query` table function sends ES composite, terms, cardinality and geotile aggregations to ES, and the JSON results are unnested in SQL. Plain Trino scans of HCM indexes take 17 s or more per 600k documents, so keep new KPIs on `raw_query`.
- Trino then joins the ES results with the `microplan` Postgres tables (`dim_district`, `dim_user`, `dim_facility`, `dim_product`, `dim_campaign_day`, `dim_district_polygon`). Every dataset exposes `region`, `district` and `boundary_code` (plus `product`, `delivery_mode` and `event_date` where they apply). The native filters are scoped by those column names.
- `tools/test_datasets.sh` runs every dataset through Trino. A healthy dataset returns rows in 2–6 s, most of which is CLI start-up.

## Traps already hit

- **Trino gets OOM-killed** if it has no `mem_limit`: its JVM takes 80% of the whole Docker VM. Keep the `mem_limit` lines in `docker-compose.yml`.
- **Trino drops an unused `raw_query` column and the query fails** ("Invalid number of channels"). Keep the result referenced, e.g. `JOIN o ON o.result IS NOT NULL`. Keep SQL comments out of dataset SQL, because Superset wraps the SQL in a subquery.
- **Postgres `numeric` reaches Trino as an unbounded type that can't be divided.** Microplan columns are `double precision`; keep them that way.
- **ES composite aggregations stop at 65,536 buckets.** That's why the map tiles have no day dimension and the age dataset has no delivery mode. Check bucket counts before adding a dimension.
- **Map tiles:** CARTO tiles show "API KEY REQUIRED", so the dashboard uses OSM tiles (`TILE` in `build_superset.py`). OSM's tile policy only suits a pilot.
- **Late-night mock events used to spill into the next day** and broke "days elapsed". The generator now caps off-hours times at 23:30.
- **Combined district-map datasets were slow** under dashboard load, so choropleths use one lighter `hcm_map_*` dataset per topic.

## Decisions and assumptions to keep

These came from the product owner or from the microplan. Change them only after asking the product owner.

- **Architecture:** Trino over Elasticsearch, chosen over a direct ES driver and over ES → Postgres sync.
- **Eligibility:** fIPV 4–59 months, target 95% of under-5s. MR 9 months to under 10 years, target all under-10s. These follow WHO guidance and the microplan.
- **Planned wastage: 5% for both vaccines** (owner's instruction). The microplan sheet itself uses 10% for MR.
- **Vial sizes:** MR 10 doses; fIPV 25 fractional doses per vial (assumed). Both live in `dim_product`.
- **Delivery modes:** fixed health-facility team → Fixed post; mobile/outreach → House to house; temporary fixed → Transit post (the owner wrote "transfer post").
- **District shapes are approximate.** Each geoBoundaries region is split into Voronoi cells around the district seat towns. Official shapes, when they exist, replace `data/districts.geojson`.
- **Mock-only items:** store coordinates (placed at district seat towns) and user ids (`NAM-U-xxxxx`). Warehouse sync means "stores with at least one stock transaction", because the user list has no warehouse managers.

## Data handling

- The microplan workbook (`../Copy of Namibia_IPV_MR_Microplan.xlsx`, or the path in `MICROPLAN_XLSX`) contains a user list with personal and payment columns. It stays out of git (`.gitignore` blocks `*.xlsx`). Load only roles and boundaries from it, as `tools/load_microplan.py` does.
- Keep ES credentials only in `trino/catalog/hcm.properties` on the server, uncommitted. The repo and the Vercel site are **public**.
- All field records in Elasticsearch, `static/data.json` and the dashboard are synthetic, generated by `tools/generate_mock.py`. Say so whenever you share figures.

## Working agreements

- After changing datasets or charts, rebuild with `tools/build_superset.py`, then open every tab at http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/ (local login `admin`/`admin`) and confirm each chart shows data.
- After changing `static/`, re-export with `tools/export_static.py` if the data changed. Check the page locally, then deploy from a copy of `static/` with `npx vercel@65.11.0 deploy --prod`.
- Regenerate the plug-in workbook with `tools/build_plug_sheet.py` whenever a dataset gains or drops an ES field, so the workbook and the code list the same fields.
- Commit messages describe the change and why. The GitHub remote is `Andrew-eGov/hcm-ipv-mr-superset`.

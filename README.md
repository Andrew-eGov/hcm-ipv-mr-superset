# HCM IPV + MR Campaign Dashboard (Superset)

This is a live Superset 6.1 dashboard for the Namibia integrated campaign, `NAM-09-01-IPV-MR_NID` (single round, 9–19 Nov 2026, delivering measles-rubella (MR) and IPV). It currently shows the **Zambezi region MR/IPV child and stock database** (field data for 10–11 Nov: Katima Mulilo, Bukalo and Sangwali districts, 23 sites), loaded into Elasticsearch.

**Open:** http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/ (local login `admin` / `admin`)

**Static review page:** `static/` is a standalone page with the same tabs, filters and maps, built from a frozen export (`tools/export_static.py` → `static/data.json`, aggregates only). `static/data.json` is git-ignored because it holds field data. The public copy at https://hcm-ipv-mr-review.vercel.app is only updated on the project owner's say-so.

## Architecture

```
Field database (.xlsx) ──► tools/load_field_data.py ──► Elasticsearch
                                                          field-child-v1     (one doc per child)
                                                          field-site-day-v1  (one doc per site × date × vaccine)
Elasticsearch ──► Trino (elasticsearch connector) ──┐
Postgres "microplan" ──► Trino (postgresql) ────────┴──► Superset 6.1 (13 virtual datasets, 75 charts)
  dim_site, districts, region/district shapes, products       60 s cache, 5 min auto-refresh
```

* **Real time with no ETL inside Superset.** Charts query ES through Trino; the field indexes are small, so plain scans return in about a second.
* **Joins happen in Trino.** ES rows join to `dim_site` (site → district → region, facility type, coordinates) and `dim_product` (doses per vial, allowed wastage).
* **Maps show Namibia only.** Superset maps use a transparent basemap, so only Namibia's region and district shapes are drawn; the review page masks everything outside Namibia. Coverage maps share one red-amber-green scale with a legend (<50% red, 70–80% amber, 90%+ green).

## Tabs

The dashboard has four tabs. Supervision and Complaints are hidden for this release. MR and IPV are always reported separately; nothing on the dashboard blends the two.

| Tab | Contents |
|---|---|
| Overview | Per vaccine: children vaccinated, target, coverage of target, wastage, vials opened, sites reporting; zero-dose children and AEFI cases (synthetic); pie of vaccinated vs remaining to target; coverage by region and by district; coverage maps by district; health-facility map by type |
| Coverage | Zero-dose children and AEFI cases (synthetic); vaccination-site map coloured by coverage with MR / IPV delivered on hover (numbered clusters on the review page); zero-dose children by district and site; coverage maps by region; coverage by region, district and site; children vaccinated by age group (labels as in the source); gender distribution per vaccine; planned vs actual (cumulative); children per day; children by vaccines received; site summary table |
| Inventory | Stores and sites with a stock entry; vials in hand in the district store; campaign day; vials received, additional, opened, returned unopened, issued (net) and wastage per vaccine; days of stock by site with a campaign-days-remaining line; wastage by district and by site with the 5% allowed line; cumulative vials issued vs needed by site; full-width Sankey (national > regional > district store > site > opened / returned); stock maps; stock table by site and day |
| Data Quality | App sync only (synthetic until HCM is connected): vaccinators downsynced and frontline workers synced (total, synced at least once, rate); frontline sync rate and downsync rate by district |

**Planned figures are scoped to the data.** Target is the sum of the daily site targets for the sites and days that uploaded data, so coverage is never compared with the national plan, and every filter changes numerator and denominator together.

**Filters:** Region → District → Site (cascading), Vaccine (empty = MR + IPV) and Campaign date. Each filter applies only to charts whose dataset has that column.

## Files

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Elasticsearch 8.19, Postgres 16, Redis, Trino 484, Superset 6.1 |
| `trino/catalog/hcm.properties` | **Point this at the real HCM ES cluster** (host, port, auth) |
| `tools/load_field_data.py` | Loads the field-database workbook into ES and `data/sites.csv` into `dim_site` |
| `data/sites.csv` | Sites: code, name, district, facility type, coordinates and where they came from |
| `tools/build_boundaries.py` | Builds approximate district polygons → `data/districts.geojson` |
| `tools/load_microplan.py` | Loads the microplan `.xlsx`, shapes and products into Postgres |
| `tools/datasets.py` | All dataset SQL. **Index names and fields are defined in one place** |
| `tools/build_superset.py` | Idempotent build of the connection, datasets, charts and dashboard through the REST API |
| `tools/test_datasets.sh` | Runs every dataset through Trino and reports row counts |
| `tools/export_static.py` | Exports aggregates for the review page |
| `tools/legacy/` | The earlier synthetic-data build (mock generator, HCM-shaped datasets), kept for reference |

## Rebuild from scratch

**Quickest:** run `./setup.sh`. It does everything below. New to the project? Read `START_HERE.md` first.

Requires Docker (8 GB RAM for the VM) and Python 3.9 or later. Two workbooks are **not in this repo**: the microplan (it contains the user list) and the field database (field data). Put both next to the repo folder, or set `MICROPLAN_XLSX=` and `FIELD_XLSX=`.

```bash
cp .env.example .env                                   # set SUPERSET_SECRET_KEY
python3 -m venv tools/.venv && tools/.venv/bin/pip install -r tools/requirements.txt
docker compose up -d --build
tools/.venv/bin/python -I tools/build_boundaries.py
tools/.venv/bin/python -I tools/load_microplan.py
tools/.venv/bin/python -I tools/load_field_data.py     # --sites-only when connected to real HCM ES
tools/.venv/bin/python -I tools/build_superset.py
```

## Going live on real HCM data

1. Edit `trino/catalog/hcm.properties` (host, port, TLS, auth). Keep credentials out of git. Then `docker compose restart trino` and check with
   `docker compose exec trino trino --execute "SHOW TABLES FROM hcm.default"`.
2. The dashboard reads two shapes of data: a child line list and a daily site report (per vaccine: target, children by age group, vials received / additional / opened / returned unopened). Map HCM onto them with `docs/HCM_Elastic_Plug-in_Sheet.xlsx`, then update the index names and fields in `tools/datasets.py`. If HCM has no daily site report, a small aggregation job that writes `field-site-day-v1`-shaped documents is the simplest route.
3. Add every real site to `data/sites.csv`, run `./setup.sh --no-field-data`, then `tools/test_datasets.sh`.

## Assumptions to confirm

* **MR wastage is the reported figure, 0.1%** (owner's instruction), on every card, chart and table; `MR_WASTAGE_REPORTED` in `tools/build_superset.py` and `static/index.html`. The field data alone gives about −1% for MR, because more children are recorded than doses in opened vials at 5 doses per vial.
* **IPV wastage is calculated and never shows below 0%** (owner's instruction).
* **Doses per vial: MR 5, IPV 10.** Inferred from the field data (about 5 children per opened MR vial and 10 per IPV vial). With 10-dose MR vials, MR wastage would be about 50%. Set in `dim_product` (`tools/load_microplan.py`).
* **Campaign day comes from the date** (9 Nov = day 1, 11 days). The workbook's sheets disagree: Children calls 10 Nov day 1; Agg and Stock call it day 2.
* **Vials in hand in the district store** = vials returned unopened on the latest day; the workbook has no store stock. Days of stock = that ÷ average daily vials opened (last 3 days).
* **Sankey store layers** (national, regional, district) are not in the field data; they are the sums of the site layer.
* **Facility type** comes from the site name (Health Centre / Clinic); other sites are outreach points, and Masokotwani is a school. Two sites (Homba Clinic, Nchichimani) have no coordinates in the source and none in OpenStreetMap, so they sit at their district centre.
* **Zambezi has three districts: Katima Mulilo, Bukalo and Sangwali**, taken from the workbook's Cluster column (owner's instruction; there is no separate cluster level). The microplan has only Katima Mulilo for the whole region, so `tools/load_field_data.py` replaces it with the three. Their shapes are approximate (the region split around each district's sites, `data/zambezi_districts.geojson`); the Bukalo and Sangwali boundary codes are dashboard-assigned. Microplan targets stay on Katima Mulilo, because the microplan does not split them. The synthetic sync users, all listed under Katima Mulilo in the microplan, are spread over the three districts in proportion to their number of sites.
* **App sync is synthetic.** The field database has no sync records, so `tools/load_field_data.py` writes `field-user-sync-v1` with a stable synthetic status per frontline user in the microplan (about 93% synced, about 86% of vaccinators downsynced), limited on the dashboard to districts that uploaded field data. Labelled synthetic on both dashboards.
* **Zero-dose and AEFI are synthetic.** The field database records neither, so `tools/load_field_data.py` adds stable synthetic flags per child (zero-dose about 4%, higher for younger children; AEFI about 1.2 per 1,000 doses), flagged `zero_dose_synthetic` / `aefi_synthetic`. They are not labelled synthetic on the dashboards (owner's instruction); real `Zero_Dose` / `AEFI` columns in the workbook replace them automatically.
* **Superset maps can't print numbers on points** or size them inside multi-layer maps, so the Superset site map shows the numbers on hover; the review page draws numbered clusters.
* **Gender is synthetic.** The field database has no gender column, so `tools/load_field_data.py` gives each child a stable synthetic gender (about 50.7% male) and flags it `gender_synthetic = 1`. The gender pies are not labelled synthetic on the dashboards. A real `Gender` column in the workbook replaces it automatically.
* **District shapes are approximate** (Voronoi cells around district seats inside geoBoundaries regions). Replace `data/districts.geojson` with official shapes when available.
* **Row-level security** is not configured yet (open by design for now).

## Data credits

* Region boundaries: [geoBoundaries](https://www.geoboundaries.org) NAM ADM1 (CC BY 4.0, Natural Earth source)
* District seats and site locations geocoded with [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org) (© OpenStreetMap contributors, ODbL)
* Field data: Zambezi region MR/IPV child and stock database (10–11 Nov 2026), supplied by the project owner; not in git.

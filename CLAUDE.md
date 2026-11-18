# CLAUDE.md: HCM IPV + MR campaign dashboard

Superset 6.1 dashboard for the DIGIT HCM **Namibia IPV + MR integrated campaign** (`NAM-09-01-IPV-MR_NID`). It has a single round, 9–19 Nov 2026 (11 days), delivering measles-rubella (MR) and IPV. Setup, rebuild commands and the go-live steps are in `README.md`. This file holds what the code doesn't tell you: why it's built this way, the traps, and where the work stopped.

## Where the work stands

- **Done:** the live stack (Superset → Trino → Elasticsearch + Postgres) with 4 tabs (Overview, Coverage, Inventory, Data Quality), 69 charts and native filters, restructured per the 16 Nov 2026 review. It runs on the **Zambezi region field database** (real field data for 10–11 Nov, district Katima, 3 clusters, 23 facilities), not synthetic data.
- **Done:** `static/`, a standalone review page with the same tabs. `static/data.json` (aggregates only) is git-ignored.
- **Done:** `docs/HCM_Elastic_Plug-in_Sheet.xlsx`, rewritten for the two field indexes.
- **Next:**
  1. Product-owner answers to the review's open questions: doses per vial, pie slices, facility types, campaign length (see "Decisions" below for what was assumed).
  2. Map HCM onto the two field indexes with the plug-in workbook, then update `tools/datasets.py`.
  3. Add every real site to `data/sites.csv`.
- **Hidden / not started:** Supervision and Complaints tabs (hidden by the review; the synthetic version is in `tools/legacy/`), zero-dose and AEFI (no source in the field data), row-level security, production hosting.

## Tally data (prepared, not loaded)

`../Namibia_MR-IPV_Tally_Ingestion.xlsx` (`TALLY_XLSX`) holds MoHSS paper-tally counts for two more sites: Ou-Nick Clinic (Oshana, Oshakati, 9-12 Nov, day 4 provisional) and Ruacana border post (Omusati, Outapi, 13 Nov). The owner asked to prepare it for **Overview and Coverage only** (no inventory or sync data) and **not ingest yet**.

- Ready: `tools/load_tally.py` (dry run by default; `--load` is deliberately blocked) and `data/tally_sites.csv` (both sites, approximate town coordinates, not in OSM).
- Before loading, the owner must choose a target rule (daily targets are blank on every sheet): `none` (counts only, left out of coverage %) or `per-team` (district microplan target / teams / 11 days; gives Ou-Nick MR 136 and IPV 66 a day).
- To load, also: append tally site-day docs after `load_field_data.py` (which recreates `field-site-day-v1`), add `data/tally_sites.csv` to `dim_site`, sum coverage targets only where a target exists, union tally zero-dose / AEFI / co-administration counts into the cards and the "children by vaccines received" pie (the tally has no child line list or gender), and add a "Border post" facility type to the facility map.
- Data checks to raise with the owner: Ou-Nick day 4 is provisional; Ruacana's "IPV also MR" is 0 (blank on paper); zero-dose, MR refusal and MR AEFI are missing for Ou-Nick day 4 and Ruacana (left empty, not 0).

## Regional child databases (loaded, coverage only)

`../Oshana_region_MR_IPV_child_database.xlsx` and `../Khomas_region_MR_IPV_child_database.xlsx` (12-13 Nov) are loaded by `tools/load_regional.py --load` (run by `setup.sh` after `load_field_data.py`, which recreates the indexes). Owner's instruction: coverage only, targets from the microplan.

- **Targets:** the workbooks' Target cells are blank, so each site-day gets its district's per-team daily target from the microplan: district target / teams / 11 days (Oshakati MR 136, IPV 66; Windhoek MR 183, IPV 92). Small Khomas sites therefore show low coverage (MR 2.9%).
- **Scope:** sites load with `dim_site.data_scope = 'coverage'`. Inventory charts use `field_stock_site_day` (only `'full'` sites), stock maps and sync filter on `data_scope = 'full'`, vial measures are NULL without stock data, and wastage counts only site-days with vials. Keep these rules when adding regions.
- **Data handling:** 'test' site dropped (`include=no` in `data/regional_sites.csv`); IPV given to 5-10 year olds goes into the IPV 5-10 years age group; gender, zero-dose and AEFI get the same synthetic flags as Zambezi.
- **Not loaded:** the MoHSS tally workbook (`tools/load_tally.py`, still dry-run). Ou-Nick Clinic 12 Nov is in both sources; loading the tally too would double-count it.

## Manual records (loaded, coverage only)

`data/manual_records.csv` holds records reported outside the workbooks, loaded by `tools/load_manual.py` (run by `setup.sh` after the regional loader). It has one row per site x date x vaccine and the same per-team target rule and `data_scope = 'coverage'` as the regional sites. There is no child line list, so these records count in children vaccinated and coverage but not in the age, gender or status breakdowns. First record (owner, 18 Nov 2026): United Nations House outreach point, Windhoek > Katutura, 1 MR child; vaccine and date assumed (MR, 18 Nov).

## How the pieces fit

- `tools/load_field_data.py` loads the workbook into ES: `field-child-v1` (one doc per child) and `field-site-day-v1` (one doc per site × date × vaccine, merging the Agg and Stock sheets on site code + date). It also loads `data/sites.csv` into Postgres `dim_site`.
- `tools/datasets.py` is the **single source of truth** for every Superset dataset. Change SQL there, never in Superset's UI: `tools/build_superset.py` deletes and recreates every dataset, chart and the dashboard on each run.
- Every dataset exposes `region`, `district`, `cluster`, `site_name` (shown as Facility), `product` and `event_date` where they apply. The native filters are scoped by those column names.
- Coverage denominators are the **daily site targets of the sites and days that uploaded data**. Keep it that way: the review requires planned figures to be scoped to uploading areas, never the national plan.

## Traps already hit

- **Superset is not responsive.** Its page template has no viewport tag (added in `superset/Dockerfile`), and its 12-column grid shrinks every chart instead of stacking. So `build_superset.py` also builds a phone dashboard (`hcm-ipv-mr-namibia-mobile`) from the same charts: one column, KPI cards two per row, horizontal filter bar, top menu hidden by its CSS on phones. Rebuilds keep both in step.

- **Join on `Site_Code`, never on site name.** The same site has different names across sheets ("Bukalo Health Centre" vs "Bukalo HC (+ team 4)").
- **Campaign_Day in the workbook is inconsistent** (Children: 10 Nov = day 1; Agg/Stock: day 2). Day is computed from the date; the source value is stored as source_campaign_day but no chart uses it now.
- **Stock sheets end with a TOTAL row.** The loader drops rows without a Site_Code.
- **deck.gl multi-layer maps can't colour points by a column** and show no legend. `point_map()` in `build_superset.py` makes one layer per category with a fixed colour and a markdown legend beside the map (emoji dots, because dashboard markdown strips inline styles).
- **Namibia-only maps** use a transparent 1×1 PNG as the tile URL (`TILE` in `build_superset.py`). A wrong base64 PNG paints the whole map purple.
- **Handlebars charts ignore `styleTemplate`** (the CSS shows as text). Use plain `<h2>`/`<p>` in the template.
- **Trino gets OOM-killed** without `mem_limit`; keep it in `docker-compose.yml`.
- **Postgres `numeric` reaches Trino as an unbounded type that can't be divided.** Keep microplan columns `double precision`.
- **Superset's API rate-limits** (429); `api()` retries with back-off.

## Decisions and assumptions to keep

From the product owner, the 16 Nov review or the data. Change them only after asking the product owner.

- **Architecture:** Trino over Elasticsearch, chosen over a direct ES driver and over ES → Postgres sync.
- **Four tabs; MR and IPV always separate;** "fIPV" is called IPV everywhere; vaccine filter empty = "MR + IPV".
- **Doses per vial: MR 5, IPV 10** (inferred from the data: about 5 children per opened MR vial, 10 per IPV vial; open question in the review). In `dim_product`.
- **Allowed wastage 5%** for both vaccines. Wastage = (doses in opened vials − children vaccinated) ÷ doses in opened vials. **MR wastage shows the reported 0.1%** (owner's instruction; `MR_WASTAGE_REPORTED`), not the calculated figure (about −1%). IPV wastage is calculated and floored at 0%.
- **Vials needed** = target ÷ doses per vial × 1.05. **Vials issued (net)** = received + additional − returned unopened.
- **Vials in hand (district store)** = vials returned unopened on the latest day; **days of stock** = that ÷ average daily vials opened over the last 3 days.
- **Sankey store layers** (national, regional, district) are synthetic sums of the site layer, as the review allows.
- **Age-group labels as in the source:** MR 6–11 months, 12–59 months, 5–10 years; IPV 14 weeks–11 months, 12–59 months.
- **Facility type from the site name**; other sites are outreach points; Masokotwani is a school.
- **Site coordinates:** from the workbook where present, otherwise OSM Nominatim; Homba Clinic and Nchichimani are at their cluster centre (flagged).
- **Hierarchy: Region > District > Cluster > Facility** (owner's instruction, 17 Nov 2026; "site" in the data and column names is shown as "Facility"). Districts: Katima (Zambezi), Oshakati (Oshana), Windhoek (Khomas). Clusters: Zambezi's from the workbook's Cluster column (Bukalo, Katima Mulilo, Sangwali); Oshana's from its workbook (Oshakati Clinic, Oshakati Health Centre); Khomas is the Katutura cluster (owner's instruction; the workbook labels it Windhoek Central Hospital). `tools/load_field_data.py` renames the microplan's single Zambezi district "Katima Mulilo" to "Katima" (same boundary code and targets) so it is not confused with the Katima Mulilo cluster; it refuses a database still holding the old three-district split (rerun `tools/load_microplan.py`). Clusters have no shapes, so maps stay at district level; the synthetic sync users in Zambezi are spread over its three clusters by facility count.
- **Tables open sorted alphabetically by district > cluster > facility** (owner's instruction, 17 Nov); every header sorts on click. Superset uses `HIER_SORT` as the table sort metric; the review page sorts on the columns marked `s`.
- **Data Quality shows app sync only** (owner's instruction; the field-data checks such as stock balance and line list vs aggregate were removed). **Sync is synthetic**: `field-user-sync-v1`, one doc per vaccinator / registrar, flagged `synthetic = 1`, shown only for the clusters of the stock-and-sync district (Katima), by cluster. Replace with HCM sync / downsync data when connected.
- **The dashboards do not label synthetic figures** (owner's instruction, 17 Nov): zero-dose, AEFI, gender and sync are synthetic, but the cards, charts and maps no longer say so. Keep that in mind before sharing figures outside the team.
- **Zero-dose and AEFI are synthetic** (owner asked for one card each on Overview and Coverage, plus zero-dose on the Coverage map): per-child flags from `load_field_data.py`, labelled synthetic everywhere; real workbook columns `Zero_Dose` / `AEFI` take over automatically.
- **Gender is synthetic** (owner's request): stable per child id, about 50.7% male, flagged `gender_synthetic = 1` and labelled synthetic on both dashboards. A real `Gender`/`Sex` column in the workbook takes over automatically.
- **District shapes are approximate** (Voronoi cells around district seats). Official shapes, when they exist, replace `data/districts.geojson`.

## Data handling

- The microplan workbook (user list with personal and payment columns) and the field-database workbook stay **out of git** (`.gitignore` blocks `*.xlsx`). Paths: `MICROPLAN_XLSX`, `FIELD_XLSX`, default next to the repo.
- `static/data.json` holds field aggregates and is git-ignored. The public review site must not be updated with field data unless the product owner says so; no child ids or line-list rows ever go into it.
- Keep ES credentials only in `trino/catalog/hcm.properties` on the server, uncommitted. The repo is **public**.

## Working agreements

- Run `./setup.sh` (or `./setup.sh --no-field-data` once real ES is configured) for a full idempotent rebuild. `START_HERE.md` is the human-facing hand-over.
- After changing datasets or charts, rebuild with `tools/build_superset.py`, then open every tab at http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/ (local login `admin`/`admin`) and confirm each chart shows data.
- After changing `static/`, re-export with `tools/export_static.py`, check the page locally, and deploy only with the owner's approval (`npx vercel@65.11.0 deploy --prod` from a copy of `static/`).
- Regenerate the plug-in workbook with `tools/build_plug_sheet.py` whenever a dataset gains or drops a field.
- Commit messages describe the change and why. The GitHub remote is `Andrew-eGov/hcm-ipv-mr-superset`.

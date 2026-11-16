# CLAUDE.md: HCM IPV + MR campaign dashboard

Superset 6.1 dashboard for the DIGIT HCM **Namibia IPV + MR integrated campaign** (`NAM-09-01-IPV-MR_NID`). It has a single round, 9–19 Nov 2026 (11 days), delivering measles-rubella (MR) and IPV. Setup, rebuild commands and the go-live steps are in `README.md`. This file holds what the code doesn't tell you: why it's built this way, the traps, and where the work stopped.

## Where the work stands

- **Done:** the live stack (Superset → Trino → Elasticsearch + Postgres) with 4 tabs (Overview, Coverage, Inventory, Data Quality), 73 charts and native filters, restructured per the 16 Nov 2026 review. It runs on the **Zambezi region field database** (real field data for 10–11 Nov, 3 clusters, 23 sites), not synthetic data.
- **Done:** `static/`, a standalone review page with the same tabs. `static/data.json` (aggregates only) is git-ignored.
- **Done:** `docs/HCM_Elastic_Plug-in_Sheet.xlsx`, rewritten for the two field indexes.
- **Next:**
  1. Product-owner answers to the review's open questions: doses per vial, pie slices, facility types, campaign length (see "Decisions" below for what was assumed).
  2. Map HCM onto the two field indexes with the plug-in workbook, then update `tools/datasets.py`.
  3. Add every real site to `data/sites.csv`.
- **Hidden / not started:** Supervision and Complaints tabs (hidden by the review; the synthetic version is in `tools/legacy/`), zero-dose and AEFI (no source in the field data), row-level security, production hosting.

## How the pieces fit

- `tools/load_field_data.py` loads the workbook into ES: `field-child-v1` (one doc per child) and `field-site-day-v1` (one doc per site × date × vaccine, merging the Agg and Stock sheets on site code + date). It also loads `data/sites.csv` into Postgres `dim_site`.
- `tools/datasets.py` is the **single source of truth** for every Superset dataset. Change SQL there, never in Superset's UI: `tools/build_superset.py` deletes and recreates every dataset, chart and the dashboard on each run.
- Every dataset exposes `region`, `district`, `cluster`, `site_name`, `product` and `event_date` where they apply. The native filters are scoped by those column names.
- Coverage denominators are the **daily site targets of the sites and days that uploaded data**. Keep it that way: the review requires planned figures to be scoped to uploading areas, never the national plan.

## Traps already hit

- **Join on `Site_Code`, never on site name.** The same site has different names across sheets ("Bukalo Health Centre" vs "Bukalo HC (+ team 4)").
- **Campaign_Day in the workbook is inconsistent** (Children: 10 Nov = day 1; Agg/Stock: day 2). Day is computed from the date; the source value is kept only for the Data Quality check.
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
- **Allowed wastage 5%** for both vaccines. Wastage = (doses in opened vials − children vaccinated) ÷ doses in opened vials. Negative wastage means more children than doses: shown as a data check, not as on track.
- **Vials needed** = target ÷ doses per vial × 1.05. **Vials issued (net)** = received + additional − returned unopened.
- **Vials in hand (district store)** = vials returned unopened on the latest day; **days of stock** = that ÷ average daily vials opened over the last 3 days.
- **Sankey store layers** (national, regional, district) are synthetic sums of the site layer, as the review allows.
- **Age-group labels as in the source:** MR 6–11 months, 12–59 months, 5–10 years; IPV 14 weeks–11 months, 12–59 months.
- **Facility type from the site name**; other sites are outreach points; Masokotwani is a school.
- **Site coordinates:** from the workbook where present, otherwise OSM Nominatim; Homba Clinic and Nchichimani are at their cluster centre (flagged).
- **All three clusters sit in microplan district Katima Mulilo (Zambezi).**
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

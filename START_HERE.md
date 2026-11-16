# Start here: HCM IPV + MR dashboard hand-over

This package lets you pick up the Namibia IPV + MR campaign dashboard where it was left. The dashboard runs in Superset 6.1, reads Elasticsearch through Trino, and currently shows the **Zambezi region MR/IPV child and stock database** (field data, 10–11 Nov 2026).

## What's in it

| Item | What it is |
|---|---|
| `setup.sh` | One command that builds and starts the whole dashboard on your machine |
| `README.md` | Architecture, the tab-by-tab contents, assumptions, and how to connect real HCM data |
| `CLAUDE.md` | Hand-over notes: status, decisions, known traps. Claude Code reads it automatically |
| `docs/HCM_Elastic_Plug-in_Sheet.xlsx` | **Your main task:** map every KPI to the real HCM Elasticsearch fields |
| `tools/`, `sql/`, `superset/`, `trino/`, `data/`, `docker-compose.yml` | The code |

## Links

- **Code:** https://github.com/Andrew-eGov/hcm-ipv-mr-superset (public). Clone it to get updates.

## Get it running (about 15 minutes on the first run)

1. Install **Docker Desktop**, give it **8 GB RAM** (Settings → Resources), and start it. You also need **Python 3.9 or later**.
2. Get two workbooks from the project owner. Neither is in this package:
   - the **microplan** (`Copy of Namibia_IPV_MR_Microplan.xlsx`), which contains the user list;
   - the **field database** (`Zambezi_region_MR_IPV_child_and_stock_database_VAA_updated.xlsx`).

   Put both in the folder **above** this one, or set `MICROPLAN_XLSX=` and `FIELD_XLSX=` to their paths.
3. Run:
   ```bash
   ./setup.sh
   ```
4. Open http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/ and log in with `admin` / `admin`.

## Connect the real HCM Elasticsearch

1. Fill in the yellow cells of `docs/HCM_Elastic_Plug-in_Sheet.xlsx`, sheets 1–4. Sheet 5 shows which KPIs are ready. The dashboard needs two kinds of data: a child line list and a daily site report per vaccine (target, children by age group, vials received / opened / returned).
2. Follow sheet 7, the go-live checklist. In short:
   - put the ES host and login in `trino/catalog/hcm.properties`;
   - update index names and fields in `tools/datasets.py`;
   - add every site to `data/sites.csv`;
   - run `./setup.sh --no-field-data`.

Using Claude Code? Open this folder and ask, for example: *"Apply the mappings from the filled-in plug-in sheet and rebuild the dashboard."* It starts from `CLAUDE.md`.

## Rules for this project

- Keep both workbooks and ES passwords **out of git**. The repo is public.
- The figures are real field data: don't publish them (screenshots, the review site) without the project owner's go-ahead.
- Questions about targets, vial sizes or wastage assumptions go to the project owner (see "Decisions and assumptions to keep" in `CLAUDE.md`).

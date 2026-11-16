# Start here: HCM IPV + MR dashboard hand-over

This package lets you pick up the Namibia IPV + MR campaign dashboard where it was left. The dashboard runs in Superset 6.1 and reads HCM Elasticsearch through Trino.

## What's in it

| Item | What it is |
|---|---|
| `setup.sh` | One command that builds and starts the whole dashboard on your machine |
| `README.md` | Architecture, the tab-by-tab contents, and how to connect real HCM data |
| `CLAUDE.md` | Hand-over notes: status, decisions, known traps. Claude Code reads it automatically |
| `docs/HCM_Elastic_Plug-in_Sheet.xlsx` | **Your main task:** map every KPI to the real HCM Elasticsearch fields |
| `tools/`, `sql/`, `superset/`, `trino/`, `docker-compose.yml` | The code |

## Links

- **Code:** https://github.com/Andrew-eGov/hcm-ipv-mr-superset (public). Clone it to get updates.
- **Static review version** (synthetic data, no install needed): https://hcm-ipv-mr-review.vercel.app

## Get it running (about 15 minutes on the first run)

1. Install **Docker Desktop**, give it **8 GB RAM** (Settings → Resources), and start it. You also need **Python 3.9 or later**.
2. Get the **microplan workbook** (`Copy of Namibia_IPV_MR_Microplan.xlsx`) from the project owner. It's not in this package because it contains the user list. Put it in the folder **above** this one, or set `MICROPLAN_XLSX=/path/to/file.xlsx`.
3. Run:
   ```bash
   ./setup.sh
   ```
4. Open http://localhost:8088/superset/dashboard/hcm-ipv-mr-namibia/ and log in with `admin` / `admin`.

The data you'll see is **synthetic** (days 1–6 of the 11-day campaign).

## Connect the real HCM Elasticsearch

1. Fill in the yellow cells of `docs/HCM_Elastic_Plug-in_Sheet.xlsx`, working through sheets 1–4. Sheet 5 shows which KPIs are ready.
   Two KPI groups need data HCM doesn't collect yet:
   - **Zero-dose:** a yes/no "no prior routine dose" answer at registration (field F24).
   - **AEFI:** a source for adverse-event cases (index I8): an HCM index or the national AEFI system.
2. Follow sheet 7, the go-live checklist. In short:
   - put the ES host and login in `trino/catalog/hcm.properties`;
   - update the index and field names in `tools/hcm_datasets.py`;
   - run `./setup.sh --no-mock`.

Using Claude Code? Open this folder and ask, for example: *"Apply the mappings from the filled-in plug-in sheet and rebuild the dashboard."* It starts from `CLAUDE.md`.

## Rules for this project

- Keep the microplan workbook and ES passwords **out of git**. The repo and the review site are public.
- Label any figures you share as synthetic until real HCM data is connected.
- Questions about targets, eligibility or wastage assumptions go to the project owner (see "Decisions and assumptions to keep" in `CLAUDE.md`).

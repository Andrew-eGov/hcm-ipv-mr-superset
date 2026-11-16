"""Build docs/HCM_Elastic_Plug-in_Sheet.xlsx - the KPI-by-KPI mapping workbook a
colleague fills in to point the dashboard at the real HCM Elasticsearch.

    tools/.venv/bin/python -I tools/build_plug_sheet.py
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/HCM_Elastic_Plug-in_Sheet.xlsx"

FONT = "Arial"
TEAL = "0B4B66"
FILL_IN = PatternFill("solid", fgColor="FFF2A8")      # yellow = colleague fills in
HEAD = PatternFill("solid", fgColor=TEAL)
SUB = PatternFill("solid", fgColor="E8F1F5")
EXAMPLE = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="D0D0D0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

STATUS = ["Not started", "Mapped - same name", "Mapped - different name", "Needs transform", "Not available in HCM"]
STATUS_LIST = '"' + ",".join(STATUS) + '"'
DONE_STATUSES = ("Mapped - same name", "Mapped - different name")

# ------------------------------------------------------------------ content
INDEXES = [
    # id, logical, holds, index read today, notes
    ("I1", "Child line list", "One document per child seen at a site (both vaccines on the same document)", "field-child-v1",
     "Today: the Children sheet of the Zambezi field database. In HCM: the individual / project-task index. If HCM stores one task per vaccine, flag 'Needs transform' (pivot to one row per child with mr / ipv flags)."),
    ("I2", "Site-day report", "One document per site x date x vaccine: target, children vaccinated by age group, vials received / additional / opened / returned unopened",
     "field-site-day-v1",
     "Today: Agg_MR + Stock_MR and Agg_IPV + Stock_IPV of the field database. In HCM: stock index (vials) + task aggregates (children) + the microplan daily site target. Usually 'Needs transform' (a daily aggregation job)."),
]

# id, index, field path, ES type, format / allowed values, example, used by, notes
FIELDS = [
    ("F01", "I1", "child_id", "keyword", "Unique child id", "BKL-000001", "K32", "Only used to count children; never shown or exported."),
    ("F02", "I1", "event_date", "date", "Date the child was vaccinated (yyyy-MM-dd, local time)", "2026-11-10", "K13 K30 K31 K32", ""),
    ("F03", "I1", "site_code", "keyword", "Site code, as in data/sites.csv", "S01", "K13 K30 K31 K32", "Join on site code, never on site name (names vary between sheets)."),
    ("F04", "I1", "age_group", "keyword", "Age group as recorded - see sheet 4", "12-59 months", "K31", ""),
    ("F05", "I1", "mr", "integer", "1 if MR given, else 0", "1", "K13 K30 K32", ""),
    ("F06", "I1", "ipv", "integer", "1 if IPV given, else 0", "1", "K13 K30 K32", ""),
    ("F07", "I1", "vaccine_status", "keyword", "Which vaccines the child received - see sheet 4", "IPV + MR", "K31", ""),
    ("F08", "I1", "gender", "keyword", "MALE / FEMALE (empty if not recorded)", "FEMALE", "K13", "Not in the field database yet: the loader fills a synthetic gender (gender_synthetic = 1) and the pies are labelled synthetic."),
    ("F09", "I1", "source_campaign_day", "integer", "Campaign day as written by the source", "1", "K33", "Only used to flag day-number mismatches."),
    ("F20", "I2", "vaccine", "keyword", "MR or IPV - see sheet 4", "MR", "All I2 KPIs", "One document per vaccine."),
    ("F21", "I2", "event_date", "date", "Report date (yyyy-MM-dd)", "2026-11-10", "All I2 KPIs", "Campaign day is computed from this date (9 Nov = day 1)."),
    ("F22", "I2", "site_code", "keyword", "Site code, as in data/sites.csv", "S01", "All I2 KPIs", ""),
    ("F23", "I2", "target", "integer", "Children planned for the site that day", "209", "K01 K02 K03 K04 K10 K11 K12 K14 K22", "Microplan daily site target. Planned = sum over the sites and days that uploaded data."),
    ("F24", "I2", "vaccinated_6_11m", "integer", "MR: children vaccinated 6-11 months", "14", "K12", "MR only."),
    ("F25", "I2", "vaccinated_14w_11m", "integer", "IPV: children vaccinated 14 weeks-11 months", "17", "K12", "IPV only."),
    ("F26", "I2", "vaccinated_12_59m", "integer", "Children vaccinated 12-59 months", "79", "K12", "Both vaccines."),
    ("F27", "I2", "vaccinated_5_10y", "integer", "MR: children vaccinated 5-10 years", "109", "K12", "MR only."),
    ("F28", "I2", "total_vaccinated", "integer", "Children vaccinated (sum of the age groups)", "202", "K01 K02 K03 K05 K10 K11 K14 K21 K30 K31", ""),
    ("F29", "I2", "vials_received", "integer", "Vials issued to the site at the start of the day", "59", "K15 K16 K17 K20 K24 K34", ""),
    ("F30", "I2", "additional_vials_received", "integer", "Top-up vials issued during the day", "0", "K16 K17 K20 K24 K34", ""),
    ("F31", "I2", "vials_opened", "integer", "Vials used for vaccination that day", "41", "K05 K06 K18 K21 K24 K34", ""),
    ("F32", "I2", "vials_returned_unopened", "integer", "Vials sent back to the store at day end", "18", "K17 K18 K19 K20 K24 K34", ""),
    ("F33", "I2", "source_campaign_day", "integer", "Campaign day as written by the source", "2", "K33", "Only used to flag day-number mismatches."),
]

CODES = [
    # field id, field, dashboard code, meaning
    ("F20", "vaccine", "MR", "Measles-Rubella vaccine"),
    ("F20", "vaccine", "IPV", "Inactivated polio vaccine"),
    ("F04", "age_group", "0-11 months", "Line-list age group (shown as 6-11 months for MR, 14 weeks-11 months for IPV)"),
    ("F04", "age_group", "12-59 months", "Line-list age group"),
    ("F04", "age_group", "5-10 years", "Line-list age group (MR only)"),
    ("F07", "vaccine_status", "IPV + MR", "Child received both vaccines"),
    ("F07", "vaccine_status", "MR only (not eligible for IPV)", "MR only, child outside the IPV age range"),
    ("F07", "vaccine_status", "MR only (IPV eligible, not received)", "MR only, IPV-eligible child did not get IPV"),
    ("F07", "vaccine_status", "IPV only", "IPV only"),
    ("F08", "gender", "MALE", "Male"),
    ("F08", "gender", "FEMALE", "Female"),
]

COV = "Children vaccinated ÷ target"
KPIS = [
    # id, tab, KPI, definition, numerator, denominator, ES indexes, ES fields, microplan inputs, dataset
    ("K01", "Overview", "Children vaccinated (MR, IPV)", "Sum of total_vaccinated, per vaccine", "total_vaccinated", "-", "I2", "F20 F21 F22 F28", "dim_site", "field_site_day"),
    ("K02", "Overview", "Target (MR, IPV)", "Sum of target for the sites and days that uploaded data", "target", "-", "I2", "F20 F21 F22 F23", "dim_site", "field_site_day"),
    ("K03", "Overview / Coverage", "Coverage of target (MR, IPV)", COV, "total_vaccinated", "target", "I2", "F20 F21 F22 F23 F28", "dim_site", "field_site_day"),
    ("K04", "Overview", "Vaccinated vs remaining to target (pie)", "Vaccinated and target - vaccinated, per vaccine", "total_vaccinated", "target", "I2", "F20 F21 F22 F23 F28", "dim_site", "field_progress_pie"),
    ("K05", "Overview / Inventory", "Wastage %", "(doses in opened vials - children vaccinated) ÷ doses in opened vials", "vials_opened × doses per vial - total_vaccinated", "vials_opened × doses per vial", "I2", "F20 F22 F28 F31", "dim_product.doses_per_unit", "field_site_day"),
    ("K06", "Overview", "Vials opened", "Sum of vials_opened", "vials_opened", "-", "I2", "F20 F22 F31", "-", "field_site_day"),
    ("K07", "Overview", "Sites reporting", "Distinct sites with a report", "site_code", "-", "I2", "F20 F22", "dim_site", "field_site_day"),
    ("K10", "Overview / Coverage", "Coverage by region / district / cluster / site", COV + ", grouped", "total_vaccinated", "target", "I2", "F20 F22 F23 F28", "dim_site, dim_district", "field_site_day"),
    ("K11", "Overview / Coverage (map)", "Coverage maps by district and region", COV + " per area; areas without uploads stay blank", "total_vaccinated", "target", "I2", "F20 F22 F23 F28", "dim_site, dim_district_polygon, dim_region_polygon", "field_district_map, field_region_map"),
    ("K12", "Coverage", "Children vaccinated by age group", "Sum of the age-group columns, labels as in the source", "vaccinated_* columns", "-", "I2", "F20 F22 F24 F25 F26 F27", "-", "field_age"),
    ("K13", "Overview", "Gender distribution (MR, IPV)", "Children by gender, per vaccine received", "children", "-", "I1", "F02 F03 F05 F06 F08", "dim_site", "field_children"),
    ("K14", "Coverage", "Planned vs actual, cumulative", "Cumulative target and cumulative children vaccinated by date", "total_vaccinated", "target", "I2", "F20 F21 F22 F23 F28", "-", "field_site_day"),
    ("K15", "Inventory", "Stores and sites with at least one stock entry", "Distinct sites with vials_received recorded", "site_code", "-", "I2", "F22 F29", "dim_site", "field_site_day"),
    ("K16", "Inventory", "Vials received / additional vials received", "Sums, per vaccine", "vials_received, additional_vials_received", "-", "I2", "F20 F22 F29 F30", "-", "field_site_day"),
    ("K17", "Inventory", "Vials issued (net)", "Vials received + additional vials received - vials returned unopened", "F29 + F30 - F32", "-", "I2", "F20 F22 F29 F30 F32", "-", "field_site_day"),
    ("K18", "Inventory", "Vials opened / returned unopened", "Sums, per vaccine", "vials_opened, vials_returned_unopened", "-", "I2", "F20 F22 F31 F32", "-", "field_site_day"),
    ("K19", "Inventory", "Vials in hand - district store", "Vials returned unopened on the latest day with data", "vials_returned_unopened", "-", "I2", "F20 F21 F22 F32", "-", "field_stock_days"),
    ("K20", "Inventory", "Days of stock left (with campaign day)", "Vials in hand ÷ average daily vials opened (last 3 days); shown as 'x days of stock · Day n of 11'", "K19", "average vials_opened per day", "I2", "F20 F21 F22 F31 F32", "campaign length (11 days)", "field_stock_days"),
    ("K21", "Inventory", "Wastage % by district and site (allowed 5%)", "As K05, grouped, with the 5% allowed line", "see K05", "see K05", "I2", "F20 F22 F28 F31", "dim_product", "field_site_day"),
    ("K22", "Inventory", "Cumulative vials issued (net) vs vials needed, by site", "Vials needed = target ÷ doses per vial × (1 + 5%); sites below need highlighted", "K17", "target ÷ doses per vial × 1.05", "I2", "F20 F22 F23 F29 F30 F32", "dim_product", "field_site_day, field_sites"),
    ("K24", "Inventory", "Stock flow (Sankey)", "National > regional > district store > site > vials opened / returned unopened (store layers = sums of sites)", "vials", "-", "I2", "F20 F22 F29 F30 F31 F32", "dim_site", "field_stock_flow"),
    ("K30", "Data Quality", "Child line list vs aggregate", "Children in the line list ≠ total_vaccinated for the same site, date and vaccine", "line-list count", "total_vaccinated", "I1 I2", "F02 F03 F05 F06 F21 F22 F28", "-", "field_dq"),
    ("K31", "Data Quality", "Children above target / above doses", "Site-days with total_vaccinated > target, or > doses in opened vials", "total_vaccinated", "target, doses", "I2", "F22 F23 F28 F31", "dim_product", "field_dq"),
    ("K32", "Coverage", "Children by vaccines received", "Children per vaccine_status", "children", "-", "I1", "F01 F02 F03 F07", "dim_site", "field_child_status"),
    ("K33", "Data Quality", "Campaign-day label mismatch", "Source campaign day ≠ day computed from the date", "-", "-", "I1 I2", "F09 F21 F33", "-", "field_dq"),
    ("K34", "Data Quality", "Stock not balanced", "Vials received + additional ≠ opened + returned unopened", "F29 + F30 - F31 - F32", "-", "I2", "F22 F29 F30 F31 F32", "-", "field_dq"),
    ("K35", "Data Quality", "Reporting completeness", "Site-day reports received ÷ sites × vaccines × dates with data", "reports", "sites × vaccines × dates", "I2", "F20 F21 F22", "dim_site", "field_reporting"),
]

CONNECTION = [
    # parameter, file / setting, current value, notes
    ("Elasticsearch host", "trino/catalog/hcm.properties → elasticsearch.host", "elasticsearch", "Hostname or IP of the HCM ES cluster, as reachable from the Trino container."),
    ("Elasticsearch port", "hcm.properties → elasticsearch.port", "9200", ""),
    ("TLS (https)?", "hcm.properties → elasticsearch.tls.enabled", "false", "true if the cluster URL starts with https://"),
    ("Verify TLS hostname?", "hcm.properties → elasticsearch.tls.verify-hostnames", "(not set)", "Set false only for self-signed certificates on a private network."),
    ("Authentication", "hcm.properties → elasticsearch.security", "(none)", "PASSWORD for basic auth; leave empty if open inside the network."),
    ("ES user name", "hcm.properties → elasticsearch.auth.user", "(none)", "Read-only user is enough."),
    ("ES password", "hcm.properties → elasticsearch.auth.password", "(none)", "DO NOT type the password in this sheet. Put it only in hcm.properties on the server (never commit it)."),
    ("Index names", "tools/datasets.py → CHILD, SITE_DAY", "field-child-v1, field-site-day-v1", "Real index or alias names (sheet 2)."),
    ("Document root object", "tools/datasets.py", "none (flat fields)", "If real docs nest fields (e.g. under 'Data'), write the root here."),
    ("Campaign / project filter", "tools/datasets.py (add a WHERE clause)", "(none - one campaign)", "If the indexes hold several campaigns, which field + value identifies NAM-09-01-IPV-MR_NID?"),
    ("Campaign start date", "tools/datasets.py → CAMPAIGN_START", "2026-11-09", "Day 1. Confirm."),
    ("Campaign length (days)", "tools/datasets.py → CAMPAIGN_DAYS", "11", "9-19 Nov. Confirm."),
    ("Superset URL", "(server)", "http://localhost:8088", "Where the dashboard will be hosted."),
]

CHECKLIST = [
    ("Fill sheet 1 (Connection) - except the password", "Colleague", "Sheet 1"),
    ("Fill sheet 2 (Indexes): where the child line list and the site-day report live in HCM (or which job will build them)", "Colleague", "Sheet 2"),
    ("Edit trino/catalog/hcm.properties on the server, then: docker compose restart trino", "Colleague", "README → Going live"),
    ("Check Trino sees the indexes: docker compose exec trino trino --execute \"SHOW TABLES FROM hcm.default\"", "Colleague", "Every index from sheet 2 should be listed"),
    ("Look at one real document per index (query in sheet 2, column G) and fill sheet 3 (Fields)", "Colleague", "Sheet 3"),
    ("Fill sheet 4 (Value codes): the real value for each dashboard code", "Colleague", "Sheet 4"),
    ("Check KPI readiness on sheet 5: 'Fields not yet mapped' should be 0 for every KPI", "Colleague", "Sheet 5"),
    ("Add every real site to data/sites.csv (code, name, cluster, type, coordinates)", "Developer", "Sheet 6"),
    ("Update index names and field paths in tools/datasets.py from sheets 2-4", "Developer", "tools/datasets.py"),
    ("Regenerate and test datasets: tools/datasets.py, then tools/test_datasets.sh (every dataset returns rows)", "Developer", "-"),
    ("Rebuild the dashboard: ./setup.sh --no-field-data", "Developer", "-"),
    ("Spot-check 3 KPIs against the field database or HCM reports (e.g. children vaccinated at one site on one day)", "Both", "Sheet 5, column N"),
]

MICROPLAN = [
    ("dim_site", "data/sites.csv", "Site code, name, cluster, facility type, coordinates (source noted)", "Every site_code in ES must be here. Two Zambezi sites have approximate coordinates."),
    ("dim_district", "Microplan Boundary List", "boundary_code, region, district, targets, team counts", "Sites map to districts through dim_site."),
    ("dim_district_polygon / dim_region_polygon", "data/districts.geojson, data/regions.geojson", "Shapes for the coverage maps", "District shapes are approximate - replace with official ones if available."),
    ("dim_product", "tools/load_microplan.py (PRODUCTS)", "Doses per vial, eligible ages, allowed wastage", "MR 5 and IPV 10 doses per vial, inferred from the field data - confirm."),
    ("dim_campaign_day", "tools/load_microplan.py", "Campaign days 1-11", ""),
]


# ------------------------------------------------------------------ helpers
def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = HEAD
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BOX
    ws.row_dimensions[row].height = 32


def title(ws, text, sub):
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color=TEAL)
    ws["A2"] = sub
    ws["A2"].font = Font(name=FONT, size=10, color="555555")
    ws["A2"].alignment = Alignment(wrap_text=False)


def body(ws, r, c, v, fill=None, bold=False, italic=False, color="000000"):
    cell = ws.cell(row=r, column=c, value=v)
    cell.font = Font(name=FONT, size=10, bold=bold, italic=italic, color=color)
    cell.alignment = WRAP
    cell.border = BOX
    if fill:
        cell.fill = fill
    return cell


def widths(ws, ws_widths):
    for i, w in enumerate(ws_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def status_validation(ws, rng):
    dv = DataValidation(type="list", formula1=STATUS_LIST, allow_blank=True)
    dv.error, dv.errorTitle = "Pick a status from the list", "Status"
    ws.add_data_validation(dv)
    dv.add(rng)


def status_colors(ws, rng, col_letter, first_row):
    ref = f"${col_letter}{first_row}"
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'LEFT({ref},6)="Mapped"'], fill=PatternFill("solid", fgColor="C6EFCE")))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'{ref}="Needs transform"'], fill=PatternFill("solid", fgColor="FFE5B4")))
    ws.conditional_formatting.add(rng, FormulaRule(formula=[f'{ref}="Not available in HCM"'], fill=PatternFill("solid", fgColor="F8CBCB")))


# ------------------------------------------------------------------ build
def main():
    wb = Workbook()

    # ---- 0 Start here
    ws = wb.active
    ws.title = "0 Start here"
    title(ws, "HCM IPV + MR dashboard - Elasticsearch plug-in sheet",
          "Fill this in to connect the Superset dashboard to the real HCM Elasticsearch. Every KPI on the dashboard is listed with the exact fields it needs. Today the dashboard reads the Zambezi field database loaded into ES.")
    rows = [
        ("How to use", ""),
        ("1", "Sheet 1 Connection - where the ES cluster is (no passwords here)."),
        ("2", "Sheet 2 Indexes - where each of the 2 data sources lives in HCM (index name, or the job that builds it)."),
        ("3", "Sheet 3 Fields - for each field the dashboard reads, the real HCM field path (or what transform is needed)."),
        ("4", "Sheet 4 Value codes - the real HCM value for each code the dashboard filters on (e.g. how HCM writes the vaccine names)."),
        ("5", "Sheet 5 KPIs - read-only catalogue of every KPI, its formula and fields. 'Fields not yet mapped' updates automatically from sheet 3."),
        ("6", "Sheet 6 Microplan - reference data loaded from the microplan (not from ES)."),
        ("7", "Sheet 7 Go-live checklist - the steps in order."),
        ("", ""),
        ("Legend", ""),
        ("Yellow cell", "You fill this in."),
        ("Grey row", "Worked example showing the expected format - leave it as is."),
        ("Status", "Pick from the dropdown: Not started · Mapped - same name · Mapped - different name · Needs transform · Not available in HCM."),
        ("", ""),
        ("Progress", ""),
        ("Indexes mapped", "=COUNTIF('2 Indexes'!$H$6:$H$7,\"Mapped*\")&\" of \"&COUNTA('2 Indexes'!$A$6:$A$7)"),
        ("Fields mapped", "=COUNTIF('3 Fields'!$K$6:$K$100,\"Mapped*\")&\" of \"&COUNTA('3 Fields'!$A$6:$A$100)"),
        ("Fields needing a transform", "=COUNTIF('3 Fields'!$K$6:$K$100,\"Needs transform\")"),
        ("Fields not available in HCM", "=COUNTIF('3 Fields'!$K$6:$K$100,\"Not available in HCM\")"),
        ("Value codes mapped", "=COUNTIF('4 Value codes'!$G$6:$G$100,\"Mapped*\")&\" of \"&COUNTA('4 Value codes'!$C$6:$C$100)"),
        ("KPIs ready (all fields mapped)", "=COUNTIF('5 KPIs'!$L$5:$L$100,0)&\" of \"&COUNTA('5 KPIs'!$A$5:$A$100)"),
        ("", ""),
        ("Contact", "Questions about a field or KPI: send this workbook back with notes in the 'Notes' columns."),
        ("Note", "The dashboard currently shows the Zambezi region MR/IPV child and stock database (field data, 10-11 Nov 2026). Column 'Dashboard reads today' lists the field names loaded from it."),
    ]
    for i, (a, b) in enumerate(rows, start=4):
        ca = ws.cell(row=i, column=1, value=a)
        cb = ws.cell(row=i, column=2, value=b)
        ca.font = Font(name=FONT, size=10, bold=a in ("How to use", "Legend", "Progress", "Contact", "Note") or a.isdigit())
        cb.font = Font(name=FONT, size=10, bold=str(b).startswith("="))
        cb.alignment = Alignment(wrap_text=True, vertical="top")
        if a in ("How to use", "Legend", "Progress"):
            ca.fill = SUB
            cb.fill = SUB
    ws["A14"].fill = FILL_IN
    ws["A15"].fill = EXAMPLE
    widths(ws, [30, 120])

    # ---- 1 Connection
    ws = wb.create_sheet("1 Connection")
    title(ws, "1 · Connection", "Where the HCM Elasticsearch is. Fill the yellow column. Never write the password in this workbook.")
    hdr = ["Parameter", "Where it goes", "Current value", "Your value", "Notes"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    for i, (p, w, m, n) in enumerate(CONNECTION, start=5):
        body(ws, i, 1, p, bold=True)
        body(ws, i, 2, w)
        body(ws, i, 3, m, color="0000FF")
        body(ws, i, 4, "(kept in hcm.properties only)" if "password" in p.lower() else None,
             fill=None if "password" in p.lower() else FILL_IN, italic="password" in p.lower())
        body(ws, i, 5, n)
    ws.cell(row=5, column=4).comment = Comment("Example: es-hcm.internal.gov.na (or an IP like 10.0.4.21)", "HCM dashboard")
    widths(ws, [28, 44, 26, 34, 70])
    ws.freeze_panes = "A5"

    # ---- 2 Indexes
    ws = wb.create_sheet("2 Indexes")
    title(ws, "2 · Indexes", "The 2 Elasticsearch indexes the dashboard reads. Fill the real HCM index / alias (or the job that builds it) and status.")
    hdr = ["Id", "Data source", "What one document is", "Dashboard reads today", "Real HCM index / alias", "Approx. doc count", "Check query (Trino)", "Status", "Notes"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    ex = ["EX", "Child line list", "One document per child", "field-child-v1", "na-individual-index-v1", 250000,
          'SELECT * FROM hcm.default."na-individual-index-v1" LIMIT 5', "Mapped - different name", "Example row - format only"]
    for c, v in enumerate(ex, 1):
        body(ws, 5, c, v, fill=EXAMPLE, italic=True, color="666666")
    for i, (iid, name, what, mock, note) in enumerate(INDEXES, start=6):
        body(ws, i, 1, iid, bold=True)
        body(ws, i, 2, name, bold=True)
        body(ws, i, 3, what)
        body(ws, i, 4, mock, color="0000FF")
        body(ws, i, 5, None, fill=FILL_IN)
        body(ws, i, 6, None, fill=FILL_IN).number_format = "#,##0"
        body(ws, i, 7, f'=IF(E{i}="","",CONCATENATE("SELECT * FROM hcm.default.""",E{i},""" LIMIT 5"))')
        body(ws, i, 8, "Not started", fill=FILL_IN)
        body(ws, i, 9, note)
    status_validation(ws, f"H6:H{5 + len(INDEXES)}")
    status_colors(ws, f"H6:H{5 + len(INDEXES)}", "H", 6)
    widths(ws, [6, 22, 40, 28, 32, 14, 52, 24, 60])
    ws.freeze_panes = "C6"

    # ---- 3 Fields
    ws = wb.create_sheet("3 Fields")
    title(ws, "3 · Fields", "Every field the dashboard reads, by index. Paths are relative to the document root (today: flat fields, no root object). Fill the yellow columns.")
    hdr = ["Id", "Index", "Dashboard expects (field path)", "ES type", "Meaning / format", "Example value", "Used by KPIs",
           "Real HCM field path", "Real example value", "Transform needed (if any)", "Status", "Notes"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    ex = ["EX", "I2", "vaccine", "keyword", "Vaccine code", "MR", "K01 K03", "Data.productVariantId", "PVAR-MR-5D",
          "Map PVAR-MR-5D → MR, PVAR-IPV-10D → IPV", "Needs transform", "Example row - format only"]
    for c, v in enumerate(ex, 1):
        body(ws, 5, c, v, fill=EXAMPLE, italic=True, color="666666")
    for i, f in enumerate(FIELDS, start=6):
        fid, idx, path, typ, fmt, exv, used, note = f
        body(ws, i, 1, fid, bold=True)
        body(ws, i, 2, idx)
        body(ws, i, 3, path, color="0000FF")
        body(ws, i, 4, typ)
        body(ws, i, 5, fmt)
        body(ws, i, 6, exv)
        body(ws, i, 7, used)
        for c in (8, 9, 10):
            body(ws, i, c, None, fill=FILL_IN)
        body(ws, i, 11, "Not started", fill=FILL_IN)
        body(ws, i, 12, note)
    last = 5 + len(FIELDS)
    status_validation(ws, f"K6:K{last}")
    status_colors(ws, f"K6:K{last}", "K", 6)
    widths(ws, [6, 13, 30, 10, 42, 26, 24, 30, 22, 34, 22, 52])
    ws.freeze_panes = "D6"
    ws.auto_filter.ref = f"A4:L{last}"

    # ---- 4 Value codes
    ws = wb.create_sheet("4 Value codes")
    title(ws, "4 · Value codes", "Codes the dashboard filters on. Write the value HCM actually stores (exact spelling and case).")
    hdr = ["Field id", "Field", "Dashboard code", "Meaning", "Real HCM value", "Notes", "Status"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    ex = ["EX", "vaccine", "IPV", "Inactivated polio vaccine", "bOPV-IPV", "Example row - format only", "Mapped - different name"]
    for c, v in enumerate(ex, 1):
        body(ws, 5, c, v, fill=EXAMPLE, italic=True, color="666666")
    for i, (fid, field, code, meaning) in enumerate(CODES, start=6):
        body(ws, i, 1, fid, bold=True)
        body(ws, i, 2, field)
        body(ws, i, 3, code, color="0000FF")
        body(ws, i, 4, meaning)
        body(ws, i, 5, None, fill=FILL_IN)
        body(ws, i, 6, None, fill=FILL_IN)
        body(ws, i, 7, "Not started", fill=FILL_IN)
    last = 5 + len(CODES)
    status_validation(ws, f"G6:G{last}")
    status_colors(ws, f"G6:G{last}", "G", 6)
    widths(ws, [9, 26, 36, 44, 30, 40, 24])
    ws.freeze_panes = "D6"

    # ---- 5 KPIs
    ws = wb.create_sheet("5 KPIs")
    title(ws, "5 · KPI catalogue", "Every KPI on the dashboard, KPI by KPI. 'Fields not yet mapped' counts the fields in column H whose status on sheet 3 is not 'Mapped…'.")
    hdr = ["Id", "Tab", "KPI", "Definition / formula", "Numerator", "Denominator", "ES indexes", "ES fields (sheet 3 ids)",
           "Microplan inputs (sheet 6)", "Superset dataset", "Fields listed", "Fields not yet mapped", "Ready?", "Verified against HCM report? (yes / no + note)"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    nf = 5 + len(FIELDS)
    for i, k in enumerate(KPIS, start=5):
        kid, tab, name, definition, num, den, idx, fields, mp, ds = k
        for c, v in enumerate([kid, tab, name, definition, num, den, idx, fields, mp, ds], 1):
            body(ws, i, c, v, bold=c in (1, 3), color="0000FF" if c == 10 else "000000")
        # fields listed: ids in column H that appear on sheet 3; not mapped: those whose status isn't Mapped*
        body(ws, i, 11, f"=SUMPRODUCT(ISNUMBER(SEARCH('3 Fields'!$A$6:$A${nf},$H{i}))*1)")
        body(ws, i, 12, f"=SUMPRODUCT(ISNUMBER(SEARCH('3 Fields'!$A$6:$A${nf},$H{i}))*(LEFT('3 Fields'!$K$6:$K${nf},6)<>\"Mapped\"))")
        body(ws, i, 13, f'=IF(K{i}=0,"Check fields",IF(L{i}=0,"Ready","Waiting on "&L{i}&" field(s)"))', bold=True)
        body(ws, i, 14, None, fill=FILL_IN)
    last = 4 + len(KPIS)
    ws.conditional_formatting.add(f"M5:M{last}", FormulaRule(formula=['$M5="Ready"'], fill=PatternFill("solid", fgColor="C6EFCE")))
    ws.conditional_formatting.add(f"M5:M{last}", FormulaRule(formula=['LEFT($M5,7)="Waiting"'], fill=PatternFill("solid", fgColor="FFE5B4")))
    ws.cell(row=last + 2, column=4, value="'Fields not yet mapped' and 'Ready?' update automatically from the Status column on sheet 3.").font = Font(name=FONT, size=9, italic=True, color="666666")
    widths(ws, [6, 20, 30, 48, 34, 30, 10, 30, 26, 24, 9, 11, 22, 32])
    ws.freeze_panes = "D5"
    ws.auto_filter.ref = f"A4:N{last}"

    # ---- 6 Microplan
    ws = wb.create_sheet("6 Microplan")
    title(ws, "6 · Microplan reference data", "Loaded into Postgres by tools/load_microplan.py - not from Elasticsearch. Ids here must match the ES fields.")
    hdr = ["Table", "Source", "Contents", "Why it matters", "Ready? (yes / no + note)"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    for i, row in enumerate(MICROPLAN, start=5):
        for c, v in enumerate(row, 1):
            body(ws, i, c, v, bold=c == 1)
        body(ws, i, 5, None, fill=FILL_IN)
    widths(ws, [22, 34, 52, 60, 30])

    # ---- 7 Go-live checklist
    ws = wb.create_sheet("7 Go-live checklist")
    title(ws, "7 · Go-live checklist", "Do these in order. Tick the Done column (yes) as you go.")
    hdr = ["#", "Step", "Who", "Where / how to check", "Done? (yes / no)", "Date", "Notes"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    for i, (step, who, where) in enumerate(CHECKLIST, start=5):
        body(ws, i, 1, i - 4, bold=True)
        body(ws, i, 2, step)
        body(ws, i, 3, who)
        body(ws, i, 4, where)
        for c in (5, 6, 7):
            body(ws, i, c, None, fill=FILL_IN)
    last = 4 + len(CHECKLIST)
    dv = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"E5:E{last}")
    ws.cell(row=last + 2, column=2, value=f'=COUNTIF(E5:E{last},"yes")&" of {len(CHECKLIST)} steps done"').font = Font(name=FONT, bold=True, size=10)
    widths(ws, [5, 80, 12, 44, 14, 12, 40])

    for sheet in wb.worksheets:
        sheet.sheet_view.showGridLines = False
        sheet.sheet_properties.tabColor = TEAL if sheet.title.startswith("0") else ("F47738" if sheet.title[0] in "1234" else "8AA8B6")
    wb.calculation.fullCalcOnLoad = True
    OUT.parent.mkdir(exist_ok=True)
    wb.save(OUT)
    print(OUT, len(FIELDS), "fields,", len(KPIS), "KPIs,", len(CODES), "codes")


if __name__ == "__main__":
    main()

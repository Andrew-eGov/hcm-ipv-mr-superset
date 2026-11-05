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
    # id, logical, holds, mock index, notes
    ("I1", "Delivery tasks", "One document per child per vaccine delivery attempt (administered or not)", "project-task-index-v1",
     "In HCM this is usually the project task index. The dashboard needs ONE doc per product per child; if HCM stores both vaccines in one task with a resources[] array, flag 'Needs transform'."),
    ("I2", "Registered individuals", "One document per registered child", "individual-index-v1",
     "Project beneficiary / individual index."),
    ("I3", "Households", "One document per household visit (house-to-house only)", "household-index-v1",
     "Include visits where no child was vaccinated (closed / refused / absent)."),
    ("I4", "Stock transactions", "Receipts, dispatches, returns and losses at every store and team", "stock-index-v1",
     "HCM stock index. Quantities are in vials for vaccines and pieces for devices."),
    ("I5", "Supervisor checklists", "One document per submitted checklist", "service-task-v1",
     "HCM service / checklist index. Answers must be reachable as fields (see sheet 3)."),
    ("I6", "Complaints", "One document per complaint (PGR)", "pgr-services-index-v1",
     "HCM PGR index."),
    ("I7", "Downsync events", "One document per user downsync", "downsync-index-v1",
     "If HCM has no downsync index, mark 'Not available in HCM' - only the downsync KPI is affected."),
]

# id, index, field path (under Data.), ES type, format / allowed values, example, used by, notes
FIELDS = [
    # common
    ("F01", "All (I1-I7)", "boundaryHierarchyCode.district", "keyword", "District boundary code, exactly as in the microplan Boundary List", "NAMIBIA_NA_01_01_OMARURU",
     "All KPIs", "Joins every event to targets, region and district filters. Must match microplan codes 1:1."),
    ("F02", "All (I1-I7)", "eventTime", "date", "Local event time (Namibia, UTC+2), ISO 8601", "2026-11-09T09:41:12",
     "K03 K07 K08 K11 K12 K33 K34 K35 K38 K42", "Used for daily charts, days elapsed and off-hours checks. If HCM only has createdTime (epoch ms), say 'Needs transform'."),
    ("F03", "All (I1-I7)", "createdBy", "keyword", "User UUID / id of the person who recorded it", "NAM-U-00431",
     "K16 K17 K18 K34 K36", "Must match the user ids in the user list for sync-rate KPIs."),
    ("F04", "I1 I2 I3 I5 I6", "geoPoint", "geo_point", "{lat, lon} geo_point mapping", '{"lat": -21.41, "lon": 15.95}',
     "K14 K15 K30", "Needs ES mapping type geo_point for clustering and outside-district checks."),
    ("F05", "I1 I5 I6", "latitude", "double", "Decimal degrees", "-21.417372", "K13 K28 K39 K44", "Separate numeric copy of the GPS point."),
    ("F06", "I1 I5 I6", "longitude", "double", "Decimal degrees", "15.951404", "K13 K39 K44", ""),
    ("F07", "I1", "locationAccuracy", "float", "GPS accuracy in metres", "12.5", "K29", "Accuracy > 100 m is flagged."),
    ("F08", "I1", "createdTime", "long", "Epoch milliseconds", "1794200472000", "K13 K29", "Only used to sort map points newest first."),
    # task
    ("F10", "I1", "productCode", "keyword", "Vaccine code - see sheet 4", "MR", "K01 K02 K04 K05 K06 K07 K09 K10 K23 K31", "Value codes on sheet 4."),
    ("F11", "I1", "administrationStatus", "keyword", "Delivery outcome - see sheet 4", "ADMINISTRATION_SUCCESS", "K01 K02 K04 K05 K10 K13 K31", ""),
    ("F12", "I1", "reasonNotAdministered", "keyword", "Why not vaccinated (empty when administered) - see sheet 4", "REFUSED", "K10 K13", ""),
    ("F13", "I1", "quantity", "integer", "Doses given in this record (1 when administered, 0 otherwise)", "1", "K01 K02 K04 K06 K07 K08 K23", "If HCM stores quantity in vials or ml, flag 'Needs transform'."),
    ("F14", "I1", "deliveryMode", "keyword", "Fixed post / house to house / transit post - see sheet 4", "HOUSE_TO_HOUSE", "K08 K14 Delivery-mode filter", ""),
    ("F15", "I1 I2", "individualId", "keyword", "Unique child id (same across both vaccines)", "IND-3f2a9c1d0b7e44", "K05 K31", "Required to count children who got both vaccines and duplicates."),
    ("F16", "I1 I2", "ageInMonths", "integer", "Child age in completed months at vaccination", "27", "K05 K09", "If only dateOfBirth exists, flag 'Needs transform' (age is derived)."),
    ("F17", "I1 I2", "gender", "keyword", "MALE / FEMALE (empty if not recorded)", "FEMALE", "K11 K32", ""),
    ("F18", "I1", "teamId", "keyword", "Vaccination team id", "NAMIBIA_NA_01_01_OMARURU_T04", "K35", ""),
    ("F19", "I1", "teamType", "keyword", "Team type from the microplan", "Mobile/outreach", "K35", "Optional - table still works without it."),
    # individual
    ("F20", "I2", "dateOfBirth", "date", "yyyy-MM-dd (empty if not recorded)", "2023-08-14", "K32", "Missing DOB counts as an incomplete registration."),
    ("F21", "I2", "deliveryMode", "keyword", "Same codes as F14", "FIXED_POST", "K11", ""),
    ("F22", "I2", "eligibleMR", "boolean", "true if 9 months to < 10 years", "true", "K11", "Can be derived from age if HCM does not store it ('Needs transform')."),
    ("F23", "I2", "eligibleIPV", "boolean", "true if 4-59 months", "false", "K11", "Can be derived from age."),
    # household
    ("F30", "I3", "visitOutcome", "keyword", "Household visit result - see sheet 4", "VISITED", "K12 K15", ""),
    ("F31", "I3", "memberCount", "integer", "Household size", "6", "K15", ""),
    # stock
    ("F40", "I4", "facilityId", "keyword", "Store where the transaction was recorded (code as in microplan Facilities List)", "FAC_NAMIBIA_NA_01_01_OMARURU", "K19 K20 K21 K22 K27", "Mock uses 'FAC_' + boundary code; real ids must be loaded into dim_facility."),
    ("F41", "I4", "productCode", "keyword", "Product code - see sheet 4", "MR", "K20 K21 K22 K23 K24 K25 K26 K27", ""),
    ("F42", "I4", "transactionType", "keyword", "RECEIVED / DISPATCHED / RETURNED / LOSS - see sheet 4", "DISPATCHED", "K20 K21 K22 K23 K24 K25 K26", ""),
    ("F43", "I4", "quantity", "integer", "Units moved (vials for vaccines, pieces for devices)", "120", "K20 K21 K22 K23 K24 K25 K26 K27", ""),
    ("F44", "I4", "senderId", "keyword", "Sending store id (or SUPPLIER)", "FAC_NAMIBIA_NA_01_ERONGO", "K24 K25 K26", ""),
    ("F45", "I4", "senderName", "keyword", "Sending store name", "Erongo Regional Vaccine Store", "K24 K25", ""),
    ("F46", "I4", "senderType", "keyword", "WAREHOUSE / TEAM / SUPPLIER - see sheet 4", "WAREHOUSE", "K21 K23", "Team returns are identified by senderType = TEAM."),
    ("F47", "I4", "receiverId", "keyword", "Receiving store id (or team id)", "FAC_NAMIBIA_NA_01_01_OMARURU", "K24 K25 K26", ""),
    ("F48", "I4", "receiverName", "keyword", "Receiving store / team name", "Omaruru District Vaccine Store", "K24 K25", ""),
    ("F49", "I4", "receiverType", "keyword", "WAREHOUSE / TEAM - see sheet 4", "TEAM", "K21 K23", "Issues to teams are identified by receiverType = TEAM."),
    ("F50", "I4", "waybillNumber", "keyword", "Shared by the DISPATCHED and matching RECEIVED record", "WB-48213", "K24", "Without a shared waybill the discrepancy report cannot pair transactions."),
    # checklist
    ("F60", "I5", "supervisorRole", "keyword", "Role of submitter - see sheet 4", "TEAM_SUPERVISOR", "K36 K38 K39", ""),
    ("F61", "I5", "checklistName", "keyword", "Checklist template name", "Team Supervisor Checklist", "K38", ""),
    ("F62", "I5", "answeredQuestions", "integer", "Questions answered", "10", "K37", ""),
    ("F63", "I5", "totalQuestions", "integer", "Questions in the checklist", "10", "K37", ""),
    ("F64", "I5", "qColdChainOk", "boolean", "Vaccine carrier with conditioned ice packs (yes = true)", "true", "K37", "One row per checklist question. Map each to the real HCM question code."),
    ("F65", "I5", "qVvmOk", "boolean", "VVM usable (stage 1-2)", "true", "K37", ""),
    ("F66", "I5", "qOpenVialLabelled", "boolean", "Opened vials labelled with time", "false", "K37", ""),
    ("F67", "I5", "qCorrectSyringe", "boolean", "Correct AD syringe per vaccine", "true", "K37", ""),
    ("F68", "I5", "qSafetyBoxUsed", "boolean", "Safety box used correctly", "true", "K37", ""),
    ("F69", "I5", "qAgeScreening", "boolean", "Age screening done correctly", "true", "K37", ""),
    ("F70", "I5", "qFingerMarking", "boolean", "Finger marking done", "true", "K37", ""),
    ("F71", "I5", "qTallyMatchesApp", "boolean", "Tally sheet matches app", "false", "K37", ""),
    ("F72", "I5", "qTeamComplete", "boolean", "Team complete and on time", "true", "K37", ""),
    ("F73", "I5", "qSocialMobilisation", "boolean", "Community informed", "true", "K37", ""),
    # complaints
    ("F80", "I6", "complaintType", "keyword", "Complaint category", "Household/child not visited", "K42 K44", ""),
    ("F81", "I6", "applicationStatus", "keyword", "PGR status - see sheet 4", "RESOLVED", "K40 K41 K42", ""),
    ("F82", "I6", "source", "keyword", "mobile / helpdesk", "helpdesk", "K42", "Optional."),
    ("F83", "I6", "resolutionHours", "float", "Hours from creation to resolution (empty if open)", "21.5", "K41", "Usually 'Needs transform': (resolved time - created time) in hours."),
]

CODES = [
    # field id, field, dashboard code, meaning
    ("F10/F41", "productCode", "MR", "Measles-Rubella vaccine"),
    ("F10/F41", "productCode", "IPV", "Fractional IPV (fIPV)"),
    ("F41", "productCode", "ADS_05", "AD syringe 0.5 mL (MR)"),
    ("F41", "productCode", "ADS_01", "AD syringe 0.1 mL (fIPV)"),
    ("F41", "productCode", "RUP_5", "Reconstitution syringe 5 mL (MR)"),
    ("F11", "administrationStatus", "ADMINISTRATION_SUCCESS", "Dose given - the only value counted as a dose"),
    ("F11", "administrationStatus", "NOT_ADMINISTERED", "Any non-administered outcome (reason in F12)"),
    ("F12", "reasonNotAdministered", "REFUSED", "Caregiver refused"),
    ("F12", "reasonNotAdministered", "CONTRAINDICATED_SICK", "Child sick / contraindicated"),
    ("F12", "reasonNotAdministered", "HESITANT_RETURN_LATER", "Hesitant, asked to return later"),
    ("F12", "reasonNotAdministered", "STOCK_OUT", "No vaccine available at the time"),
    ("F14/F21", "deliveryMode", "FIXED_POST", "Fixed post (health facility)"),
    ("F14/F21", "deliveryMode", "HOUSE_TO_HOUSE", "House to house"),
    ("F14/F21", "deliveryMode", "TRANSIT_POST", "Transit post (temporary fixed)"),
    ("F30", "visitOutcome", "VISITED", "Household visited"),
    ("F30", "visitOutcome", "CLOSED_HOUSEHOLD", "Nobody home"),
    ("F30", "visitOutcome", "REFUSED", "Household refused"),
    ("F30", "visitOutcome", "CHILD_ABSENT", "Eligible child absent"),
    ("F42", "transactionType", "RECEIVED", "Stock received into the store"),
    ("F42", "transactionType", "DISPATCHED", "Stock issued out of the store"),
    ("F42", "transactionType", "RETURNED", "Stock returned into the store"),
    ("F42", "transactionType", "LOSS", "Damaged / expired / VVM stage 3"),
    ("F46/F49", "senderType / receiverType", "WAREHOUSE", "A store (national, regional, district)"),
    ("F46/F49", "senderType / receiverType", "TEAM", "Vaccination team"),
    ("F46", "senderType", "SUPPLIER", "External supplier (into national store)"),
    ("F60", "supervisorRole", "TEAM_SUPERVISOR", "Team supervisor"),
    ("F60", "supervisorRole", "DISTRICT_SUPERVISOR", "District supervisor"),
    ("F60", "supervisorRole", "PROVINCIAL_SUPERVISOR", "Regional supervisor"),
    ("F60", "supervisorRole", "NATIONAL_SUPERVISOR", "National supervisor"),
    ("F81", "applicationStatus", "RESOLVED", "Resolved"),
    ("F81", "applicationStatus", "REJECTED", "Rejected"),
    ("F81", "applicationStatus", "PENDING_ASSIGNMENT / PENDING_AT_LME", "Open (any other status counts as open)"),
]

# id, tab, KPI, definition, numerator, denominator, ES indexes, fields, microplan inputs, dataset
KPIS = [
    ("K01", "Overview / Coverage", "MR coverage %", "Cumulative MR doses ÷ MR target", "Sum of quantity where productCode = MR and status = ADMINISTRATION_SUCCESS", "MR target (children 9 m to <10 y)", "I1", "F01 F10 F11 F13", "dim_district.mr_target", "hcm_coverage"),
    ("K02", "Overview / Coverage", "fIPV coverage %", "Cumulative fIPV doses ÷ fIPV target", "Sum of quantity where productCode = IPV and status = ADMINISTRATION_SUCCESS", "fIPV target (95% of under-5)", "I1", "F01 F10 F11 F13", "dim_district.ipv_target", "hcm_coverage"),
    ("K03", "Overview / Coverage", "Doses vs plan to date", "Doses ÷ (target × days elapsed ÷ 11)", "K01 + K02 doses", "Target × days elapsed ÷ campaign days", "I1", "F01 F02 F10 F11 F13", "targets, dim_campaign_day", "hcm_coverage"),
    ("K04", "Overview", "Total doses administered", "MR + fIPV doses", "Sum of quantity where status = ADMINISTRATION_SUCCESS", "-", "I1", "F01 F10 F11 F13", "-", "hcm_coverage"),
    ("K05", "Overview / Coverage", "Children 9-59 m given both vaccines", "(MR doses + fIPV doses − distinct children) ÷ distinct children, ages 9-59 m", "Children with both vaccines", "Distinct children aged 9-59 m vaccinated", "I1", "F01 F10 F11 F15 F16", "-", "hcm_coadmin"),
    ("K06", "Coverage", "Coverage % by district / region", "K01 and K02 per district, rolled up to region", "Doses per district", "Target per district", "I1", "F01 F10 F11 F13", "targets", "hcm_coverage"),
    ("K07", "Overview / Coverage", "Planned vs actual (cumulative)", "Cumulative doses by day ÷ target vs planned cumulative %", "Cumulative doses", "Target", "I1", "F01 F02 F10 F11 F13", "dim_campaign_day.planned_cum_pct", "hcm_planned_vs_actual"),
    ("K08", "Coverage", "Daily doses by delivery mode", "Doses per day split by mode", "Doses", "-", "I1", "F01 F02 F13 F14", "-", "hcm_delivery_daily"),
    ("K09", "Coverage", "Doses by age group", "Doses for 4-8 m, 9-59 m, 5-9 y", "Doses", "-", "I1", "F01 F10 F11 F16", "-", "hcm_age"),
    ("K10", "Coverage", "Missed opportunities by reason", "Children not vaccinated, by reason", "Records with status <> ADMINISTRATION_SUCCESS", "-", "I1", "F01 F10 F11 F12", "-", "hcm_delivery_daily"),
    ("K11", "Coverage", "Registrations by gender / mode", "Registered children by gender, delivery mode, eligibility", "Registrations", "-", "I2", "F01 F02 F17 F21 F22 F23", "-", "hcm_registration_daily"),
    ("K12", "Coverage", "Household visit outcome", "Households by outcome", "Households", "-", "I3", "F01 F02 F30", "-", "hcm_household_daily"),
    ("K13", "Coverage (map)", "Missed / refused children map", "Latest 10,000 non-administered records as points", "-", "-", "I1", "F01 F05 F06 F08 F10 F11 F12", "-", "hcm_points_missed"),
    ("K14", "Overview / Coverage (map)", "Vaccination events clustered", "Doses aggregated to map tiles (geotile) with centroid", "Doses", "-", "I1", "F01 F04 F10 F11 F14", "-", "hcm_map_delivery_tiles"),
    ("K15", "Coverage (map)", "Households visited heatmap", "Households aggregated to map tiles", "Households", "-", "I3", "F01 F04 F30 F31", "-", "hcm_map_registration_tiles"),
    ("K16", "All tabs (sync strip)", "Frontline sync rate", "Vaccinators + registrars with ≥1 record ÷ all of them", "Users found as createdBy in I1/I2/I3", "Users with role VACCINATOR/REGISTRAR", "I1 I2 I3", "F03", "dim_user", "hcm_sync"),
    ("K17", "Data Quality (sync strip)", "Downsync rate", "Vaccinators who downsynced ÷ vaccinators", "Users found as createdBy in I7", "Vaccinators", "I7", "F03", "dim_user", "hcm_sync"),
    ("K18", "Supervision (sync strip)", "Supervisor sync rate", "Supervisors with ≥1 checklist ÷ supervisors", "Users found as createdBy in I5", "Supervisors", "I5", "F03", "dim_user", "hcm_sync"),
    ("K19", "Inventory (sync strip)", "Warehouses reporting", "Stores with ≥1 stock transaction ÷ stores", "Distinct facilityId in I4", "Stores in Facilities List", "I4", "F40", "dim_facility", "hcm_sync"),
    ("K20", "Inventory", "Vials in hand", "Received + returned − dispatched − loss, per store", "-", "-", "I4", "F40 F41 F42 F43", "dim_facility, dim_product", "hcm_stock_position"),
    ("K21", "Inventory", "Days of stock left", "Vials in hand ÷ average daily net issue to teams (last 3 days)", "Vials in hand", "Avg daily (issued to TEAM − returned by TEAM)", "I4", "F02 F40 F41 F42 F43 F46 F49", "-", "hcm_stock_position"),
    ("K22", "Inventory / Overview", "Stock status / stores at risk", "Sufficient, insufficient for remaining days, stock-out risk (< 2 days)", "-", "-", "I4", "F02 F40 F41 F42 F43 F46 F49", "-", "hcm_stock_position"),
    ("K23", "Inventory / Overview", "Wastage %", "(Net vials issued to teams × doses per vial − doses administered) ÷ doses opened", "Doses wasted", "Doses in opened vials", "I1 I4", "F13 F40 F41 F42 F43 F46 F49", "dim_product.doses_per_unit, planned_wastage_pct", "hcm_wastage"),
    ("K24", "Inventory", "Receipt discrepancy", "Dispatched − received per waybill", "Sent", "Received", "I4", "F41 F42 F43 F44 F45 F47 F48 F50", "dim_facility", "hcm_stock_discrepancy"),
    ("K25", "Inventory", "Stock flow (Sankey)", "Vials dispatched national → region → district → teams", "-", "-", "I4", "F41 F42 F43 F44 F47 F49", "dim_facility", "hcm_stock_flow"),
    ("K26", "Inventory (map)", "Stock movements map", "Lines between sending and receiving stores", "-", "-", "I4", "F41 F42 F43 F44 F47", "dim_facility latitude/longitude", "hcm_stock_arcs"),
    ("K27", "Inventory", "AD syringes in hand", "As K20 for ADS_05 + ADS_01", "-", "-", "I4", "F40 F41 F42 F43", "-", "hcm_stock_position"),
    ("K28", "Data Quality", "Records without GPS", "Delivery records with no latitude", "Records missing F05", "Delivery records", "I1", "F01 F05", "-", "hcm_dq_district"),
    ("K29", "Data Quality", "GPS accuracy > 100 m", "Records with locationAccuracy > 100", "-", "Delivery records", "I1", "F01 F07", "-", "hcm_dq_district"),
    ("K30", "Data Quality", "GPS outside assigned district", "Point not inside its district polygon (ES geo_shape)", "-", "Delivery records", "I1", "F01 F04", "district polygons", "hcm_dq_district"),
    ("K31", "Data Quality", "Duplicate doses", "Same child + vaccine administered more than once", "Children with >1 dose", "-", "I1", "F01 F10 F11 F15", "-", "hcm_dq_district"),
    ("K32", "Data Quality", "Incomplete registrations", "Registrations missing gender or date of birth", "-", "Registrations", "I2", "F01 F17 F20", "-", "hcm_dq_district"),
    ("K33", "Data Quality", "Off-hours records", "Records with event time 20:00-06:00", "-", "-", "I1", "F01 F02", "-", "hcm_dq_district"),
    ("K34", "Data Quality", "Users > 120 doses / day", "Users with unusually high daily output", "-", "-", "I1", "F02 F03 F11", "dim_user", "hcm_dq_users"),
    ("K35", "Data Quality", "Teams < 20 doses / day", "Teams with very low daily output", "-", "-", "I1", "F01 F02 F11 F18 F19", "-", "hcm_dq_teams"),
    ("K36", "Supervision", "Checklist completion by level", "Checklists submitted ÷ expected (team supervisors 2/day, others 1/day)", "Checklists per supervisor", "Supervisors × per day × days elapsed", "I5", "F03 F60", "dim_user", "hcm_checklist_completion"),
    ("K37", "Supervision", "Checklist findings (% yes)", "Yes answers ÷ checklists, per question", "Yes answers", "Checklists", "I5", "F01 F62 F63 F64 F65 F66 F67 F68 F69 F70 F71 F72 F73", "-", "hcm_checklist_findings"),
    ("K38", "Supervision", "Checklists per day", "Submissions per day by role", "-", "-", "I5", "F01 F02 F60 F61", "-", "hcm_checklist_daily"),
    ("K39", "Supervision (map)", "Checklist locations map", "Where checklists were submitted", "-", "-", "I5", "F01 F05 F06 F60", "-", "hcm_points_checklists"),
    ("K40", "Complaints / Overview", "Complaints, resolved, resolution rate", "Resolved ÷ total complaints", "RESOLVED complaints", "All complaints", "I6", "F01 F02 F81", "-", "hcm_complaints_daily"),
    ("K41", "Complaints", "Average hours to resolve", "Sum of resolution hours ÷ resolved complaints", "-", "-", "I6", "F01 F81 F83", "-", "hcm_complaints_daily"),
    ("K42", "Complaints", "Complaints by type / status / day", "Counts", "-", "-", "I6", "F01 F02 F80 F81 F82", "-", "hcm_complaints_daily"),
    ("K43", "Complaints (map)", "Complaints per 10,000 MR doses", "Complaints ÷ MR doses × 10,000, per district", "Complaints", "MR doses", "I1 I6", "F01 F10 F11 F13", "-", "hcm_map_complaints"),
    ("K44", "Complaints (map)", "Complaint locations map", "Complaints as points", "-", "-", "I6", "F01 F05 F06 F80 F81", "-", "hcm_points_complaints"),
]

CONNECTION = [
    # parameter, file / setting, mock value, notes
    ("Elasticsearch host", "trino/catalog/hcm.properties → elasticsearch.host", "elasticsearch", "Hostname or IP of the HCM ES cluster, as reachable from the Trino container."),
    ("Elasticsearch port", "hcm.properties → elasticsearch.port", "9200", ""),
    ("TLS (https)?", "hcm.properties → elasticsearch.tls.enabled", "false", "true if the cluster URL starts with https://"),
    ("Verify TLS hostname?", "hcm.properties → elasticsearch.tls.verify-hostnames", "(not set)", "Set false only for self-signed certificates on a private network."),
    ("Authentication", "hcm.properties → elasticsearch.security", "(none)", "PASSWORD for basic auth; leave empty if open inside the network."),
    ("ES user name", "hcm.properties → elasticsearch.auth.user", "(none)", "Read-only user is enough."),
    ("ES password", "hcm.properties → elasticsearch.auth.password", "(none)", "DO NOT type the password in this sheet. Put it only in hcm.properties on the server (never commit it)."),
    ("Index / alias prefix", "tools/hcm_datasets.py → IDX", "(none)", "If HCM indexes are tenant- or campaign-prefixed (e.g. na-project-task-index-v1), note the prefix."),
    ("Document root object", "tools/hcm_datasets.py → F()", "Data", "Mock docs nest fields under 'Data'. If real docs differ, write the root here (or 'none')."),
    ("Campaign / project filter", "tools/hcm_datasets.py (add a term filter)", "(none - mock has one campaign)", "If the indexes hold several campaigns, which field + value identifies NAM-09-01-IPV-MR_NID?"),
    ("Time zone of eventTime", "tools/hcm_datasets.py → DAY", "Local time (UTC+2)", "UTC or local? Affects day boundaries and off-hours flags."),
    ("Campaign start date", "tools/hcm_datasets.py → CAMPAIGN_START", "2026-11-09", "Confirm."),
    ("Campaign length (days)", "tools/hcm_datasets.py → CAMPAIGN_DAYS", "11", "Confirm."),
    ("Superset URL", "(server)", "http://localhost:8088", "Where the dashboard will be hosted."),
]

CHECKLIST = [
    ("Fill sheet 1 (Connection) - except the password", "Colleague", "Sheet 1"),
    ("Fill sheet 2 (Indexes): real index name for I1-I7", "Colleague", "Sheet 2"),
    ("Edit trino/catalog/hcm.properties on the server, then: docker compose restart trino", "Colleague", "README → Going live"),
    ("Check Trino sees the indexes: docker compose exec trino trino --execute \"SHOW TABLES FROM hcm.default\"", "Colleague", "Every real index from sheet 2 should be listed"),
    ("Look at one real document per index (query in sheet 2, column G) and fill sheet 3 (Fields)", "Colleague", "Sheet 3"),
    ("Fill sheet 4 (Value codes): the real HCM value for each dashboard code", "Colleague", "Sheet 4"),
    ("Check KPI readiness on sheet 5: 'Fields not yet mapped' should be 0 for every KPI", "Colleague", "Sheet 5"),
    ("Update IDX, F() and value codes in tools/hcm_datasets.py from sheets 2-4 (or send this workbook back to the developer)", "Developer", "tools/hcm_datasets.py"),
    ("Load real microplan + facility ids + user ids: tools/load_microplan.py", "Developer", "Sheet 6"),
    ("Regenerate and test datasets: tools/hcm_datasets.py, then tools/test_datasets.sh (every dataset returns rows)", "Developer", "-"),
    ("Rebuild the dashboard: tools/build_superset.py", "Developer", "-"),
    ("Spot-check 3 KPIs against HCM's own reports (e.g. doses for one district on one day)", "Both", "Sheet 5, column N"),
]

MICROPLAN = [
    ("dim_district", "Boundary List", "boundary_code, region, district, under-5 population, IPV target, MR target, team counts", "Targets for every coverage KPI. Codes must match F01."),
    ("dim_district_polygon", "data/districts.geojson", "District shapes for choropleths and K30", "Approximate today - replace with official health-district shapes if available."),
    ("dim_facility", "Facilities List", "Store id, name, type (national / regional / district), capacity, latitude, longitude", "Store ids must match F40 / F44 / F47. Coordinates are mock (district towns) - add real ones."),
    ("dim_user", "User List (roles + boundary only - no names or phones)", "User id, role, boundary", "User ids must match F03. The mock generates ids; real HCM user UUIDs are needed."),
    ("dim_product", "tools/load_microplan.py (PRODUCTS)", "Product code, doses per vial, eligible ages, planned wastage", "Confirm vial sizes: MR 10 doses, fIPV 25 fractional doses."),
    ("dim_campaign_day", "tools/load_microplan.py", "Campaign days and planned cumulative %", "Linear plan over 11 days unless a daily plan is provided."),
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
          "Fill this in to connect the Superset dashboard to the real HCM Elasticsearch. Every KPI on the dashboard is listed with the exact ES fields it needs.")
    rows = [
        ("How to use", ""),
        ("1", "Sheet 1 Connection - where the ES cluster is (no passwords here)."),
        ("2", "Sheet 2 Indexes - the real HCM index name for each of the 7 data sources."),
        ("3", "Sheet 3 Fields - for each field the dashboard reads, the real HCM field path (or what transform is needed)."),
        ("4", "Sheet 4 Value codes - the real HCM value for each code the dashboard filters on (e.g. what HCM calls 'administered')."),
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
        ("Indexes mapped", "=COUNTIF('2 Indexes'!$H$6:$H$12,\"Mapped*\")&\" of \"&COUNTA('2 Indexes'!$A$6:$A$12)"),
        ("Fields mapped", "=COUNTIF('3 Fields'!$K$6:$K$100,\"Mapped*\")&\" of \"&COUNTA('3 Fields'!$A$6:$A$100)"),
        ("Fields needing a transform", "=COUNTIF('3 Fields'!$K$6:$K$100,\"Needs transform\")"),
        ("Fields not available in HCM", "=COUNTIF('3 Fields'!$K$6:$K$100,\"Not available in HCM\")"),
        ("Value codes mapped", "=COUNTIF('4 Value codes'!$G$6:$G$100,\"Mapped*\")&\" of \"&COUNTA('4 Value codes'!$C$6:$C$100)"),
        ("KPIs ready (all fields mapped)", "=COUNTIF('5 KPIs'!$L$5:$L$100,0)&\" of \"&COUNTA('5 KPIs'!$A$5:$A$100)"),
        ("", ""),
        ("Contact", "Questions about a field or KPI: send this workbook back with notes in the 'Notes' columns."),
        ("Note", "All figures in the current dashboard are synthetic test data. Field names in column 'Dashboard expects' are what the mock data uses today."),
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
    hdr = ["Parameter", "Where it goes", "Current value (mock)", "Your value", "Notes"]
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
    title(ws, "2 · Indexes", "The 7 Elasticsearch indexes (or aliases) the dashboard reads. Fill the real HCM name and status.")
    hdr = ["Id", "Data source", "What one document is", "Dashboard expects (mock index)", "Real HCM index / alias", "Approx. doc count", "Check query (Trino)", "Status", "Notes"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    ex = ["EX", "Delivery tasks", "One document per child per vaccine", "project-task-index-v1", "na-project-task-index-v1", 1250000,
          'SELECT * FROM hcm.default."na-project-task-index-v1" LIMIT 5', "Mapped - different name", "Example row - format only"]
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
    status_validation(ws, "H6:H12")
    status_colors(ws, "H6:H12", "H", 6)
    widths(ws, [6, 22, 40, 28, 32, 14, 52, 24, 60])
    ws.freeze_panes = "C6"

    # ---- 3 Fields
    ws = wb.create_sheet("3 Fields")
    title(ws, "3 · Fields", "Every field the dashboard reads, by index. Paths are relative to the document root (mock: Data.<field>). Fill the yellow columns.")
    hdr = ["Id", "Index", "Dashboard expects (field path)", "ES type", "Meaning / format", "Example value", "Used by KPIs",
           "Real HCM field path", "Real example value", "Transform needed (if any)", "Status", "Notes"]
    for c, h in enumerate(hdr, 1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(hdr))
    ex = ["EX", "I1", "productCode", "keyword", "Vaccine code", "MR", "K01 K02", "Data.productVariantId", "PVAR-MR-10D",
          "Map PVAR-MR-10D → MR, PVAR-IPV-F → IPV", "Needs transform", "Example row - format only"]
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
    ex = ["EX", "administrationStatus", "ADMINISTRATION_SUCCESS", "Dose given", "DELIVERED", "Example row - format only", "Mapped - different name"]
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

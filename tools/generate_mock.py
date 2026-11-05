"""Generate HCM-shaped mock events for the Namibia IPV+MR campaign into Elasticsearch.

Simulates days 1-6 (9-14 Nov 2026) of the 11-day campaign against the real
microplan targets in Postgres. Every event carries GPS, boundary hierarchy,
user and timestamps, mirroring HCM ES transformer documents ({"Data": {...}}).

Indexes (swap names in sql/datasets/*.sql if real HCM index names differ):
  project-task-index-v1   one doc per child per product (MR / IPV) delivery attempt
  individual-index-v1     registered children
  household-index-v1      households registered house-to-house
  stock-index-v1          stock transactions (stores and teams)
  service-task-v1         supervisor checklists
  pgr-services-index-v1   complaints
  downsync-index-v1       user downsync events

Deliberate data-quality noise: missing/low-accuracy GPS, points outside the
assigned district, duplicates, incomplete records, off-hours submissions,
users who never sync, store receipt discrepancies.
"""
import datetime as dt
import http.client
import json
import math
import random
import sys
import uuid
from pathlib import Path

import psycopg2
from shapely.geometry import shape, Point
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parent.parent
PG = dict(host="localhost", port=5433, user="hcm", password="hcm", dbname="microplan")
ES_HOST, ES_PORT = "localhost", 9200
SIM_DAYS = 6
START = dt.datetime(2026, 11, 9)
CAMPAIGN_DAYS = 11
TZ_OFFSET = dt.timedelta(hours=2)  # Namibia CAT
PROJECT = {"projectId": "NAM-IPV-MR-2026", "projectName": "Namibia IPV-MR Integrated Campaign 2026",
           "campaignNumber": "NAM-09-01-IPV-MR_NID", "tenantId": "na"}
DPV = {"MR": 10, "IPV": 25}
rnd = random.Random(20261109)

INDEXES = {
    "project-task-index-v1": {
        "productName": "keyword", "productCode": "keyword", "productVariant": "keyword",
        "administrationStatus": "keyword", "reasonNotAdministered": "keyword",
        "deliveryMode": "keyword", "teamId": "keyword", "teamType": "keyword",
        "individualId": "keyword", "householdId": "keyword", "ageInMonths": "integer",
        "gender": "keyword", "quantity": "integer", "isCoAdministered": "boolean"},
    "individual-index-v1": {
        "individualId": "keyword", "householdId": "keyword", "ageInMonths": "integer",
        "dateOfBirth": "date", "gender": "keyword", "deliveryMode": "keyword",
        "eligibleMR": "boolean", "eligibleIPV": "boolean"},
    "household-index-v1": {
        "householdId": "keyword", "memberCount": "integer", "childrenUnder10": "integer",
        "deliveryMode": "keyword", "visitOutcome": "keyword"},
    "stock-index-v1": {
        "transactionId": "keyword", "productCode": "keyword", "productName": "keyword",
        "transactionType": "keyword", "transactionReason": "keyword", "quantity": "integer",
        "dosesPerUnit": "integer", "senderId": "keyword", "senderName": "keyword", "senderType": "keyword",
        "receiverId": "keyword", "receiverName": "keyword", "receiverType": "keyword",
        "facilityId": "keyword", "facilityName": "keyword", "facilityLevel": "keyword", "waybillNumber": "keyword"},
    "service-task-v1": {
        "serviceId": "keyword", "checklistName": "keyword", "supervisorRole": "keyword",
        "visitedTeamId": "keyword", "totalQuestions": "integer", "answeredQuestions": "integer",
        "qColdChainOk": "boolean", "qVvmOk": "boolean", "qOpenVialLabelled": "boolean",
        "qCorrectSyringe": "boolean", "qSafetyBoxUsed": "boolean", "qAgeScreening": "boolean",
        "qFingerMarking": "boolean", "qTallyMatchesApp": "boolean", "qTeamComplete": "boolean",
        "qSocialMobilisation": "boolean"},
    "pgr-services-index-v1": {
        "serviceRequestId": "keyword", "serviceCode": "keyword", "complaintType": "keyword",
        "applicationStatus": "keyword", "source": "keyword", "resolvedTime": "date",
        "resolutionHours": "float"},
    "downsync-index-v1": {"recordsDownloaded": "integer"},
}
COMMON = {"id": "keyword", "clientReferenceId": "keyword", "tenantId": "keyword", "projectId": "keyword",
          "projectName": "keyword", "campaignNumber": "keyword",
          "latitude": "double", "longitude": "double", "geoPoint": "geo_point", "locationAccuracy": "float",
          "createdBy": "keyword", "userRole": "keyword", "createdTime": "long", "syncedTime": "long",
          "eventTime": "date", "syncedDate": "date",
          "boundaryHierarchy": {"properties": {"country": {"type": "keyword"}, "region": {"type": "keyword"},
                                               "district": {"type": "keyword"}}},
          "boundaryHierarchyCode": {"properties": {"district": {"type": "keyword"}}}}


# ---------------------------------------------------------------- ES plumbing
class Bulk:
    def __init__(self):
        self.conn = http.client.HTTPConnection(ES_HOST, ES_PORT, timeout=300)
        self.buf, self.n, self.counts = [], 0, {}

    def req(self, method, path, body=None):
        self.conn.request(method, path, body=body, headers={"Content-Type": "application/x-ndjson"})
        r = self.conn.getresponse()
        data = r.read()
        if r.status >= 300:
            raise RuntimeError(f"{method} {path} -> {r.status} {data[:500]}")
        return json.loads(data or b"{}")

    def add(self, index, data):
        self.buf.append(json.dumps({"index": {"_index": index}}))
        self.buf.append(json.dumps({"Data": data}, default=str))
        self.counts[index] = self.counts.get(index, 0) + 1
        if len(self.buf) >= 10000:
            self.flush()

    def flush(self):
        if not self.buf:
            return
        res = self.req("POST", "/_bulk", ("\n".join(self.buf) + "\n").encode())
        if res.get("errors"):
            bad = next(i for i in res["items"] if "error" in i["index"])
            raise RuntimeError(bad)
        self.n += len(self.buf) // 2
        self.buf = []
        print(f"\r  indexed {self.n:,}", end="", file=sys.stderr)


def setup_indexes(es):
    for name, fields in INDEXES.items():
        try:
            es.req("DELETE", f"/{name}")
        except RuntimeError:
            pass
        props = {k: (v if isinstance(v, dict) else {"type": v}) for k, v in COMMON.items()}
        props.update({k: {"type": v} for k, v in fields.items()})
        body = {"settings": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": "-1"},
                "mappings": {"properties": {"Data": {"properties": props}}}}
        es.req("PUT", f"/{name}", json.dumps(body).encode())


# ---------------------------------------------------------------- helpers
def ms(t_local):
    return int((t_local - TZ_OFFSET).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def stamp(d, t_local, user, role, lat, lon, acc, sync_lag_h=None):
    lag = dt.timedelta(hours=sync_lag_h if sync_lag_h is not None else rnd.expovariate(1 / 2.5))
    st = t_local + lag
    d.update(PROJECT)
    d.update({
        "id": uuid.UUID(int=rnd.getrandbits(128)).hex, "clientReferenceId": uuid.UUID(int=rnd.getrandbits(128)).hex,
        "latitude": lat, "longitude": lon, "locationAccuracy": acc,
        "geoPoint": {"lat": lat, "lon": lon} if lat is not None else None,
        "createdBy": user, "userRole": role, "createdTime": ms(t_local), "syncedTime": ms(st),
        "eventTime": t_local.isoformat(timespec="seconds"), "syncedDate": st.date().isoformat(),
    })
    return d


def gps(base_lat, base_lon, spread, dist):
    """Point near base with HCM-like noise: 1.5% missing, 4% low accuracy, 0.8% outside district."""
    u = rnd.random()
    if u < 0.015:
        return None, None, None
    lat = base_lat + rnd.gauss(0, spread)
    lon = base_lon + rnd.gauss(0, spread)
    if u < 0.023:  # wrongly placed: shifted well outside
        ang = rnd.random() * 2 * math.pi
        lat, lon = lat + 0.6 * math.sin(ang), lon + 0.6 * math.cos(ang)
    acc = rnd.uniform(150, 2500) if u > 0.96 else rnd.uniform(3, 40)
    return round(lat, 6), round(lon, 6), round(acc, 1)


def sample_in(poly_prep, bounds, n, near=None, near_w=0.0):
    pts = []
    minx, miny, maxx, maxy = bounds
    while len(pts) < n:
        if near and rnd.random() < near_w:
            x, y = near[1] + rnd.gauss(0, 0.06), near[0] + rnd.gauss(0, 0.06)
        else:
            x, y = rnd.uniform(minx, maxx), rnd.uniform(miny, maxy)
        if poly_prep.contains(Point(x, y)):
            pts.append((y, x))
    return pts


def work_time(day, early=8, late=17):
    h = rnd.uniform(early, late)
    if rnd.random() < 0.01:  # off-hours submission (data-quality flag)
        h = rnd.choice([rnd.uniform(0, 5), rnd.uniform(21, 23.5)])
    return START + dt.timedelta(days=day, hours=h)


# ---------------------------------------------------------------- main
def main():
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("select boundary_code, region, district, ipv_target, mr_target, teams_fixed, teams_temp_fixed, "
                "teams_mobile, seat_lat, seat_lon, geojson from dim_district order by boundary_code")
    districts = [dict(zip(("code", "region", "district", "ipv", "mr", "tf", "tt", "tm", "slat", "slon", "geo"),
                          [float(x) if hasattr(x, "as_tuple") else x for x in r]))
                 for r in cur.fetchall()]
    cur.execute("select user_id, role_group, boundary_code, region, district from dim_user")
    users = cur.fetchall()
    cur.execute("select facility_code, facility_name, facility_type, level, boundary_code, region, district, "
                "latitude, longitude from dim_facility")
    facs = [dict(zip(("id", "name", "type", "level", "code", "region", "district", "lat", "lon"), r))
            for r in cur.fetchall()]

    es = Bulk()
    setup_indexes(es)
    bh = lambda d: {"boundaryHierarchy": {"country": "Namibia", "region": d["region"], "district": d["district"]},
                    "boundaryHierarchyCode": {"district": d["code"]}}

    by_dist = {}
    for u in users:
        by_dist.setdefault(u[2], {}).setdefault(u[1], []).append(u[0])
    by_region_role = {}
    for u in users:
        by_region_role.setdefault((u[3], u[1]), []).append(u[0])

    # 7% of frontline users never sync -> not in ES
    silent = {u[0] for u in users if (u[1] in ("VACCINATOR", "REGISTRAR") and rnd.random() < 0.07)
              or (u[1].endswith("SUPERVISOR") and rnd.random() < 0.06)}

    consumption = {}  # (district code, product, day) -> doses administered
    stockout_districts = set(rnd.sample([d["code"] for d in districts], 3))

    for d in districts:
        print(f"\n{d['district']}", end="", file=sys.stderr)
        g = shape(json.loads(d["geo"]))
        gp, b = prep(g.buffer(-0.02) if g.buffer(-0.02).area > 0.05 else g), g.bounds
        perf = rnd.uniform(0.62, 1.22)
        vacc = [u for u in by_dist.get(d["code"], {}).get("VACCINATOR", []) if u not in silent] or ["NAM-U-X"]
        regs = [u for u in by_dist.get(d["code"], {}).get("REGISTRAR", []) if u not in silent] or vacc
        tf, tt, tm = int(d["tf"]), int(d["tt"]), int(d["tm"])
        teams = ([("FIXED_POST", "Fixed health facility")] * tf + [("TRANSIT_POST", "Temporary fixed")] * tt +
                 [("HOUSE_TO_HOUSE", "Mobile/outreach")] * tm)
        team_sites = []
        fixed_pts = sample_in(gp, b, max(tf, 1), (d["slat"], d["slon"]), 0.5)
        transit_pts = sample_in(gp, b, max(tt, 1), (d["slat"], d["slon"]), 0.8)
        for k, (mode, ttype) in enumerate(teams):
            members = vacc[k::len(teams)] or [rnd.choice(vacc)]
            if mode == "FIXED_POST":
                site = fixed_pts[k % len(fixed_pts)]
            elif mode == "TRANSIT_POST":
                site = transit_pts[k % len(transit_pts)]
            else:
                site = None
            team_sites.append(dict(team=f"{d['code']}_T{k + 1:02d}", mode=mode, ttype=ttype, members=members,
                                   site=site, weight={"FIXED_POST": 1.2, "TRANSIT_POST": 1.0, "HOUSE_TO_HOUSE": 0.9}[mode]))
        settlements = sample_in(gp, b, 50, (d["slat"], d["slon"]), 0.35)
        tw = [t["weight"] for t in team_sites]

        ipv_only = d["ipv"] * 5 / 56
        both = d["ipv"] * 51 / 56
        mr_only = max(d["mr"] - both, 0)
        total = ipv_only + both + mr_only
        bands = [(4, 8, ipv_only), (9, 59, both), (60, 119, mr_only)]
        prev_children = []

        for day in range(SIM_DAYS):
            dayfac = [0.72, 0.9, 1.0, 1.05, 1.02, 0.98][day] * rnd.uniform(0.9, 1.1)
            n_children = int(total / CAMPAIGN_DAYS * perf * dayfac)
            hh = None
            for _ in range(n_children):
                team = rnd.choices(team_sites, tw)[0]
                vaccinator = rnd.choice(team["members"])
                t = work_time(day)
                if team["mode"] == "HOUSE_TO_HOUSE":
                    if hh is None or hh["left"] <= 0 or hh["team"] != team["team"]:
                        s = rnd.choice(settlements)
                        lat, lon, acc = gps(s[0], s[1], 0.012, d)
                        hh = dict(id="HH-" + uuid.UUID(int=rnd.getrandbits(128)).hex[:12], left=rnd.randint(1, 3),
                                  team=team["team"], lat=lat, lon=lon, acc=acc, t=t)
                        es.add("household-index-v1", stamp({
                            "householdId": hh["id"], "memberCount": rnd.randint(3, 9),
                            "childrenUnder10": hh["left"], "deliveryMode": "HOUSE_TO_HOUSE",
                            "visitOutcome": "VISITED", **bh(d)}, t, vaccinator, "DISTRIBUTOR", lat, lon, acc))
                        if rnd.random() < 0.05:  # household found closed / refused
                            es.add("household-index-v1", stamp({
                                "householdId": "HH-" + uuid.UUID(int=rnd.getrandbits(128)).hex[:12],
                                "memberCount": rnd.randint(2, 7), "childrenUnder10": rnd.randint(1, 2),
                                "deliveryMode": "HOUSE_TO_HOUSE",
                                "visitOutcome": rnd.choice(["CLOSED_HOUSEHOLD", "REFUSED", "CHILD_ABSENT"]), **bh(d)},
                                t, vaccinator, "DISTRIBUTOR", *gps(s[0], s[1], 0.012, d)))
                    hh["left"] -= 1
                    lat, lon, acc, hid, registrar = hh["lat"], hh["lon"], hh["acc"], hh["id"], vaccinator
                    t = hh["t"] + dt.timedelta(minutes=rnd.uniform(1, 8))
                else:
                    lat, lon, acc = gps(team["site"][0], team["site"][1], 0.002, d)
                    hid = None
                    registrar = rnd.choice(regs) if rnd.random() < 0.6 else vaccinator
                lo, hi, _ = rnd.choices(bands, [x[2] for x in bands])[0]
                age = rnd.randint(lo, hi)
                gender = rnd.choice(["MALE", "FEMALE"])
                dob = (t - dt.timedelta(days=age * 30.4 + rnd.uniform(0, 30))).date().isoformat()
                if rnd.random() < 0.02:  # incomplete registration
                    if rnd.random() < 0.5:
                        gender = None
                    else:
                        dob = None
                iid = "IND-" + uuid.UUID(int=rnd.getrandbits(128)).hex[:14]
                elig_mr, elig_ipv = 9 <= age <= 119, 4 <= age <= 59
                es.add("individual-index-v1", stamp({
                    "individualId": iid, "householdId": hid, "ageInMonths": age, "dateOfBirth": dob,
                    "gender": gender, "deliveryMode": team["mode"], "eligibleMR": elig_mr,
                    "eligibleIPV": elig_ipv, **bh(d)}, t - dt.timedelta(minutes=2), registrar,
                    "REGISTRAR", lat, lon, acc))
                prods = [p for p, e in (("MR", elig_mr), ("IPV", elig_ipv)) if e]
                for p in prods:
                    u = rnd.random()
                    stockout = d["code"] in stockout_districts and day >= 4 and p == "MR" and u < 0.06
                    if stockout:
                        status, reason = "NOT_ADMINISTERED", "STOCK_OUT"
                    elif u < 0.02:
                        status, reason = "NOT_ADMINISTERED", "REFUSED"
                    elif u < 0.032:
                        status, reason = "NOT_ADMINISTERED", "CONTRAINDICATED_SICK"
                    elif u < 0.037:
                        status, reason = "NOT_ADMINISTERED", "HESITANT_RETURN_LATER"
                    else:
                        status, reason = "ADMINISTRATION_SUCCESS", None
                    doc = {"productName": p, "productCode": p,
                           "productVariant": "MR 10-dose vial" if p == "MR" else "fIPV 0.1 mL ID (25 doses/vial)",
                           "administrationStatus": status, "reasonNotAdministered": reason,
                           "deliveryMode": team["mode"], "teamId": team["team"], "teamType": team["ttype"],
                           "individualId": iid, "householdId": hid, "ageInMonths": age, "gender": gender,
                           "quantity": 1 if status == "ADMINISTRATION_SUCCESS" else 0,
                           "isCoAdministered": len(prods) == 2, **bh(d)}
                    es.add("project-task-index-v1", stamp(doc, t + dt.timedelta(minutes=1), vaccinator,
                                                          "DISTRIBUTOR", lat, lon, acc))
                    if status == "ADMINISTRATION_SUCCESS":
                        key = (d["code"], p, day)
                        consumption[key] = consumption.get(key, 0) + 1
                        if rnd.random() < 0.006:  # duplicate delivery record
                            dup = dict(doc)
                            es.add("project-task-index-v1", stamp(dup, t + dt.timedelta(days=rnd.randint(0, 1) if day < SIM_DAYS - 1 else 0, minutes=30),
                                                                  rnd.choice(vacc), "DISTRIBUTOR", lat, lon, acc))
                prev_children.append(iid)

        # supervisors' checklists
        for day in range(SIM_DAYS):
            for role, per_day, name in (("TEAM_SUPERVISOR", 2, "Team Supervisor Checklist"),
                                        ("DISTRICT_SUPERVISOR", 1, "District Supervisor Checklist")):
                for sup in [s for s in by_dist.get(d["code"], {}).get(role, []) if s not in silent]:
                    for _ in range(per_day):
                        if rnd.random() > (0.85 if role == "TEAM_SUPERVISOR" else 0.75) * min(perf, 1.1):
                            continue
                        team = rnd.choice(team_sites)
                        s = team["site"] or rnd.choice(settlements)
                        add_checklist(es, d, bh, sup, role, name, team["team"], s, day)

        # complaints
        n_c = int(n_children * SIM_DAYS / 1800 * rnd.uniform(0.5, 1.6))
        helpdesk = by_dist.get(d["code"], {}).get("DASHBOARD_VIEWER", ["NAM-HELPDESK"])
        for _ in range(n_c):
            day = rnd.randrange(SIM_DAYS)
            t = work_time(day, 7, 19)
            ctype = rnd.choices(["Household/child not visited", "Vaccine stock-out at site", "Team conduct",
                                 "App or sync problem", "Incentive/payment", "Other"],
                                [30, 12, 10, 22, 16, 10])[0]
            age_h = (START + dt.timedelta(days=SIM_DAYS) - t).total_seconds() / 3600
            res_h = rnd.expovariate(1 / 30)
            status = ("RESOLVED" if res_h < age_h and rnd.random() < 0.9 else
                      rnd.choice(["PENDING_ASSIGNMENT", "PENDING_AT_LME", "REJECTED"]))
            s = rnd.choice(settlements)
            lat, lon, acc = gps(s[0], s[1], 0.01, d)
            es.add("pgr-services-index-v1", stamp({
                "serviceRequestId": f"PGR-{rnd.randint(100000, 999999)}", "serviceCode": ctype.upper()[:20],
                "complaintType": ctype, "applicationStatus": status, "source": rnd.choice(["mobile", "helpdesk"]),
                "resolvedTime": (t + dt.timedelta(hours=res_h)).isoformat(timespec="seconds") if status == "RESOLVED" else None,
                "resolutionHours": round(res_h, 1) if status == "RESOLVED" else None, **bh(d)},
                t, rnd.choice(helpdesk), "HELPDESK_USER", lat, lon, acc))

        # downsync (house-to-house users pull household lists)
        for u in by_dist.get(d["code"], {}).get("VACCINATOR", []):
            if u in silent or rnd.random() < 0.12:
                continue
            for _ in range(rnd.randint(1, 4)):
                t = work_time(rnd.randrange(-1, SIM_DAYS), 6, 9)
                es.add("downsync-index-v1", stamp({"recordsDownloaded": rnd.randint(20, 900), **bh(d)},
                                                  t, u, "DISTRIBUTOR", d["slat"], d["slon"], 25.0, 0))

    # provincial / national supervisors
    for d in districts:
        pass
    regions = sorted({d["region"] for d in districts})
    for day in range(SIM_DAYS):
        for r in regions:
            ds = [d for d in districts if d["region"] == r]
            for role, name in (("PROVINCIAL_SUPERVISOR", "Regional Supervisor Checklist"),
                               ("NATIONAL_SUPERVISOR", "National Supervisor Checklist")):
                for sup in [s for s in by_region_role.get((r, role), []) if s not in silent]:
                    if rnd.random() < 0.7:
                        d = rnd.choice(ds)
                        add_checklist(es, d, bh, sup, role, name, None, (d["slat"], d["slon"]), day)

    generate_stock(es, districts, facs, consumption, bh)
    es.flush()
    for idx in INDEXES:
        es.req("PUT", f"/{idx}/_settings", json.dumps({"index": {"refresh_interval": "5s"}}).encode())
        es.req("POST", f"/{idx}/_refresh")
    print("\n", json.dumps(es.counts, indent=1))


def add_checklist(es, d, bh, sup, role, name, team, site, day):
    t = work_time(day, 9, 16)
    lat, lon, acc = gps(site[0], site[1], 0.003, d)
    qs = {k: rnd.random() < p for k, p in (
        ("qColdChainOk", 0.9), ("qVvmOk", 0.95), ("qOpenVialLabelled", 0.82), ("qCorrectSyringe", 0.93),
        ("qSafetyBoxUsed", 0.88), ("qAgeScreening", 0.86), ("qFingerMarking", 0.9),
        ("qTallyMatchesApp", 0.78), ("qTeamComplete", 0.91), ("qSocialMobilisation", 0.74))}
    total = len(qs)
    answered = total if rnd.random() < 0.9 else rnd.randint(6, total - 1)
    es.add("service-task-v1", stamp({
        "serviceId": "SRV-" + uuid.UUID(int=rnd.getrandbits(128)).hex[:12], "checklistName": name,
        "supervisorRole": role, "visitedTeamId": team, "totalQuestions": total,
        "answeredQuestions": answered, **qs, **bh(d)}, t, sup, role, lat, lon, acc))


def generate_stock(es, districts, facs, consumption, bh):
    """Pre-positioning CMS -> regions -> districts, then daily team issue/return at district stores."""
    cms = next(f for f in facs if f["level"] == 1)
    reg = {f["region"]: f for f in facs if f["level"] == 2}
    dst = {f["code"]: f for f in facs if f["level"] == 3}
    supply_t = START - dt.timedelta(days=9)

    def fac_bh(f):
        return {"boundaryHierarchy": {"country": "Namibia", "region": f["region"], "district": f["district"]},
                "boundaryHierarchyCode": {"district": f["code"]}}

    def tx(f, ttype, prod, qty, t, sender, receiver, reason=None, wb=None):
        es.add("stock-index-v1", stamp({
            "transactionId": "TX-" + uuid.UUID(int=rnd.getrandbits(128)).hex[:12],
            "productCode": prod, "productName": prod, "transactionType": ttype, "transactionReason": reason,
            "quantity": int(qty), "dosesPerUnit": DPV.get(prod, 1),
            "senderId": sender[0], "senderName": sender[1], "senderType": sender[2],
            "receiverId": receiver[0], "receiverName": receiver[1], "receiverType": receiver[2],
            "facilityId": f["id"], "facilityName": f["name"], "facilityLevel": f["type"],
            "waybillNumber": wb, **fac_bh(f)}, t, "WH-" + f["id"], "WAREHOUSE_MANAGER",
            f["lat"], f["lon"], 10.0, rnd.uniform(0.1, 6)))

    W = lambda f: (f["id"], f["name"], "WAREHOUSE")
    need = {}
    for d in districts:
        mrv = math.ceil(d["mr"] * 1.05 / DPV["MR"])
        ipvv = math.ceil(d["ipv"] * 1.05 / DPV["IPV"])
        need[d["code"]] = {"MR": mrv, "IPV": ipvv, "ADS_05": int(d["mr"] * 1.05), "ADS_01": int(d["ipv"] * 1.05),
                           "RUP_5": mrv}
    prods = ["MR", "IPV", "ADS_05", "ADS_01", "RUP_5"]
    tot = {p: sum(n[p] for n in need.values()) for p in prods}
    for p in prods:
        tx(cms, "RECEIVED", p, tot[p] * 1.08, supply_t, ("SUPPLIER", "UNICEF Supply Division", "SUPPLIER"), W(cms))
    for r, rf in reg.items():
        ds = [d for d in districts if d["region"] == r]
        for p in prods:
            q = sum(need[d["code"]][p] for d in ds) * 1.03
            wb = f"WB-{rnd.randint(10000, 99999)}"
            t = supply_t + dt.timedelta(days=2, hours=rnd.uniform(0, 8))
            tx(cms, "DISPATCHED", p, q, t, W(cms), W(rf), wb=wb)
            tx(rf, "RECEIVED", p, q, t + dt.timedelta(hours=rnd.uniform(6, 30)), W(cms), W(rf), wb=wb)
    short = set(rnd.sample(list(dst), 6))
    for d in districts:
        df, rf = dst[d["code"]], reg[d["region"]]
        supply_frac = rnd.uniform(0.62, 0.8) if d["code"] in short else rnd.uniform(0.95, 1.05)
        for p in prods:
            q = int(need[d["code"]][p] * supply_frac)
            wb = f"WB-{rnd.randint(10000, 99999)}"
            t = supply_t + dt.timedelta(days=5, hours=rnd.uniform(0, 8))
            tx(rf, "DISPATCHED", p, q, t, W(rf), W(df), wb=wb)
            lost = int(q * rnd.uniform(0.01, 0.05)) if rnd.random() < 0.15 else 0  # receipt discrepancy
            tx(df, "RECEIVED", p, q - lost, t + dt.timedelta(hours=rnd.uniform(4, 30)), W(rf), W(df), wb=wb)
        # daily issue to teams and evening returns
        mr_w, ipv_w = rnd.uniform(0.03, 0.13), rnd.uniform(0.02, 0.09)
        team_rx = (f"TEAMS_{d['code']}", f"Vaccination teams - {d['district']}", "TEAM")
        for day in range(SIM_DAYS):
            day_t = START + dt.timedelta(days=day)
            for p, w in (("MR", mr_w), ("IPV", ipv_w)):
                doses = consumption.get((d["code"], p, day), 0)
                used_vials = math.ceil(doses * (1 + w) / DPV[p])
                spare = math.ceil(used_vials * rnd.uniform(0.08, 0.2))
                tx(df, "DISPATCHED", p, used_vials + spare, day_t + dt.timedelta(hours=7), W(df), team_rx)
                tx(df, "RETURNED", p, spare, day_t + dt.timedelta(hours=18), team_rx, W(df))
                dev = ("ADS_05", "RUP_5") if p == "MR" else ("ADS_01",)
                for dv in dev:
                    q = used_vials if dv == "RUP_5" else math.ceil(doses * 1.03)
                    sp = math.ceil(q * 0.1)
                    tx(df, "DISPATCHED", dv, q + sp, day_t + dt.timedelta(hours=7), W(df), team_rx)
                    tx(df, "RETURNED", dv, sp, day_t + dt.timedelta(hours=18), team_rx, W(df))
            if rnd.random() < 0.08:
                tx(df, "LOSS", rnd.choice(["MR", "IPV"]), rnd.randint(2, 20), day_t + dt.timedelta(hours=12),
                   W(df), ("LOSS", "Damaged / cold chain break", "LOSS"), reason=rnd.choice(["DAMAGED", "VVM_STAGE_3", "EXPIRED"]))


if __name__ == "__main__":
    main()

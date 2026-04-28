"""Extend the loaded graph with the proposed care-ops, clinical, financial, and
workflow layers, and emit a deterministic question/answer eval set.

Reads the current builder-format graph from data/processed/{nodes,edges}.csv,
appends new entities and edges in place, and writes an evals CSV with ground
truth answers computed directly from the generated data.

Run from project root:
    .venv/bin/python -m src.synthetic.extend_dataset \
        --nodes data/processed/nodes.csv \
        --edges data/processed/edges.csv \
        --eval-out eval/generated_qa.csv \
        --seed 42

Idempotent: if the script detects already-extended types (CareSession, Invoice,
etc.) it refuses unless --force is given. Use --force to regenerate.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Catalogs (kept inline to keep the script self-contained)
# ---------------------------------------------------------------------------

ICD10_DIAGNOSES = [
    ("F03.90",  "Unspecified dementia, without behavioral disturbance"),
    ("G30.9",   "Alzheimer's disease, unspecified"),
    ("I63.9",   "Cerebral infarction, unspecified"),
    ("M81.0",   "Age-related osteoporosis without current pathological fracture"),
    ("E11.9",   "Type 2 diabetes mellitus without complications"),
    ("I50.9",   "Heart failure, unspecified"),
    ("J44.9",   "COPD, unspecified"),
    ("G20",     "Parkinson's disease"),
    ("N39.0",   "Urinary tract infection, site not specified"),
    ("R26.81",  "Unsteadiness on feet"),
    ("F32.9",   "Major depressive disorder, single episode, unspecified"),
    ("S72.001A","Closed fracture of femur, initial encounter"),
]

ADL_NAMES = ["Bathing", "Dressing", "Toileting", "Transferring", "Continence", "Feeding"]

RIDER_CATALOG = [
    ("RDR-IBR",  "Inflation Benefit Rider"),
    ("RDR-WPR",  "Waiver of Premium Rider"),
    ("RDR-NHR",  "Nonforfeiture Rider"),
    ("RDR-SBR",  "Shared Benefit Rider"),
    ("RDR-RPR",  "Return of Premium Rider"),
    ("RDR-COL",  "Cost of Living Rider"),
]

CARE_SETTINGS = ["Home", "AssistedLiving", "Nursing", "AdultDayCare"]

DEVICE_OS = ["iOS 17.4", "iOS 17.5", "Android 13", "Android 14"]
DEVICE_MODELS = [
    "iPhone 12", "iPhone 13", "iPhone 14", "iPhone 15",
    "Pixel 7", "Pixel 8", "Galaxy S22", "Galaxy S23",
]

TRIGGER_METRICS = [
    "DistanceAnomaly", "ManualSessionShare", "DeviceReuse",
    "AgentClaimantOverlap", "CrossClaimProvider", "BankSharing",
]

ICP_FIRST_NAMES = ["MARIA", "JOHN", "SARAH", "DAVID", "JESSICA", "ROBERT",
                   "LINDA", "JAMES", "PATRICIA", "MICHAEL", "ELIZABETH",
                   "WILLIAM", "BARBARA", "RICHARD", "CAROL", "JOSEPH",
                   "SUSAN", "THOMAS", "MARGARET", "CHARLES", "ASHLEY",
                   "DANIEL", "JENNIFER", "MATTHEW", "AMANDA"]

ICP_LAST_NAMES = ["RODRIGUEZ", "MARTINEZ", "JOHNSON", "WILLIAMS", "JONES",
                  "BROWN", "DAVIS", "MILLER", "WILSON", "ANDERSON",
                  "TAYLOR", "THOMAS", "HERNANDEZ", "MOORE", "MARTIN",
                  "JACKSON", "THOMPSON", "WHITE", "LOPEZ", "LEE",
                  "GONZALEZ", "HARRIS", "CLARK", "LEWIS", "ROBINSON"]

HHCA_NAMES = [
    "BLUEBIRD HOME CARE LLC", "EVERGREEN CARE PARTNERS",
    "SUNRISE HOMECARE LLC", "GENTLE HANDS CARE LLC",
    "BEACON HOME HEALTH", "HOMEWARD CAREGIVERS",
    "MERIDIAN HOME CARE", "HARMONY CARE GROUP",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GraphState:
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    node_ids: set[str] = field(default_factory=set)
    edge_id_seq: int = 0

    def add_node(self, node_id: str, node_type: str, label: str,
                 source_table: str, props: dict) -> str:
        if node_id in self.node_ids:
            return node_id
        self.node_ids.add(node_id)
        self.nodes.append({
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
            "source_table": source_table,
            "properties_json": json.dumps(props, default=str),
        })
        return node_id

    def add_edge(self, source: str, target: str, edge_type: str,
                 source_table: str, props: dict | None = None) -> str:
        eid = f"e_ext_{self.edge_id_seq:06d}"
        self.edge_id_seq += 1
        self.edges.append({
            "edge_id": eid,
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": edge_type,
            "source_table": source_table,
            "properties_json": json.dumps(props or {}, default=str),
        })
        return eid


# ---------------------------------------------------------------------------
# Loading existing data
# ---------------------------------------------------------------------------

def load_existing(nodes_path: Path, edges_path: Path) -> tuple[list[dict], list[dict]]:
    nodes = []
    with nodes_path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nodes.append(row)
    edges = []
    with edges_path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            edges.append(row)
    return nodes, edges


def parse_props(node_or_edge: dict) -> dict:
    raw = node_or_edge.get("properties_json") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def index_nodes(nodes: list[dict]) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    for n in nodes:
        by_type.setdefault(n["node_type"], []).append(n)
    return by_type


def claims_with_anchors(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """For each Claim node, attach the linked Policy and the Person(s) covered."""
    by_id = {n["node_id"]: n for n in nodes}
    claim_to_policy: dict[str, str] = {}
    person_to_policy: dict[str, list[str]] = {}
    person_addr: dict[str, str] = {}
    spouse_of: dict[str, list[str]] = {}
    sold_policy_by: dict[str, str] = {}  # policy_id -> agent person
    for e in edges:
        et = e["edge_type"]
        s, t = e["source_node_id"], e["target_node_id"]
        if et == "IS_CLAIM_AGAINST_POLICY":
            claim_to_policy[s] = t
        elif et == "IS_COVERED_BY":
            person_to_policy.setdefault(s, []).append(t)
        elif et == "LOCATED_IN":
            sn = by_id.get(s)
            if sn and sn["node_type"] == "Person":
                person_addr[s] = t
        elif et == "IS_SPOUSE_OF":
            spouse_of.setdefault(s, []).append(t)
        elif et == "SOLD_POLICY":
            sold_policy_by[t] = s
    policy_to_persons: dict[str, list[str]] = {}
    for person, pols in person_to_policy.items():
        for pol in pols:
            policy_to_persons.setdefault(pol, []).append(person)
    out = []
    for cn in nodes:
        if cn["node_type"] != "Claim":
            continue
        cid = cn["node_id"]
        pol = claim_to_policy.get(cid)
        if not pol:
            continue
        insureds = policy_to_persons.get(pol, [])
        primary = insureds[0] if insureds else None
        out.append({
            "claim_node": cn,
            "claim_id": cid,
            "policy_id": pol,
            "insureds": insureds,
            "primary_insured": primary,
            "primary_address": person_addr.get(primary) if primary else None,
            "spouse_ids": spouse_of.get(primary, []) if primary else [],
            "writing_agent_id": sold_policy_by.get(pol),
        })
    return out


# ---------------------------------------------------------------------------
# Geo helpers (haversine miles)
# ---------------------------------------------------------------------------

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.7613
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def jitter_coord(lat: float, lon: float, miles: float, rng: random.Random) -> tuple[float, float]:
    bearing = rng.uniform(0, 2 * math.pi)
    dlat = (miles / 69.0) * math.cos(bearing)
    dlon = (miles / (69.0 * math.cos(math.radians(lat)))) * math.sin(bearing)
    return lat + dlat, lon + dlon


# ---------------------------------------------------------------------------
# Generators (per layer)
# ---------------------------------------------------------------------------

def _addr_coords(addr_node: dict) -> tuple[float | None, float | None]:
    p = parse_props(addr_node)
    return p.get("LATITUDE"), p.get("LONGITUDE")


def _new_address(state: GraphState, rng: random.Random, near_lat: float, near_lon: float,
                 city_state: str, residence_type: str, idx: int) -> str:
    addr_id = f"address_ext_{idx:05d}"
    new_lat, new_lon = jitter_coord(near_lat, near_lon, rng.uniform(0.5, 8.0), rng)
    city, st = (city_state.split(", ") + ["MA"])[:2]
    state.add_node(
        addr_id, "Address",
        f"{city}, {st}",
        "ext_address",
        {
            "ADDRESS_LINE_1": f"{rng.randint(10, 9999)} {rng.choice(['MAIN','OAK','MAPLE','ELM','CEDAR','BIRCH'])} ST",
            "CITY": city,
            "STATE": st,
            "ZIP_CODE": f"0{rng.randint(1000, 9999)}",
            "LATITUDE": round(new_lat, 6),
            "LONGITUDE": round(new_lon, 6),
            "RESIDENCE_TYPE": residence_type,
        },
    )
    return addr_id


def _new_bank(state: GraphState, rng: random.Random, idx: int) -> str:
    bid = f"bank_ext_{idx:05d}"
    state.add_node(
        bid, "BankAccount",
        f"Bank ext-{idx} (****{rng.randint(1000, 9999)})",
        "ext_bank",
        {
            "ROUTING_NUMBER": str(rng.randint(100000000, 999999999)),
            "ACCOUNT_NUMBER": f"****{rng.randint(1000, 9999)}",
        },
    )
    return bid


def generate_riders_and_benefits(state: GraphState, rng: random.Random,
                                 policy_ids: set[str]) -> None:
    """One or two Riders per policy, plus Benefit nodes per care setting."""
    for pid in policy_ids:
        n_riders = rng.randint(1, 2)
        for k in range(n_riders):
            code, name = rng.choice(RIDER_CATALOG)
            rid = f"rider_{pid.removeprefix('policy_')}_{k}"
            issue = date(2018, 1, 1) + timedelta(days=rng.randint(0, 1500))
            term = issue + timedelta(days=rng.randint(365, 365 * 10))
            state.add_node(rid, "Rider", name, "ext_rider", {
                "RIDER_CODE": code,
                "RIDER_NAME": name,
                "EFFECTIVE_DATE": issue.isoformat(),
                "TERMINATION_DATE": term.isoformat(),
            })
            state.add_edge(pid, rid, "HAS_RIDER", "ext_rider")
        # 3 benefit settings per policy
        for setting in ["Home", "AssistedLiving", "Nursing"]:
            bid = f"benefit_{pid.removeprefix('policy_')}_{setting}"
            dmb = rng.choice([100, 150, 200, 250, 300])
            state.add_node(bid, "Benefit",
                           f"{setting} DMB ${dmb}",
                           "ext_benefit",
                           {
                               "CARE_SETTING": setting,
                               "DAILY_MAX_BENEFIT": dmb,
                               "MONTHLY_MAX_BENEFIT": dmb * 30,
                               "LIFETIME_MAX": dmb * 365 * 5,
                           })
            state.add_edge(pid, bid, "HAS_BENEFIT", "ext_benefit")


def generate_clinical(state: GraphState, rng: random.Random, claim_anchor: dict) -> dict:
    cid = claim_anchor["claim_id"]
    primary = claim_anchor["primary_insured"]
    out = {"diagnoses": [], "mmse": None, "adls": [], "cognitive_impaired": False}

    n_dx = rng.randint(1, 4)
    chosen_dx = rng.sample(ICD10_DIAGNOSES, n_dx)
    for k, (code, desc) in enumerate(chosen_dx):
        did = f"diagnosis_{cid.removeprefix('claim_')}_{k}"
        dx_date = date(2022, 1, 1) + timedelta(days=rng.randint(0, 800))
        state.add_node(did, "Diagnosis", f"{code} - {desc[:40]}", "ext_diagnosis", {
            "DIAGNOSIS_ID": did, "ICD10_CODE": code, "DESCRIPTION": desc,
            "DIAGNOSIS_DATE": dx_date.isoformat(),
        })
        state.add_edge(claim_anchor["claim_node"]["node_id"], did, "HAS_DIAGNOSIS", "ext_diagnosis")
        out["diagnoses"].append((did, code, desc))

    if primary:
        mmse_score = rng.choices(
            [rng.randint(8, 17), rng.randint(18, 23), rng.randint(24, 30)],
            weights=[0.25, 0.40, 0.35],
        )[0]
        cognitive_flag = mmse_score < 24
        aid = f"assessment_{cid.removeprefix('claim_')}_mmse"
        state.add_node(aid, "Assessment", f"MMSE {mmse_score}/30", "ext_assessment", {
            "ASSESSMENT_ID": aid, "ASSESSMENT_TYPE": "MMSE",
            "SCORE": mmse_score, "MAX_SCORE": 30,
            "ASSESSED_DATE": (date(2024, 1, 1) + timedelta(days=rng.randint(0, 365))).isoformat(),
            "COGNITIVE_IMPAIRMENT_FLAG": cognitive_flag,
        })
        state.add_edge(primary, aid, "HAS_ASSESSMENT", "ext_assessment")
        out["mmse"] = (aid, mmse_score, cognitive_flag)
        out["cognitive_impaired"] = cognitive_flag

    n_adls = rng.randint(2, 5)
    for k, name in enumerate(rng.sample(ADL_NAMES, n_adls)):
        adl_id = f"adl_{cid.removeprefix('claim_')}_{k}"
        freq = rng.randint(1, 3)
        state.add_node(adl_id, "ADL", name, "ext_adl", {
            "ADL_ID": adl_id, "NAME": name,
            "IS_PROVIDED": True, "FREQUENCY_PER_DAY": freq,
        })
        state.add_edge(claim_anchor["claim_node"]["node_id"], adl_id, "RECEIVES_ADL", "ext_adl")
        out["adls"].append((adl_id, name, freq))
    return out


def generate_care_ops(state: GraphState, rng: random.Random, claim_anchor: dict,
                      addr_idx: list[int], bank_idx: list[int],
                      person_idx: list[int], device_pool: dict[str, str],
                      hhca_pool: dict[str, str], all_addresses: list[dict],
                      suspicious_motifs: set[str]) -> dict:
    """Create ICPs, an HHCA, sessions, and devices for one claim. Returns a
    summary dict with everything ground-truth derives from."""
    cid = claim_anchor["claim_id"]
    short_cid = cid.removeprefix("claim_")
    primary_addr_id = claim_anchor["primary_address"]
    primary_addr = next((a for a in all_addresses if a["node_id"] == primary_addr_id), None)
    if not primary_addr:
        return {"icps": [], "sessions": [], "agency_id": None}
    plat, plon = _addr_coords(primary_addr)
    if plat is None:
        return {"icps": [], "sessions": [], "agency_id": None}
    p_props = parse_props(primary_addr)
    city_state = f"{p_props.get('CITY','BOSTON')}, {p_props.get('STATE','MA')}"

    # 1) HHCA agency (Business)
    hhca_name = rng.choice(HHCA_NAMES)
    if hhca_name not in hhca_pool:
        hhca_pool[hhca_name] = f"business_ext_hhca_{len(hhca_pool):03d}"
        bid = hhca_pool[hhca_name]
        addr_idx[0] += 1
        agency_addr = _new_address(state, rng, plat, plon, city_state, "Business", addr_idx[0])
        state.add_node(bid, "Business", hhca_name, "ext_hhca", {
            "BUSINESS_NAME": hhca_name,
            "TAX_ID": f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}",
            "BUSINESS_TYPE": "HHCA",
            "BUSINESS_TYPE_EXT": "HHCA",
        })
        state.add_edge(bid, agency_addr, "LOCATED_IN", "ext_hhca")
    agency_id = hhca_pool[hhca_name]
    state.add_edge(agency_id, claim_anchor["claim_node"]["node_id"],
                   "IS_AGENCY_FOR", "ext_hhca",
                   {"AGENCY_TYPE": "HHCA",
                    "CONTRACT_START": "2024-01-01",
                    "CONTRACT_END": "2025-12-31"})

    # 2) ICPs (2 or 3 per claim)
    n_icps = rng.randint(2, 3)
    icps: list[dict] = []
    address_collision = "icp_address_collision" in suspicious_motifs
    for j in range(n_icps):
        person_idx[0] += 1
        pid = f"person_ext_icp_{person_idx[0]:05d}"
        first = rng.choice(ICP_FIRST_NAMES)
        last = rng.choice(ICP_LAST_NAMES)
        state.add_node(pid, "Person", f"{first} {last}", "ext_icp", {
            "RES_PERSON_ID": person_idx[0] + 100000,
            "FIRST_NAME": first, "LAST_NAME": last,
            "BIRTH_DATE": f"{rng.randint(1965, 1995)}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
            "SEX": rng.choice(["M", "F"]),
            "PRIMARY_ROLE": "ICP",
            "LICENSE_NUMBER": f"LIC-{rng.randint(100000, 999999)}",
            "SPECIALTY": rng.choice(["HomeHealth", "PT", "OT", "CNA"]),
        })
        # ICP address: same as claimant only if motif active for first ICP
        if address_collision and j == 0 and primary_addr_id:
            icp_addr = primary_addr_id
        else:
            addr_idx[0] += 1
            icp_addr = _new_address(state, rng, plat, plon, city_state, "Home", addr_idx[0])
        state.add_edge(pid, icp_addr, "LOCATED_IN", "ext_icp")
        # ICP bank
        bank_idx[0] += 1
        ibank = _new_bank(state, rng, bank_idx[0])
        state.add_edge(pid, ibank, "HOLD_BY", "ext_icp")
        # employed by HHCA
        state.add_edge(pid, agency_id, "EMPLOYED_BY", "ext_icp",
                       {"ROLE": "ICP",
                        "HIRE_DATE": "2023-06-01",
                        "TERMINATION_DATE": None})
        # provides care on this claim
        svc_start = date(2024, 1, 1) + timedelta(days=rng.randint(0, 60))
        svc_end = svc_start + timedelta(days=rng.randint(60, 240))
        state.add_edge(pid, claim_anchor["claim_node"]["node_id"],
                       "PROVIDES_CARE_ON", "ext_icp",
                       {"ROLE": "ICP",
                        "SERVICE_START_DATE": svc_start.isoformat(),
                        "SERVICE_END_DATE": svc_end.isoformat(),
                        "AGENCY_BUSINESS_ID": agency_id})
        icps.append({
            "person_id": pid, "name": f"{first} {last}",
            "address_id": icp_addr, "bank_id": ibank,
            "service_start": svc_start, "service_end": svc_end,
        })

    # 3) Sessions (3 months of activity, ~12-25 sessions per ICP)
    sessions: list[dict] = []
    distance_anomaly = "distance_anomaly" in suspicious_motifs
    manual_high_charge = "manual_high_charge" in suspicious_motifs
    device_reuse = "device_reuse" in suspicious_motifs
    shared_device_id = None
    if device_reuse:
        shared_device_id = f"device_shared_{short_cid}"
        if shared_device_id not in device_pool:
            state.add_node(shared_device_id, "Device", f"Device {shared_device_id[-8:]}", "ext_device", {
                "DEVICE_ID": shared_device_id,
                "DEVICE_OS": rng.choice(DEVICE_OS),
                "DEVICE_MODEL": rng.choice(DEVICE_MODELS),
            })
            device_pool[shared_device_id] = shared_device_id

    for icp in icps:
        n_sessions = rng.randint(12, 25)
        # one device per ICP (unless reuse motif active)
        own_device = f"device_{icp['person_id'].split('_')[-1]}"
        if own_device not in device_pool:
            state.add_node(own_device, "Device", f"Device {own_device[-8:]}", "ext_device", {
                "DEVICE_ID": own_device,
                "DEVICE_OS": rng.choice(DEVICE_OS),
                "DEVICE_MODEL": rng.choice(DEVICE_MODELS),
            })
            device_pool[own_device] = own_device
        for s in range(n_sessions):
            sdate = icp["service_start"] + timedelta(days=int(s * 7))
            if sdate > icp["service_end"]:
                break
            check_in = datetime.combine(sdate, datetime.min.time()).replace(
                hour=rng.randint(7, 10), minute=rng.randint(0, 59))
            duration = rng.randint(120, 360)
            check_out = check_in + timedelta(minutes=duration)

            # Geo: usually near policyholder, some far if motif on
            if distance_anomaly and rng.random() < 0.3:
                miles_off = rng.uniform(6, 30)
            else:
                miles_off = rng.uniform(0.0, 1.5)
            in_lat, in_lon = jitter_coord(plat, plon, miles_off, rng)
            out_lat, out_lon = jitter_coord(in_lat, in_lon, rng.uniform(0, 0.3), rng)

            # Device: shared if motif on, else own
            in_device = shared_device_id if (device_reuse and rng.random() < 0.5) else own_device
            out_device = in_device if rng.random() > 0.05 else own_device

            mode = "Manual" if (manual_high_charge and rng.random() < 0.5) else (
                   "Manual" if rng.random() < 0.05 else "Live")

            sid_short = f"S{short_cid}_{icp['person_id'][-5:]}_{s:03d}"
            sid = f"session_{sid_short}"
            state.add_node(sid, "CareSession",
                           f"Session {sdate.isoformat()} {icp['name']}",
                           "ext_session", {
                               "SESSION_ID": sid_short,
                               "CLAIM_ID": cid,
                               "ICP_PERSON_ID": icp["person_id"],
                               "SESSION_DATE": sdate.isoformat(),
                               "CHECK_IN_TS": check_in.isoformat(),
                               "CHECK_OUT_TS": check_out.isoformat(),
                               "CHECK_IN_LAT": round(in_lat, 6),
                               "CHECK_IN_LON": round(in_lon, 6),
                               "CHECK_OUT_LAT": round(out_lat, 6),
                               "CHECK_OUT_LON": round(out_lon, 6),
                               "CHECK_IN_DEVICE_ID": in_device,
                               "CHECK_OUT_DEVICE_ID": out_device,
                               "SUBMISSION_MODE": mode,
                               "DURATION_MINUTES": duration,
                           })
            state.add_edge(icp["person_id"], sid, "LOGGED_SESSION", "ext_session")
            state.add_edge(sid, claim_anchor["claim_node"]["node_id"],
                           "SESSION_FOR_CLAIM", "ext_session")
            state.add_edge(sid, in_device, "USED_DEVICE", "ext_session", {"EVENT": "CheckIn"})
            if out_device != in_device:
                state.add_edge(sid, out_device, "USED_DEVICE", "ext_session", {"EVENT": "CheckOut"})
            else:
                state.add_edge(sid, out_device, "USED_DEVICE", "ext_session", {"EVENT": "CheckOut"})

            sessions.append({
                "session_id": sid, "icp_person_id": icp["person_id"],
                "icp_name": icp["name"],
                "date": sdate, "check_in": check_in, "check_out": check_out,
                "in_lat": in_lat, "in_lon": in_lon,
                "out_lat": out_lat, "out_lon": out_lon,
                "miles_from_addr": haversine_miles(plat, plon, in_lat, in_lon),
                "miles_from_addr_out": haversine_miles(plat, plon, out_lat, out_lon),
                "in_device": in_device, "out_device": out_device,
                "mode": mode, "duration_min": duration,
            })

    return {"icps": icps, "sessions": sessions, "agency_id": agency_id,
            "primary_lat": plat, "primary_lon": plon}


def generate_financial(state: GraphState, rng: random.Random, claim_anchor: dict,
                       care_ops: dict, suspicious_motifs: set[str]) -> dict:
    cid = claim_anchor["claim_id"]
    short_cid = cid.removeprefix("claim_")
    icps = care_ops.get("icps", [])
    sessions = care_ops.get("sessions", [])
    if not icps:
        return {"invoices": [], "total_paid_per_icp": {}, "rate_per_icp": {}}

    # group sessions by ICP
    by_icp: dict[str, list[dict]] = {}
    for s in sessions:
        by_icp.setdefault(s["icp_person_id"], []).append(s)

    high_charges = "manual_high_charge" in suspicious_motifs

    invoices: list[dict] = []
    total_paid_per_icp: dict[str, float] = {}
    rate_per_icp: dict[str, float] = {}
    inv_seq = 0
    for icp in icps:
        rate = round(rng.uniform(45, 65) if high_charges else rng.uniform(28, 50), 2)
        rate_per_icp[icp["person_id"]] = rate
        sess = by_icp.get(icp["person_id"], [])
        # group sessions into monthly invoices
        monthly: dict[str, list[dict]] = {}
        for s in sess:
            key = s["date"].strftime("%Y-%m")
            monthly.setdefault(key, []).append(s)
        for ym, items in sorted(monthly.items()):
            inv_seq += 1
            inv_id = f"invoice_{short_cid}_{icp['person_id'][-5:]}_{ym}"
            total = 0.0
            charge_ids = []
            for k, s in enumerate(items):
                hours = round(s["duration_min"] / 60.0, 2)
                line = round(hours * rate, 2)
                total += line
                cid2 = f"charge_{inv_id.removeprefix('invoice_')}_{k}"
                state.add_node(cid2, "Charge", f"{hours}h @ ${rate}", "ext_charge", {
                    "CHARGE_ID": cid2,
                    "LINE_ITEM_DATE": s["date"].isoformat(),
                    "HOURS_BILLED": hours,
                    "HOURLY_RATE": rate,
                    "LINE_AMOUNT": line,
                    "SERVICE_CODE": "T1019",
                })
                state.add_edge(inv_id, cid2, "HAS_CHARGE", "ext_charge")
                charge_ids.append(cid2)
            year, month = ym.split("-")
            month_start = date(int(year), int(month), 1)
            state.add_node(inv_id, "Invoice", f"Invoice {ym} {icp['name']}", "ext_invoice", {
                "INVOICE_ID": inv_id,
                "CLAIM_ID": cid,
                "BILLING_PERIOD_START": month_start.isoformat(),
                "BILLING_PERIOD_END": (month_start + timedelta(days=27)).isoformat(),
                "TOTAL_AMOUNT": round(total, 2),
                "SUBMISSION_DATE": (month_start + timedelta(days=30)).isoformat(),
                "STATUS": "Paid",
            })
            state.add_edge(inv_id, claim_anchor["claim_node"]["node_id"],
                           "BILLED_ON", "ext_invoice")
            state.add_edge(inv_id, icp["person_id"], "INVOICED_BY", "ext_invoice",
                           {"PROVIDER_ROLE": "ICP"})
            # payment
            pay_id = f"payment_{inv_id.removeprefix('invoice_')}"
            pay_date = month_start + timedelta(days=30 + rng.randint(2, 14))
            state.add_node(pay_id, "Payment", f"Pay {round(total,2)} {icp['name']}", "ext_payment", {
                "PAYMENT_ID": pay_id,
                "PAYMENT_DATE": pay_date.isoformat(),
                "AMOUNT": round(total, 2),
                "PAYMENT_METHOD": "ACH",
                "STATUS": "Paid",
            })
            state.add_edge(pay_id, inv_id, "SETTLES_INVOICE", "ext_payment")
            state.add_edge(pay_id, icp["person_id"], "PAID_TO", "ext_payment")
            state.add_edge(pay_id, icp["bank_id"], "PAID_VIA", "ext_payment")
            total_paid_per_icp[icp["person_id"]] = total_paid_per_icp.get(icp["person_id"], 0) + round(total, 2)
            invoices.append({
                "invoice_id": inv_id, "icp_id": icp["person_id"],
                "month": ym, "total": round(total, 2),
                "payment_id": pay_id, "n_charges": len(charge_ids),
            })
    return {"invoices": invoices, "total_paid_per_icp": total_paid_per_icp,
            "rate_per_icp": rate_per_icp}


def generate_workflow(state: GraphState, rng: random.Random, claim_anchor: dict,
                      care_ops: dict, suspicious_motifs: set[str]) -> dict:
    """About 12% of claims get a review cycle; suspicious motifs always do."""
    if not suspicious_motifs and rng.random() > 0.12:
        return {"cycle": None}
    cid = claim_anchor["claim_id"]
    short_cid = cid.removeprefix("claim_")
    cyc_id = f"review_{short_cid}"
    opened = date(2024, 6, 1) + timedelta(days=rng.randint(0, 200))
    is_open = rng.random() < 0.35
    closed = None if is_open else opened + timedelta(days=rng.randint(20, 90))
    status = "Open" if is_open else rng.choice(["Cleared", "Escalated", "Remediated"])
    state.add_node(cyc_id, "ReviewCycle", f"Review {short_cid} {status}", "ext_review", {
        "CYCLE_ID": cyc_id, "CLAIM_ID": cid,
        "OPENED_DATE": opened.isoformat(),
        "CLOSED_DATE": closed.isoformat() if closed else None,
        "STATUS": status,
        "OUTCOME": "" if is_open else f"{status} after review",
    })
    state.add_edge(claim_anchor["claim_node"]["node_id"], cyc_id, "HAS_REVIEW_CYCLE", "ext_review")
    # trigger metrics
    metric_names = list(suspicious_motifs) if suspicious_motifs else [rng.choice(TRIGGER_METRICS)]
    metric_map = {
        "icp_address_collision": "AgentClaimantOverlap",
        "device_reuse": "DeviceReuse",
        "distance_anomaly": "DistanceAnomaly",
        "manual_high_charge": "ManualSessionShare",
        "agency_bank_share": "BankSharing",
    }
    triggered = []
    for k, mn in enumerate(metric_names[:3]):
        m_id = f"metric_{short_cid}_{k}"
        name = metric_map.get(mn, mn if mn in TRIGGER_METRICS else "DistanceAnomaly")
        val = round(rng.uniform(0.6, 0.95), 3)
        thr = round(rng.uniform(0.3, 0.55), 3)
        state.add_node(m_id, "TriggerMetric", f"{name} {val}", "ext_metric", {
            "METRIC_ID": m_id, "NAME": name,
            "VALUE": val, "THRESHOLD": thr,
            "TRIGGERED_DATE": opened.isoformat(),
        })
        state.add_edge(m_id, cyc_id, "TRIGGERED", "ext_metric")
        triggered.append(name)
    rem = None
    if status == "Remediated":
        rem_id = f"remediation_{short_cid}"
        amount = round(rng.uniform(2000, 20000), 2)
        state.add_node(rem_id, "Remediation", f"Recovery ${amount}", "ext_remediation", {
            "REMEDIATION_ID": rem_id,
            "ACTION_TYPE": "Recovery",
            "RECOVERY_AMOUNT": amount,
            "COMPLETION_DATE": (closed + timedelta(days=14)).isoformat() if closed else None,
        })
        state.add_edge(cyc_id, rem_id, "HAS_REMEDIATION", "ext_remediation")
        rem = (rem_id, amount)
    return {"cycle": (cyc_id, status, is_open, closed),
            "triggered": triggered, "remediation": rem}


# ---------------------------------------------------------------------------
# Eval set construction
# ---------------------------------------------------------------------------

def build_eval_rows(claim_anchor: dict, clinical: dict, care_ops: dict,
                    financial: dict, workflow: dict, all_addresses: list[dict],
                    name_lookup: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    cid = claim_anchor["claim_id"]
    cn = claim_anchor["claim_node"]
    cprops = parse_props(cn)
    claim_number = cprops.get("CLAIM_NUMBER", cid)
    primary = claim_anchor["primary_insured"]
    primary_name = name_lookup.get(primary or "", "")

    def add(qid: str, qtemplate: str, ans_type: str, ans_value, evidence: list[str], notes: str = ""):
        rows.append({
            "qid": qid, "claim_node_id": cid, "claim_number": claim_number,
            "question_template": qtemplate,
            "question_text": qtemplate.replace("XYZ", str(claim_number)),
            "expected_answer_type": ans_type,
            "expected_answer": json.dumps(ans_value, default=str) if not isinstance(ans_value, str) else ans_value,
            "evidence_node_ids": ";".join(evidence),
            "notes": notes,
        })

    # Q1 policyholder
    add("Q1", "Who is the policyholder for claim XYZ?",
        "string",
        primary_name or (primary or ""),
        [primary] if primary else [])

    # Q5 writing agent
    wa = claim_anchor["writing_agent_id"]
    add("Q5", "Who is the writing agent that sold the policy associated with claim XYZ?",
        "string",
        name_lookup.get(wa or "", wa or "Unknown"),
        [wa] if wa else [])

    # Q7 spouse exists
    spouses = claim_anchor.get("spouse_ids", []) or []
    add("Q7", "Does the claimant on claim XYZ have a spouse?",
        "bool",
        bool(spouses),
        spouses)

    # Q11 providers (ICP names)
    icp_names = [i["name"] for i in care_ops.get("icps", [])]
    icp_ids = [i["person_id"] for i in care_ops.get("icps", [])]
    add("Q11", "Who are all the providers (ICPs, agencies) associated with claim XYZ?",
        "list", icp_names + ([care_ops.get("agency_id")] if care_ops.get("agency_id") else []),
        icp_ids + ([care_ops.get("agency_id")] if care_ops.get("agency_id") else []))

    # Q12 ICPs only
    add("Q12", "Who are the individual care providers (ICPs) on claim XYZ?",
        "list", icp_names, icp_ids)

    # Q15 service dates
    add("Q15", "When did each provider begin and end their service on claim XYZ?",
        "list",
        [{"icp": i["name"], "start": str(i["service_start"]), "end": str(i["service_end"])}
         for i in care_ops.get("icps", [])],
        icp_ids)

    # Q17 furthest check-out distance
    sessions = care_ops.get("sessions", [])
    if sessions:
        s_max = max(sessions, key=lambda s: s["miles_from_addr_out"])
        add("Q17", "What is the care session with the furthest check-out from the insured's address on claim XYZ?",
            "object",
            {"session_id": s_max["session_id"],
             "icp": s_max["icp_name"],
             "miles_from_address": round(s_max["miles_from_addr_out"], 2),
             "date": str(s_max["date"])},
            [s_max["session_id"]])

        # Q18 sessions >5mi
        far = [s for s in sessions if s["miles_from_addr"] > 5.0 or s["miles_from_addr_out"] > 5.0]
        add("Q18", "Are there any care sessions on claim XYZ where pings occurred more than 5 miles from the policyholder's address?",
            "object",
            {"any_far": bool(far), "count": len(far)},
            [s["session_id"] for s in far[:10]])

        # Q19 different check-in vs check-out devices
        diff_dev = [s for s in sessions if s["in_device"] != s["out_device"]]
        add("Q19", "Are there any care sessions where the check-in and check-out devices are different for claim XYZ?",
            "object",
            {"any_different": bool(diff_dev), "count": len(diff_dev)},
            [s["session_id"] for s in diff_dev[:10]])

        # Q20 ICPs sharing devices
        device_to_icps: dict[str, set[str]] = {}
        for s in sessions:
            device_to_icps.setdefault(s["in_device"], set()).add(s["icp_person_id"])
            device_to_icps.setdefault(s["out_device"], set()).add(s["icp_person_id"])
        shared = {d: list(icps) for d, icps in device_to_icps.items() if len(icps) > 1}
        add("Q20", "Are any ICPs on claim XYZ using the same device ID across their sessions?",
            "object",
            {"any_shared": bool(shared), "shared_devices": shared},
            list(shared.keys()))

    # Q23 MMSE
    if clinical.get("mmse"):
        aid, score, _ = clinical["mmse"]
        add("Q23", "What is the MMSE score for the claimant on claim XYZ?",
            "number", score, [aid])

    # Q24 cognitively impaired
    add("Q24", "Is the claimant on claim XYZ cognitively impaired?",
        "bool",
        clinical.get("cognitive_impaired", False),
        [clinical["mmse"][0]] if clinical.get("mmse") else [])

    # Q25 diagnoses
    add("Q25", "What diagnoses are on file for claim XYZ?",
        "list",
        [f"{c} - {d}" for (_, c, d) in clinical.get("diagnoses", [])],
        [did for (did, _, _) in clinical.get("diagnoses", [])])

    # Q26 ADLs
    add("Q26", "What ADLs are being provided for claim XYZ?",
        "list",
        [{"name": n, "frequency_per_day": f} for (_, n, f) in clinical.get("adls", [])],
        [aid for (aid, _, _) in clinical.get("adls", [])])

    # Q28 hourly rate per ICP
    rate_per = financial.get("rate_per_icp", {})
    add("Q28", "What is the hourly rate of each ICP for claim XYZ?",
        "object",
        {name_lookup.get(pid, pid): rate for pid, rate in rate_per.items()},
        list(rate_per.keys()))

    # Q31 bank accounts on payments
    bank_ids = [i["bank_id"] for i in care_ops.get("icps", [])]
    add("Q31", "Which bank accounts are associated with payments on claim XYZ?",
        "list", bank_ids, bank_ids)

    # Q32 total paid per ICP
    paid = financial.get("total_paid_per_icp", {})
    add("Q32", "What is the total paid amount to each ICP on claim XYZ?",
        "object",
        {name_lookup.get(pid, pid): amt for pid, amt in paid.items()},
        list(paid.keys()))

    # Q33 ongoing review cycle
    cyc = workflow.get("cycle")
    add("Q33", "Is there an ongoing review cycle for claim XYZ?",
        "bool",
        bool(cyc and cyc[2]),
        [cyc[0]] if cyc else [])

    # Q34 metrics that triggered
    add("Q34", "What metrics triggered the most recent review cycle for claim XYZ?",
        "list",
        workflow.get("triggered", []),
        [cyc[0]] if cyc else [])

    # Q36 remediation
    rem = workflow.get("remediation")
    add("Q36", "Was there any remediation for claim XYZ, and what was the recovery amount?",
        "object",
        {"any": bool(rem), "recovery_amount": rem[1] if rem else 0},
        [rem[0]] if rem else [])

    # Q37 ICP shares address with policyholder
    primary_addr = claim_anchor["primary_address"]
    icps_sharing = [i for i in care_ops.get("icps", []) if i["address_id"] == primary_addr]
    add("Q37", "Does the ICP on claim XYZ share a home address with the policyholder?",
        "object",
        {"any": bool(icps_sharing), "icps": [i["name"] for i in icps_sharing]},
        [i["person_id"] for i in icps_sharing])

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", default="data/processed/nodes.csv")
    ap.add_argument("--edges", default="data/processed/edges.csv")
    ap.add_argument("--eval-out", default="eval/generated_qa.csv")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--suspicious-rate", type=float, default=0.12)
    ap.add_argument("--limit-claims", type=int, default=0,
                    help="If >0, only extend this many claims (for fast iteration).")
    ap.add_argument("--force", action="store_true",
                    help="Allow extending even if extended types already present.")
    args = ap.parse_args(argv)

    nodes_path = (PROJECT_ROOT / args.nodes).resolve()
    edges_path = (PROJECT_ROOT / args.edges).resolve()
    eval_path = (PROJECT_ROOT / args.eval_out).resolve()

    nodes, edges = load_existing(nodes_path, edges_path)
    by_type = index_nodes(nodes)
    if not args.force and any(t in by_type for t in
                              ("CareSession", "Invoice", "Diagnosis", "ReviewCycle")):
        print("ERROR: graph already contains extended types. Re-run with --force to regenerate.",
              file=sys.stderr)
        return 2

    # If --force, drop previously appended ext_* rows
    if args.force:
        nodes = [n for n in nodes if not (n.get("source_table") or "").startswith("ext_")]
        edges = [e for e in edges if not (e.get("source_table") or "").startswith("ext_")]
        # also drop new node types entirely (in case source_table missing)
        new_types = {"CareSession", "Device", "Diagnosis", "Assessment", "ADL",
                     "Rider", "Benefit", "Invoice", "Charge", "Payment",
                     "ReviewCycle", "TriggerMetric", "Remediation"}
        kept_nids = {n["node_id"] for n in nodes if n["node_type"] not in new_types}
        nodes = [n for n in nodes if n["node_id"] in kept_nids]
        edges = [e for e in edges if e["source_node_id"] in kept_nids and e["target_node_id"] in kept_nids]

    state = GraphState(nodes=list(nodes), edges=list(edges),
                       node_ids={n["node_id"] for n in nodes},
                       edge_id_seq=len(edges))

    rng = random.Random(args.seed)
    anchors = claims_with_anchors(state.nodes, state.edges)
    if args.limit_claims > 0:
        anchors = anchors[: args.limit_claims]

    print(f"Extending {len(anchors)} claims (seed={args.seed}).")

    # name lookup for eval prose
    name_lookup: dict[str, str] = {n["node_id"]: n.get("label", n["node_id"]) for n in state.nodes}

    # riders + benefits per policy
    policy_ids = {a["policy_id"] for a in anchors}
    generate_riders_and_benefits(state, rng, policy_ids)

    # per-claim layers
    addr_idx = [10000]
    bank_idx = [20000]
    person_idx = [30000]
    device_pool: dict[str, str] = {}
    hhca_pool: dict[str, str] = {}
    address_nodes = [n for n in state.nodes if n["node_type"] == "Address"]

    eval_rows: list[dict] = []
    motif_choices = ["icp_address_collision", "device_reuse", "distance_anomaly", "manual_high_charge"]

    for k, anchor in enumerate(anchors):
        # decide suspicious motifs for this claim
        if rng.random() < args.suspicious_rate:
            n_motifs = rng.choices([1, 2], weights=[0.7, 0.3])[0]
            motifs = set(rng.sample(motif_choices, n_motifs))
        else:
            motifs = set()

        clinical = generate_clinical(state, rng, anchor)
        # refresh address_nodes after riders/benefits/etc.
        address_nodes = [n for n in state.nodes if n["node_type"] == "Address"]
        care = generate_care_ops(state, rng, anchor, addr_idx, bank_idx, person_idx,
                                 device_pool, hhca_pool, address_nodes, motifs)
        # update name lookup with new ICPs
        for n in state.nodes:
            if n["node_id"] not in name_lookup:
                name_lookup[n["node_id"]] = n.get("label", n["node_id"])
        finance = generate_financial(state, rng, anchor, care, motifs)
        workflow = generate_workflow(state, rng, anchor, care, motifs)
        eval_rows.extend(build_eval_rows(anchor, clinical, care, finance, workflow,
                                         address_nodes, name_lookup))
        if (k + 1) % 50 == 0:
            print(f"  ... {k+1}/{len(anchors)} claims")

    # write back
    print(f"Writing {len(state.nodes)} nodes, {len(state.edges)} edges.")
    with nodes_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["node_id", "node_type", "label", "source_table", "properties_json"])
        w.writeheader()
        w.writerows(state.nodes)
    with edges_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["edge_id", "source_node_id", "target_node_id", "edge_type", "source_table", "properties_json"])
        w.writeheader()
        w.writerows(state.edges)

    # write eval set
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    with eval_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "claim_node_id", "claim_number",
                                          "question_template", "question_text",
                                          "expected_answer_type", "expected_answer",
                                          "evidence_node_ids", "notes"])
        w.writeheader()
        w.writerows(eval_rows)
    print(f"Wrote eval set: {eval_path}  ({len(eval_rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
